# IDES — Architecture Reference

This document describes how IDES is built and why it is designed the way it is.
For deployment instructions see [DEPLOY.md](DEPLOY.md). For the CLI reference see [CLI.md](CLI.md).

---

## Design Principle

**Use the cheapest extraction method that works. Only escalate to expensive layers when cheaper ones are insufficient.**

Every PDF page goes through a fast pre-filter (pdfplumber, no API calls) that classifies it before any expensive work is done. The result drives which layers are invoked per page — from "text layer only" (free, ~10 ms) up to "text + OCR + Vision LLM" for the hardest pages.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      SECURITY LAYER                        │
│  SHA-256 hashed API keys · per-IP restriction · admin key  │
└──────────────────────────┬─────────────────────────────────┘
                           │
   Client ──POST /extract──▶  FastAPI  ──▶  SQLite job queue
   (n8n / curl / SDK)         (HTTP)              │
                              │                   │  poll every 2 s
                         GET /jobs/{id}    Async Worker
                         GET /result       (embedded in uvicorn)
                         GET /detail              │
                         POST /admin/keys         ▼
                         DELETE /admin/keys  ┌─────────────┐
                                             │ Pre-Filter  │
                                             │ (pdfplumber │
                                             │  all pages) │
                                             └──────┬──────┘
                                                    │ per-page classification
                                     ┌──────────────┼──────────────┐
                                     ▼              ▼              ▼
                               Text Layer          OCR           Vision
                               (pdfplumber)    (Tesseract)    (LLM call)
                                     └──────────────┼──────────────┘
                                                    ▼
                                             Fusion Agent
                                         (LLM — cross-validate
                                          numbers, merge sources)
                                                    │
                                          ┌─────────┴──────────┐
                                          ▼                     ▼
                                    File Store              SQLite
                                 /data/jobs/YYYY/       status = completed
                                   MM/DD/{id}/
```

**Network topology:**
```
Client (cloud / LAN)
        │
        └──HTTPS──▶ VPS  (IDES API + Worker)
                     │
                     ├── Tailscale VPN ──▶ Office LLM  (192.168.1.107:11435)
                     │
                     └── HTTPS ──────────▶ OpenAI Cloud API  (fallback)
```

---

## Adaptive Pipeline

### Phase A — Pre-Filter (runs on every page, zero LLM cost)

pdfplumber scans every page and assigns a classification. Boilerplate pages (AGB, Impressum, privacy policy) are detected by configurable regex patterns, then optionally confirmed by a cheap LLM call. Once a boilerplate cascade begins (typically from the last pages backwards), all subsequent pages are skipped.

| Classification | Trigger condition | Layers invoked |
|---|---|---|
| `boilerplate` | Pattern match or LLM confirm | **SKIP** |
| `structured_text` | char_count > 500 AND tables present | text_layer only |
| `text_only` | char_count > 200, no tables | text_layer + OCR (number verify) |
| `scanned` | char_count ≈ 0, OCR finds text | OCR + Vision |
| `image_only` | char_count ≈ 0, OCR finds nothing | Vision only |
| `mixed` | char_count 50–200 | text_layer + OCR + Vision |

Configurable thresholds in `config.yaml`:
```yaml
thresholds:
  text_rich:     500   # chars → structured_text
  text_moderate: 200   # chars → text_only
  text_sparse:    50   # chars → mixed
  min_image_size: 100  # px   → skip tiny icons/bullets
```

### Phase B — Layer Extraction

**Text Layer** (`extractors/text_layer.py`)
pdfplumber reads the digital text layer directly. Produces text, Markdown tables, and a character-level position map used by the fusion agent for number verification.

**OCR** (`extractors/ocr.py`)
pdf2image converts the page at 300 DPI → OpenCV greyscale + Otsu threshold + dilate preprocessing → Tesseract. Language defaults to `deu+eng+rus` (configurable per-request via `lang` parameter).

**Vision** (`extractors/vision.py`)
pdf2image converts the page at 200 DPI → base64-encoded PNG → LLM multimodal call. Thinking blocks (`<think>…</think>`) from reasoning models are stripped automatically.

**Image extraction** (`extractors/images.py`)
PyMuPDF extracts embedded images from the PDF. Images smaller than `thresholds.min_image_size` are skipped. Kept images are described by a separate cheap LLM call.

### Phase C — Fusion Agent (`fusion/llm_merge.py`, `agent/brain.py`)

A custom `FusionAgent` class (no external SDK) makes a single LLM call per page with all layer outputs in the prompt. The agent is instructed to:

1. Cross-validate every number across all sources before emitting it
2. Prefer pdfplumber character-level data for exact numeric values
3. Prefer Vision output for layout and table structure
4. Suppress all internal reasoning — output clean Markdown only

**Source priority:**
```
Numbers/text:  pdfplumber char_map > Tesseract OCR > Vision LLM
Layout/tables: Vision LLM > pdfplumber tables > Tesseract
Images:        Extracted embedded image > Vision LLM description
```

---

## Database Schema

```sql
CREATE TABLE api_keys (
    id          TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL UNIQUE,   -- SHA-256(raw_key), raw key never stored
    key_prefix  TEXT NOT NULL,          -- first 9 chars, shown in listings
    name        TEXT NOT NULL,
    owner       TEXT NOT NULL,
    allowed_ips TEXT,                   -- JSON array or NULL (unrestricted)
    is_active   INTEGER DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    expires_at  TIMESTAMP
);

CREATE INDEX idx_api_keys_hash   ON api_keys(key_hash);
CREATE INDEX idx_api_keys_active ON api_keys(is_active);

CREATE TABLE jobs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'pending',
    -- pending | processing | retrying | recovering | completed | failed | cancelled
    original_filename   TEXT NOT NULL,
    storage_path        TEXT NOT NULL,  -- relative: jobs/YYYY/MM/DD/{id}
    job_date            TEXT,           -- YYYY-MM-DD, used for date-based queries/CLI
    options             TEXT,           -- JSON: full ExtractOptions
    attempt             INTEGER DEFAULT 1,
    max_attempts        INTEGER DEFAULT 3,
    last_error          TEXT,
    agent_recovery_plan TEXT,           -- JSON: agent's adjusted plan (attempt 3)
    error_analysis      TEXT,
    retry_history       TEXT,           -- JSON array of {attempt, error, timestamp}
    result_summary      TEXT,           -- JSON: lightweight metadata (no markdown)
    progress_current    INTEGER DEFAULT 0,
    progress_total      INTEGER DEFAULT 0,
    pages_skipped       INTEGER DEFAULT 0,
    layers_stats        TEXT,           -- JSON: {text_layer: N, ocr: N, vision: N}
    opencode_session_id TEXT,           -- reserved
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_jobs_status  ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at);
CREATE INDEX idx_jobs_date    ON jobs(job_date);
```

Schema migrations run automatically at startup (`storage/database.py → _migrate()`). Currently handles adding `job_date` to databases created before that column existed.

---

## File Storage Layout

Every job gets an isolated directory under `{storage.base_path}`:

```
{base_path}/
├── ides.db
└── jobs/
    └── 2026/
        └── 04/
            └── 17/
                └── {job_id}/
                    ├── original.pdf          # uploaded PDF, untouched
                    ├── meta.json             # options + page_count at submission time
                    ├── classification.json   # per-page: classification, layers_to_use, skipped
                    ├── pages/
                    │   ├── page_001_vision.png   # 200 DPI for Vision LLM
                    │   ├── page_001_ocr.png      # 300 DPI preprocessed for Tesseract
                    │   └── page_001_images/      # extracted embedded images
                    ├── layers/
                    │   ├── page_001_text.json    # {text, tables, char_map, markdown}
                    │   ├── page_001_ocr.json     # {text}
                    │   ├── page_001_vision.md    # raw Vision LLM output
                    │   └── page_001_images.json  # [{index, path, description}]
                    ├── fusion/
                    │   └── page_001_merged.md    # Fusion Agent output per page
                    └── result/
                        ├── final.md              # assembled document (served by /result)
                        └── result.json           # full per-page detail (served by /detail)
```

`jobs.storage_path` in SQLite stores the relative path (e.g. `jobs/2026/04/17/abc123`). `FileStore` prepends `base_path` to resolve the absolute path. This means the DB record is the single source of truth — files can be on any mount as long as `base_path` is consistent.

---

## LLM Client

`llm/client.py` wraps the OpenAI SDK into a single `LLMClient` that supports multiple named providers (local + cloud). All providers use the OpenAI-compatible chat completions API.

Key behaviours:
- Uses `max_completion_tokens` (not `max_tokens`) — required by newer models such as gpt-5.4-nano which reject the old parameter name
- Per-call `asyncio.wait_for` timeout from provider config
- On any single call failure the provider is **not** marked unavailable — the error is propagated to the caller, which decides whether to retry or fall back
- `check_all()` at startup pings every configured provider and logs its status; extraction continues regardless

```python
response = await asyncio.wait_for(
    client.chat.completions.create(
        model=model_config["name"],
        messages=messages,
        max_completion_tokens=model_config.get("max_tokens", 4000),
        **kwargs,
    ),
    timeout=timeout,
)
```

---

## Security Model

Two independent, layered IP controls are available.

**1. Global service allowlist** (`server.allowed_ips` in `config.yaml`)

Blocks the entire service from IPs not on the list. Applied in the middleware before any key validation — no request from an unlisted IP reaches any endpoint.

```yaml
server:
  allowed_ips:       # omit or set to [] to allow all IPs
    - "1.2.3.4"
    - "10.0.0.5"
```

**2. Per-key IP restriction** (`allowed_ips` column on each API key)

Restricts an individual API key to specific caller IPs. Other keys from the same IP are unaffected. Set at key creation time via `ides keys create --ips "1.2.3.4,10.0.0.5"` or the admin HTTP API.

**API keys**
- Generated as `ides_{secrets.token_hex(16)}`
- Only the SHA-256 hash is stored; the raw key is shown once and never persisted
- Optional per-key `allowed_ips` (JSON array): requests using that key from other IPs get 401
- Optional `expires_at`: expired keys get 401 silently
- Soft-delete (`is_active = 0`) — revoked keys remain in DB for audit

**Admin key**
- Single master key from `config.server.master_admin_key` (env var recommended)
- Guard checks `if not expected or not admin_key or admin_key != expected` — prevents bypass when the env var is unset (empty string would otherwise match an empty header)

**Middleware order** (`security.py`)
1. Global IP allowlist check → 403 if IP not listed (when list is non-empty)
2. `/admin/*` → admin key check → 401 if invalid
3. `/extract`, `/jobs/*` → API key + per-key IP + expiry → 401 if any check fails, then `last_used_at` update
4. All other paths (health checks) → pass through

---

## Retry and Agent Recovery

```
Attempt 1: status = processing  — standard pipeline
Attempt 2: status = retrying    — same pipeline, fresh state
Attempt 3: status = recovering  — FusionAgent analyses prior errors,
                                   produces adjusted page-level plan,
                                   pipeline uses overrides
All failed: status = failed     — last_error + error_analysis stored in DB
```

Between attempts: exponential backoff (`retry.backoff_base × attempt` seconds).

Recovery analysis looks at `last_error`, `retry_history`, and the existing `classification.json` to suggest per-page layer overrides (e.g. "skip vision on page 4, use OCR only").

---

## Worker Design

The job worker runs as a single `asyncio` task inside the uvicorn process — no separate process, no cron, no message broker needed at this scale.

```
lifespan startup
  └── asyncio.create_task(_worker_loop())
            │
            └── while True:
                  pending = get_pending_jobs(limit=max_concurrent_jobs)
                  if pending:
                    for job in pending:
                        update status → processing
                        create_task(_run_job_with_semaphore())
                    await gather(all tasks)
                  else:
                    await sleep(worker_poll_interval)
```

Concurrency is controlled by an `asyncio.Semaphore(max_concurrent_jobs)`. Each job also has a hard wall-clock timeout (`job_timeout`, default 3600 s).

**Important:** always run with `--workers 1`. Multiple uvicorn workers would each start their own polling loop and process the same jobs simultaneously.

---

## Configuration Reference

All values can be overridden by environment variables (Pydantic Settings). See `config.yaml` for the live defaults.

```yaml
server:
  host: "127.0.0.1"
  port: 8000
  master_admin_key: "${IDES_ADMIN_KEY}"

storage:
  base_path: "./data"

providers:
  local:                              # local LLM via Tailscale VPN
    base_url: "http://192.168.1.107:11435/v1"
    api_key: "not-needed"
    timeout: 180
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    timeout: 60

models:                               # each model: provider + name + max_tokens
  vision:        { provider: openai, name: gpt-5.4-nano, max_tokens: 4000 }
  merge:         { provider: openai, name: gpt-5.4-nano, max_tokens: 4000 }
  filter:        { provider: openai, name: gpt-5.4-nano, max_tokens: 200  }
  image_describe:{ provider: openai, name: gpt-5.4-nano, max_tokens: 500  }

extraction:
  dpi:
    vision: 200      # lower DPI → cheaper, faster
    ocr:    300      # higher DPI → better Tesseract accuracy
  ocr_languages: "deu+eng+rus"
  max_pages: 50
  max_file_size_mb: 50
  skip_boilerplate: true
  boilerplate_patterns:
    - "(?i)allgemeine.{0,5}geschäft"
    - "(?i)terms.{0,10}conditions"
    - "(?i)datenschutz"
    - "(?i)impressum"
    - "(?i)privacy.{0,5}policy"

thresholds:
  text_rich: 500
  text_moderate: 200
  text_sparse: 50
  min_image_size: 100

retry:
  max_attempts: 3
  backoff_base: 5

queue:
  max_concurrent_jobs: 2
  job_timeout: 3600
  worker_poll_interval: 2
```

---

## Scaling Path

IDES is designed so each infrastructure component is swappable with a single module change:

| Component | Current (MVP) | Scale-up swap |
|---|---|---|
| Job queue | SQLite + asyncio poll | `job_store.py` → Redis + RQ |
| Workers | In-process asyncio task | Separate Celery worker process |
| File storage | Local filesystem | `file_store.py` → S3 / MinIO |
| Database | SQLite (aiosqlite) | `database.py` → PostgreSQL (asyncpg) |
| API | Single uvicorn | nginx + gunicorn multi-worker |
