# IDES — Intelligent Document Extraction System — Full Implementation Spec

> **Status: APPROVED** — Ready for handoff to implementation agent.
> This document is self-contained. An agent can build the entire system from this spec alone.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       SECURITY LAYER                             │
│  API Keys table (multi-key, per-owner, per-IP) + master admin   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
n8n ──POST /extract──▶ FastAPI ──▶ SQLite ──▶ Worker (async)
      (file upload or       │                    │
       base64 JSON)         │              ┌─────┴──────┐
                           │              │  Pipeline   │
                      GET /jobs/{id}      │  + Retry    │
                      GET /result         │  + Agent    │
                      GET /detail         │  Recovery   │
                      POST /admin/keys    └─────┬──────┘
                      DELETE /admin/keys         │
                              ┌──────────────────┤
                              ▼                  ▼
                      ┌──────────────┐    ┌──────────────┐
                      │  Pre-Filter   │    │ opencode.ai  │
                      │ (pdfplumber   │    │  Agent (the  │
                      │  + cheap OCR) │    │  "Brain")    │
                      └──────┬───────┘    └──────┬───────┘
                             │                    │
                             ▼                    ▼
                    Classify each page     Fusion + Number
                    - boilerplate → SKIP   Validation
                    - has text+structure
                      → text_layer only
                    - no text layer
                      → OCR + vision
                    - mixed → all layers
```

**Network topology:**
```
n8n (cloud) ──HTTPS──▶ VPS (IDES API)
                         │
                         ├── Tailscale VPN ──▶ Office LLM (192.168.1.141:11435)
                         │
                         └── HTTPS ──────────▶ OpenAI Cloud API
```

---

## 1. Project Overview

**IDES** is an asynchronous PDF extraction service that converts invoices, offers, and other business documents into structured Markdown using an adaptive, multi-layered pipeline.

**Key principle:** Use the cheapest extraction method that works. Only invoke expensive layers (LLM vision) when cheaper methods (pdfplumber, Tesseract) are insufficient.

**Stack:** Python 3.12, FastAPI, SQLite (aiosqlite), opencode.ai SDK, PyMuPDF, pdfplumber, Tesseract, OpenAI-compatible LLM client.

---

## 2. Directory Structure

```
ides/
├── pyproject.toml
├── config.yaml
├── ides/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app + lifespan (starts worker)
│   ├── config.py                   # Pydantic Settings from YAML + env vars
│   ├── models.py                   # All Pydantic schemas
│   ├── security.py                 # Auth middleware (API keys + admin key)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── jobs.py                 # POST /extract, GET /jobs/{id}, /result, /detail
│   │   └── admin.py               # POST/GET/DELETE /admin/keys
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Main pipeline: prefilter -> extract -> fuse
│   │   ├── prefilter.py            # Cheap scan all pages -> classification
│   │   └── page_plan.py            # Per-page extraction plan
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract extractor base class
│   │   ├── text_layer.py           # pdfplumber: text + tables + char_map
│   │   ├── ocr.py                  # Tesseract with image preprocessing
│   │   ├── vision.py               # Vision LLM: image -> markdown
│   │   └── images.py               # Extract embedded images + describe
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── brain.py                # opencode.ai SDK agent setup
│   │   ├── tools.py                # Agent tools: validate_numbers, merge, resolve
│   │   └── skills/
│   │       ├── invoice_extraction.md
│   │       ├── offer_extraction.md
│   │       └── general_document.md
│   ├── fusion/
│   │   ├── __init__.py
│   │   ├── rules.py                # Programmatic merge rules
│   │   └── llm_merge.py            # Agent-driven fusion
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py               # Unified async OpenAI-compatible client
│   │   └── prompts.py              # Default prompt templates
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py             # SQLite + aiosqlite setup
│   │   ├── job_store.py            # Job CRUD + retry history
│   │   └── file_store.py           # /data/jobs/{id}/ file operations
│   └── utils/
│       ├── __init__.py
│       ├── pdf_ops.py              # Page split, PDF->image, DPI
│       └── image_ops.py            # Grayscale, OTSU threshold, dilate
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_extractors.py
│   ├── test_fusion.py
│   └── test_pipeline.py
└── samples/                        # Test PDFs
```

---

## 3. Dependencies

```toml
[project]
name = "ides"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]>=0.115",
    "uvicorn[standard]>=0.30",
    "aiosqlite>=0.20",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "pdfplumber>=0.11",
    "pymupdf>=1.24",
    "pdf2image>=1.17",
    "pytesseract>=0.3",
    "Pillow>=10.0",
    "opencv-python-headless>=4.9",
    "openai>=1.30",
    "opencode>=0.1",
    "langdetect>=1.0",
    "httpx>=0.27",
    "passlib>=1.7",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "httpx"]

[project.scripts]
ides = "ides.main:cli"
```

---

## 4. Configuration

**`config.yaml`:**

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  master_admin_key: "${IDES_ADMIN_KEY}"       # Env var, separate from user API keys

storage:
  base_path: "./data"                          # Relative or absolute path

providers:
  local:
    base_url: "http://192.168.1.141:11435/v1"  # Via Tailscale VPN to office
    api_key: "not-needed"
    timeout: 180
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    timeout: 60

models:
  vision:
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 4000
  merge:                                       # Default agent/fusion model
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 4000
  filter:                                      # Cheap model for boilerplate detection
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 200
  image_describe:
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 500

extraction:
  dpi:
    vision: 200
    ocr: 300
  ocr_languages: "deu+eng+rus"
  max_pages: 50
  skip_boilerplate: true
  boilerplate_patterns:
    - "(?i)allgemeine.{0,5}geschäft"
    - "(?i)terms.{0,5}(and|&)conditions"
    - "(?i)datenschutz"
    - "(?i)impressum"
    - "(?i)privacy.{0,5}policy"

thresholds:
  text_rich: 500                               # chars — text_layer only
  text_moderate: 200                           # chars — text + OCR verify
  text_sparse: 50                              # chars — all layers
  min_image_size: 100                          # px — skip tiny icons/bullets

retry:
  max_attempts: 3
  backoff_base: 5                              # seconds: 5s, 10s between retries

queue:
  max_concurrent_jobs: 2
  job_timeout: 600                             # seconds per job
  worker_poll_interval: 2                      # seconds
```

---

## 5. Database Schema

```sql
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    allowed_ips TEXT,                           -- JSON array or NULL
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_active ON api_keys(is_active);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',     -- pending|processing|retrying|recovering|completed|failed
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    options TEXT,                               -- JSON: full ExtractOptions
    opencode_session_id TEXT,
    attempt INTEGER DEFAULT 1,
    max_attempts INTEGER DEFAULT 3,
    last_error TEXT,
    agent_recovery_plan TEXT,                   -- JSON: agent's suggested fix
    error_analysis TEXT,
    retry_history TEXT,                         -- JSON array
    result_summary TEXT,                        -- JSON: lightweight metadata
    progress_current INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    pages_skipped INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at);
```

**DB <-> Storage connection:**
- `jobs.storage_path` = `"jobs/{job_id}/"` (relative to `storage.base_path`)
- Lightweight queries (status, progress) -> SQLite
- Heavy content (full markdown, per-page details) -> read from file system via `file_store.py`

---

## 6. File Storage Layout

Every job gets an isolated directory under `{storage.base_path}/jobs/{job_id}/`:

```
{base_path}/
└── jobs/
    └── {job_id}/
        ├── original.pdf                       # Uploaded PDF (untouched)
        ├── meta.json                          # Job options + timestamps
        ├── pages/
        │   ├── page_001.pdf                   # Split single-page PDF (PyMuPDF)
        │   ├── page_001_vision.png            # 200 DPI image (for vision LLM)
        │   ├── page_001_ocr.png               # 300 DPI preprocessed (grayscale+OTSU+dilate)
        │   ├── page_001_images/
        │   │   ├── img_0.png                  # Extracted embedded image
        │   │   └── img_1.png
        │   ├── page_002.pdf
        │   ├── page_002_vision.png
        │   └── ...
        ├── layers/
        │   ├── page_001_text.json             # { text, tables, char_map, markdown }
        │   ├── page_001_ocr.json              # { text }
        │   ├── page_001_vision.md             # Raw vision LLM output
        │   ├── page_001_images.json           # [{ index, path, description }]
        │   ├── page_002_text.json
        │   └── ...
        ├── classification.json                # Per-page: { page_num, classification, layers_to_use, skipped }
        ├── fusion/
        │   ├── page_001_merged.md             # Fusion result per page
        │   ├── page_002_merged.md
        │   └── ...
        └── result/
            ├── final.md                       # Full assembled document
            └── result.json                    # Full ExtractionResult (served by GET /detail)
```

---

## 7. API Endpoints

### Authentication
- **Job endpoints** (`/extract`, `/jobs/*`): `X-API-Key: ides_xxxxx...` header (per-user key from `api_keys` table)
- **Admin endpoints** (`/admin/*`): `X-Admin-Key: <master>` header (from `config.yaml`)

### `POST /extract` — Submit PDF

Supports two content types:

**Multipart (file upload):**
```
POST /extract
Content-Type: multipart/form-data
X-API-Key: ides_...

Fields:
  file (binary)              — Required: PDF file
  pages (text)               — Optional: "1-5" or "1,3,7" or "all" (default: "all")
  prompt (text)              — Optional: override default vision extraction prompt
  merge_prompt (text)        — Optional: override default fusion/merge prompt
  lang (text)                — Optional: override OCR language e.g. "deu+eng+rus"
  skip_boilerplate (text)    — Optional: "true" or "false" (default: "true")
  agent_model (text)         — Optional: override agent/fusion model name
  agent_provider (text)      — Optional: "local" or "openai"
  opencode_skills (text)     — Optional: JSON array string e.g. '["invoice_extraction"]'
```

**JSON (base64):**
```
POST /extract
Content-Type: application/json
X-API-Key: ides_...

{
    "file_base64": "JVBERi0xLjQg...",
    "filename": "invoice.pdf",
    "pages": "all",
    "prompt": null,
    "merge_prompt": null,
    "lang": null,
    "skip_boilerplate": true,
    "agent_model": null,
    "agent_provider": null,
    "opencode_skills": []
}
```

**Response:**
```json
{ "job_id": "01HZX3KABC...", "status": "pending" }
```

### `GET /jobs/{job_id}` — Status
```json
{
    "job_id": "...",
    "status": "processing",
    "attempt": 1,
    "max_attempts": 3,
    "progress": {
        "current_page": 3,
        "total_pages": 10,
        "pages_skipped": 2,
        "layers_stats": { "text_layer": 1, "ocr": 2, "vision": 1 }
    },
    "retry_history": [],
    "opencode_session_id": "ses_abc123",
    "created_at": "...",
    "updated_at": "..."
}
```

### `GET /jobs/{job_id}/result` — Final output (lightweight)
```json
{
    "job_id": "...",
    "status": "completed",
    "markdown": "full document markdown string...",
    "metadata": {
        "pages_processed": 8,
        "pages_skipped": 2,
        "total_time_seconds": 45,
        "opencode_session_id": "ses_abc123"
    }
}
```

### `GET /jobs/{job_id}/detail` — Full breakdown (heavyweight)
```json
{
    "job_id": "...",
    "status": "completed",
    "markdown": "full document markdown...",
    "pages": [
        {
            "page": 1,
            "classification": "structured_text",
            "layers_used": ["text_layer"],
            "skipped": false,
            "layer_results": {
                "text_layer": { "char_count": 1234, "tables_found": 2 },
                "ocr": null,
                "vision": null
            },
            "markdown": "per-page markdown..."
        }
    ],
    "images": [
        { "page": 1, "index": 0, "description": "Company logo" }
    ],
    "opencode_session_id": "ses_abc123",
    "metadata": {
        "pages_processed": 8,
        "pages_skipped": 2,
        "layers_stats": { "text_layer": 6, "ocr": 3, "vision": 2 },
        "total_time_seconds": 45,
        "storage_path": "jobs/01HZX3KABC..."
    }
}
```

### `POST /admin/keys` — Create API key
```
X-Admin-Key: <master>
{ "name": "n8n-production", "owner": "n8n team", "allowed_ips": ["203.0.113.50"] }

Response:
{ "id": "uuid", "key": "ides_a3f2b8c1...FULL_KEY_SHOWN_ONCE", "key_prefix": "ides_a3f2", "name": "...", "owner": "..." }
```

### `GET /admin/keys` — List keys
```
X-Admin-Key: <master>
Response: [{ "id", "key_prefix", "name", "owner", "is_active", "allowed_ips", "last_used_at", "expires_at" }]
```

### `DELETE /admin/keys/{id}` — Deactivate key
```
X-Admin-Key: <master>
Response: { "deleted": true }
```
(Soft delete: `is_active = 0`)

---

## 8. Security Middleware

```python
# security.py
import hashlib

async def verify_api_key(api_key: str, client_ip: str, db) -> dict | None:
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    record = await db.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
        [key_hash]
    )
    row = record.fetchone()
    if not row:
        return None
    # Check IP restriction
    if row["allowed_ips"]:
        allowed = json.loads(row["allowed_ips"])
        if client_ip not in allowed:
            return None
    # Check expiry
    if row["expires_at"] and row["expires_at"] < datetime.utcnow():
        return None
    return dict(row)

@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path

    if path.startswith("/admin"):
        admin_key = request.headers.get("X-Admin-Key")
        if admin_key != config.server.master_admin_key:
            return JSONResponse(401, {"error": "Invalid admin key"})
        return await call_next(request)

    if path.startswith("/jobs") or path == "/extract":
        api_key = request.headers.get("X-API-Key")
        key_record = await verify_api_key(api_key, request.client.host, db)
        if not key_record:
            return JSONResponse(401, {"error": "Invalid API key or IP not allowed"})
        await db.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            [datetime.utcnow(), key_record["id"]]
        )
        return await call_next(request)

    return await call_next(request)
```

---

## 9. Pipeline — Adaptive Multi-Layer Engine

### Phase A: Pre-Filter (runs on ALL pages, cheap)

```python
# prefilter.py
async def classify_all_pages(pdf_path, config) -> list[PageClassification]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            char_count = len(text.strip())
            has_tables = len(tables) > 0

            classification = classify_page(char_count, has_tables)

            if classification != "boilerplate":
                if is_boilerplate(text, config.extraction.boilerplate_patterns):
                    classification = "boilerplate"

            results.append(PageClassification(
                page_num=i + 1,
                classification=classification,
                char_count=char_count,
                has_tables=has_tables,
                layers_needed=get_layers_for_classification(classification),
                skipped=(classification == "boilerplate")
            ))

    # For pages with no text, do quick OCR to check if they're blank or have content
    for pc in results:
        if pc.classification in ("scanned", "image_only"):
            ocr_text = quick_ocr(pdf_path, pc.page_num, config)
            if len(ocr_text.strip()) < 10:
                pc.classification = "image_only"
            else:
                pc.classification = "scanned"

    # If skip_boilerplate: run cheap LLM check on last few pages from end
    if config.extraction.skip_boilerplate:
        for pc in reversed(results):
            if pc.skipped:
                continue
            text = get_page_text(pdf_path, pc.page_num)
            if await llm_is_boilerplate(text, config):
                pc.skipped = True
                pc.classification = "boilerplate"
            else:
                break  # Stop at first non-boilerplate page from end

    return results
```

**Classification logic:**

| Classification | Condition | Layers invoked |
|---|---|---|
| `boilerplate` | Pattern match or LLM check | **SKIP** |
| `structured_text` | char_count > 500 AND has_tables | `text_layer` only |
| `text_only` | char_count > 200, no tables | `text_layer` + OCR (verify numbers) |
| `scanned` | char_count ~ 0, OCR has text | `OCR` + `vision` |
| `image_only` | char_count ~ 0, no OCR text | `vision` only |
| `mixed` | char_count 50-200 | `text_layer` + `OCR` + `vision` |

### Phase B: Layer Extraction

**Text Layer** (`text_layer.py`):
```python
def extract(pdf_path: str, page_num: int) -> TextLayerResult:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num - 1]
        text = page.extract_text() or ""
        tables = page.extract_tables() or []
        chars = page.chars  # Character-level positions for number validation

        # Convert tables to markdown
        table_markdown = []
        for table in tables:
            header = "| " + " | ".join(str(c or "") for c in table[0]) + " |"
            sep = "| " + " | ".join("---" for _ in table[0]) + " |"
            rows = ["| " + " | ".join(str(c or "") for c in row) + " |" for row in table[1:]]
            table_markdown.append(header + "\n" + sep + "\n" + "\n".join(rows))

        markdown = text
        if table_markdown:
            markdown += "\n\n" + "\n\n".join(table_markdown)

        return TextLayerResult(text=text, tables=tables, char_map=chars, markdown=markdown)
```

**OCR** (`ocr.py`):
```python
def extract(pdf_path: str, page_num: int, config) -> OCRResult:
    images = convert_from_path(pdf_path, dpi=config.extraction.dpi.ocr,
                               first_page=page_num, last_page=page_num)
    image = images[0]

    # Preprocess for Tesseract
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    kernel = np.ones((1, 1), np.uint8)
    gray = cv2.dilate(gray, kernel, iterations=1)

    text = pytesseract.image_to_string(gray, lang=config.extraction.ocr_languages)
    return OCRResult(text=text)
```

**Vision** (`vision.py`):
```python
async def extract(pdf_path: str, page_num: int, config, prompt: str = None) -> VisionResult:
    images = convert_from_path(pdf_path, dpi=config.extraction.dpi.vision,
                               first_page=page_num, last_page=page_num)
    image = images[0]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()

    effective_prompt = prompt or DEFAULT_VISION_PROMPT

    response = await llm_client.chat(
        model_config=config.models.vision,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": effective_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }],
        max_tokens=config.models.vision.max_tokens
    )

    # Strip thinking blocks (Qwen models)
    markdown = re.sub(r"<think.*?</think", "", response, flags=re.DOTALL).strip()
    return VisionResult(markdown=markdown)
```

**Images** (`images.py`):
```python
def extract_images(pdf_path: str, page_num: int, storage_path: str, config) -> ImageResult:
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    images = page.get_images(full=True)

    results = []
    img_dir = Path(storage_path) / f"pages/page_{page_num:03d}_images"
    img_dir.mkdir(parents=True, exist_ok=True)

    for idx, img in enumerate(images):
        xref = img[0]
        base_image = doc.extract_image(xref)
        if base_image["width"] < config.thresholds.min_image_size:
            continue
        img_path = img_dir / f"img_{idx}.png"
        img_path.write_bytes(base_image["image"])
        results.append({"index": idx, "path": str(img_path)})

    return ImageResult(images=results)

async def describe_images(images: list, config) -> list:
    descriptions = []
    for img in images:
        b64 = base64.b64encode(Path(img["path"]).read_bytes()).decode()
        desc = await llm_client.chat(
            model_config=config.models.image_describe,
            messages=[{...image + "Describe this image briefly"...}],
            max_tokens=config.models.image_describe.max_tokens
        )
        descriptions.append({**img, "description": desc})
    return descriptions
```

### Phase C: Agent-Driven Fusion

```python
# agent/brain.py
from opencode import Agent

def create_agent(config, job_options):
    model = job_options.agent_model or config.models.merge.name
    provider = job_options.agent_provider or config.models.merge.provider
    skills = job_options.opencode_skills or []

    agent = Agent(
        model=f"{provider}/{model}",
        skills=skills,
        tools=[validate_numbers, merge_sources, resolve_conflict],
        system_prompt=job_options.merge_prompt or DEFAULT_FUSION_PROMPT,
    )
    return agent

# fusion/llm_merge.py
async def fuse_page(agent, page_num, layer_results: dict, config) -> str:
    """Merge all layer outputs for a single page using agent."""
    result = await agent.run(
        f"Merge these extraction sources for page {page_num}:\n\n"
        f"VISION STRUCTURE:\n{layer_results.get('vision', {}).get('markdown', 'N/A')}\n\n"
        f"PDFPLUMBER TEXT:\n{layer_results.get('text_layer', {}).get('text', 'N/A')}\n\n"
        f"PDFPLUMBER TABLES:\n{layer_results.get('text_layer', {}).get('markdown', 'N/A')}\n\n"
        f"OCR TEXT:\n{layer_results.get('ocr', {}).get('text', 'N/A')}\n\n"
        f"Cross-validate ALL numbers. Resolve any conflicts. Output clean Markdown."
    )
    return result.output
```

**Number Validation (agent tool):**

```python
# agent/tools.py
import re

@tool
def validate_numbers(sources: dict) -> dict:
    """Extract and cross-validate all numbers across sources.

    Priority: pdfplumber char_map > OCR text > vision markdown
    Returns: { number_value: { sources, confidence, recommended } }
    """
    number_pattern = r'[\d\.,]+\d{2}'  # Matches amounts like 1.234,56 or 1234.56
    all_numbers = {}

    for source_name, content in sources.items():
        if not content:
            continue
        found = re.findall(number_pattern, content)
        for num in found:
            normalized = normalize_number(num)
            if normalized not in all_numbers:
                all_numbers[normalized] = {"sources": {}}
            all_numbers[normalized]["sources"][source_name] = num

    # Validate
    results = {}
    for num, info in all_numbers.items():
        sources_agree = len(set(info["sources"].values())) == 1
        confidence = "high" if sources_agree else "medium"

        # Prefer pdfplumber if available
        if "text_layer" in info["sources"]:
            recommended = info["sources"]["text_layer"]
            confidence = "high"
        elif "ocr" in info["sources"]:
            recommended = info["sources"]["ocr"]
        else:
            recommended = list(info["sources"].values())[0]
            confidence = "low"

        results[num] = {
            "sources": info["sources"],
            "confidence": confidence,
            "recommended": recommended
        }

    return results
```

### Fusion Priority Rules

```
For TEXT/NUMBERS:
  1. pdfplumber char-level extraction (highest fidelity for individual characters)
  2. Tesseract OCR (good for scanned text)
  3. Vision LLM (prone to hallucination on exact chars/numbers → lowest priority)

For STRUCTURE/LAYOUT:
  1. Vision LLM output (best at understanding visual layout)
  2. pdfplumber tables (good for tabular structure)
  3. Tesseract (no structure info)

For IMAGES:
  1. Extracted embedded image (highest fidelity)
  2. Vision LLM description (contextual understanding)
```

### Number Validation Flow

```
1. Extract all numbers from each source (regex: €?\d+[.,]\d{2})
2. If all sources agree → use the number (confidence: high)
3. If sources disagree:
   a. If pdfplumber has a number AND it has char-level data for it → use pdfplumber
   b. If OCR has a number that pdfplumber doesn't → use OCR but flag as "unverified"
   c. If only vision has it → lowest confidence, flag for review
4. Agent can make final call with reasoning
```

---

## 10. Job Status Values

| Status | Meaning |
|---|---|
| `pending` | Queued, waiting for worker |
| `processing` | Active extraction in progress |
| `retrying` | Failed once, retrying (attempt 2) |
| `recovering` | Agent analyzing failure, preparing adjusted plan (attempt 3) |
| `completed` | Done, result available |
| `failed` | All attempts exhausted, error_analysis available |

---

## API Key Format

Keys follow the format: `ides_{random_32_chars}` (e.g. `ides_a3f2b8c1d4e5f6g7h8i9j0k1l2m3n4o5`)

- Stored in DB as **SHA-256 hash** (original key never stored)
- `key_prefix` (first 8 chars) stored for identification in listings
- Full key shown **only once** at creation time
- Soft-delete via `is_active = 0`

---

## 11. Retry + Agent Recovery

```python
# pipeline/orchestrator.py
async def run_with_retry(job, config, db):
    for attempt in range(1, config.retry.max_attempts + 1):
        try:
            await db.update_job(job.id,
                status="processing" if attempt == 1 else "retrying",
                attempt=attempt
            )

            override_plan = None
            if attempt == 3 and job.last_error:
                await db.update_job(job.id, status="recovering")
                recovery = await agent.analyze_failure(
                    error=job.last_error,
                    classifications=file_store.load_classification(job.storage_path),
                    retry_history=job.retry_history
                )
                await db.update_job(job.id, agent_recovery_plan=json.dumps(recovery))
                override_plan = recovery.get("adjusted_plan")

            result = await run_pipeline(job, config, override_plan=override_plan)

            await db.store_result(job.id, result)
            await db.update_job(job.id, status="completed")
            return

        except Exception as e:
            error_record = {"attempt": attempt, "error": str(e), "timestamp": now_iso()}
            await db.append_retry_history(job.id, error_record)
            await db.update_job(job.id, last_error=str(e))

            if attempt < config.retry.max_attempts:
                await asyncio.sleep(config.retry.backoff_base * attempt)
                continue

    # All attempts failed -- agent analysis
    analysis = await agent.analyze_failure(
        error=job.last_error,
        retry_history=job.retry_history
    )
    await db.update_job(job.id,
        status="failed",
        error=job.last_error,
        error_analysis=analysis.get("explanation", "No analysis available")
    )
```

### Agent Recovery Tools

```python
# Used in attempt 3 (recovery mode)
@tool
def analyze_failure(error: str, retry_history: list, classifications: dict) -> dict:
    """Analyze why extraction failed and suggest a modified approach.
    Returns: { diagnosis: str, adjusted_plan: { page_overrides: {...} }, confidence: float }"""

@tool
def get_available_layers(storage_path: str) -> dict:
    """Check which layer outputs exist on disk for each page.
    Returns: { page_num: ["text_layer", "ocr", "vision"] }"""
```

---

## 12. Worker

```python
# main.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await init_database()
    worker_task = asyncio.create_task(worker_loop(db, config))
    yield
    worker_task.cancel()
    await db.close()

async def worker_loop(db, config):
    semaphore = asyncio.Semaphore(config.queue.max_concurrent_jobs)
    while True:
        pending = await db.get_pending_jobs(limit=config.queue.max_concurrent_jobs)
        if pending:
            for job in pending:
                await db.update_job(job.id, status="processing")
                async with semaphore:
                    await run_with_retry(job, config, db)
        else:
            await asyncio.sleep(config.queue.worker_poll_interval)
```

---

## 13. Default Prompts

**Vision extraction (`prompts.py`):**
```
Extract ALL text and structure from this document page as Markdown.
Rules:
- Preserve ALL tables using Markdown table syntax (| col1 | col2 |)
- Do NOT add positioning descriptions like (header), (footer), (box rechts)
- Do NOT wrap output in code blocks
- This must be a 100% complete reflection of the document
- Do NOT summarize or omit any content
- Preserve the original language exactly as written
- For numbers: reproduce EXACTLY as shown, including decimal separators
- Include all line items, totals, subtotals, tax amounts
```

**Fusion (agent system prompt):**
```
You are a document fusion agent merging multiple extraction sources into accurate Markdown.
CRITICAL RULES:
1. NUMBERS ARE SACRED — every digit, decimal, separator must be exact
2. Cross-validate ALL numbers across sources before including them
3. If sources disagree on a number, state which source you chose and why
4. Prefer pdfplumber for exact characters (reads digital text layer directly)
5. Prefer vision output for layout and table structure
6. Prefer OCR for text in scanned regions
7. Preserve original document language
8. Do NOT invent content not in any source
```

**Boilerplate:**
```
Is this page relevant business information or boilerplate (terms/legal/AGB/impressum)?
Content (first 500 chars): {content}
Answer ONE word: RELEVANT or BOILERPLATE
```

**All prompts are overridable via API parameters (`prompt`, `merge_prompt`).**

---

## 14. LLM Client

```python
# llm/client.py
class LLMClient:
    def __init__(self, providers: dict):
        self._clients = {
            name: AsyncOpenAI(base_url=p["base_url"], api_key=p["api_key"])
            for name, p in providers.items()
        }

    async def chat(self, model_config, messages: list, **kwargs) -> str:
        client = self._clients[model_config["provider"]]
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_config["name"],
                    messages=messages,
                    max_tokens=model_config.get("max_tokens", 4000),
                    **kwargs
                ),
                timeout=model_config.get("timeout", 120)
            )
        except asyncio.TimeoutError:
            raise ExtractionError(f"LLM timeout for model {model_config['name']}")

        text = response.choices[0].message.content
        return re.sub(r"<think.*?</think", "", text, flags=re.DOTALL).strip()

    async def chat_with_image(self, model_config, b64_image: str, prompt: str, **kwargs) -> str:
        return await self.chat(model_config, [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
            ]
        }], **kwargs)
```

---

## 15. Implementation Order (5 Hours)

| # | Task | Time | Key Files |
|---|---|---|---|
| 1 | Scaffold: dirs, pyproject.toml, config.py, models.py | 15m | All structure files |
| 2 | Storage: database.py, job_store.py, file_store.py | 30m | storage/* |
| 3 | Security: security.py (middleware) | 15m | security.py |
| 4 | API: jobs.py, admin.py, main.py | 30m | api/*, main.py |
| 5 | LLM: client.py, prompts.py | 20m | llm/* |
| 6 | Utils: pdf_ops.py, image_ops.py | 15m | utils/* |
| 7 | Extractors: text_layer, ocr, vision, images | 50m | extractors/* |
| 8 | Pre-filter + classification | 25m | pipeline/prefilter.py, page_plan.py |
| 9 | Agent + fusion + recovery tools | 45m | agent/*, fusion/* |
| 10 | Orchestrator + retry logic | 30m | pipeline/orchestrator.py |
| 11 | Worker + integration test | 25m | main.py worker, tests/ |

---

## 16. VPS Deployment

```bash
# System deps
apt update && apt install -y \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-rus \
    poppler-utils python3.12 python3.12-venv

# Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up

# App
python3.12 -m venv /opt/ides/venv
source /opt/ides/venv/bin/activate
cd /opt/ides && pip install -e .

# Configure
cp config.example.yaml config.yaml
# Set IDES_ADMIN_KEY, OPENAI_API_KEY env vars

# Run
uvicorn ides.main:app --host 0.0.0.0 --port 8000
```

---

## 17. n8n Integration Example

**n8n HTTP Request node configuration:**
```
Method: POST
URL: https://your-vps:8000/extract
Authentication: Header Auth
  Header Name: X-API-Key
  Header Value: ides_a3f2b8c1d4e5f6g7h8i9j0k1l2m3n4o5
Body Content Type: Multipart-Form Data
Body Parameters:
  - Name: file, Type: n8n Binary Data, Value: data
  - Name: pages, Type: Text, Value: "all"
  - Name: skip_boilerplate, Type: Text, Value: "true"
```

**Polling workflow (n8n):**
1. HTTP Request -> POST /extract -> get job_id
2. Wait 10s
3. Loop: HTTP Request -> GET /jobs/{job_id}
4. If status != "completed" -> Wait 5s -> goto 3
5. HTTP Request -> GET /jobs/{job_id}/result -> get markdown

---

## 18. Scaling Path

| Component | MVP | Scale-up (swap one module) |
|---|---|---|
| Queue | SQLite + asyncio poll | `job_store.py` -> Redis + RQ |
| Workers | In-process asyncio | Extract worker -> Celery |
| Storage | Local filesystem | `file_store.py` -> S3/MinIO |
| DB | SQLite | `database.py` -> PostgreSQL |
| Agent | Single opencode session | Agent pool |
| API | Single uvicorn | nginx + gunicorn |
