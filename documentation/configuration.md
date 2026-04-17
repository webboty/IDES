# Configuration Reference

IDES is configured via `config.yaml` with environment variable substitution.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `IDES_ADMIN_KEY` | Yes | Master admin key for `/admin/*` endpoints |
| `OPENAI_API_KEY` | If using OpenAI provider | OpenAI API key |

Usage in `config.yaml`:
```yaml
master_admin_key: "${IDES_ADMIN_KEY}"
api_key: "${OPENAI_API_KEY}"
```

---

## Full Config Reference

### `server`

```yaml
server:
  host: "0.0.0.0"           # Bind address
  port: 8000                 # Bind port
  master_admin_key: "${IDES_ADMIN_KEY}"
```

### `storage`

```yaml
storage:
  base_path: "./data"        # Base directory for job files and SQLite DB
```

All job files are stored under `{base_path}/jobs/{job_id}/`. The SQLite database is at `{base_path}/ides.db`.

### `providers`

LLM provider configurations. Each provider has:

```yaml
providers:
  local:                              # Provider name (referenced in models)
    base_url: "http://192.168.1.141:11435/v1"
    api_key: "not-needed"
    timeout: 180                      # Seconds
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    timeout: 60
```

The `local` provider is typically an Ollama instance accessed via Tailscale VPN. You can define any number of providers.

### `models`

Each model references a provider and sets parameters:

```yaml
models:
  vision:                             # Used for page image → markdown
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 4000
  merge:                              # Used for fusion / agent
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 4000
  filter:                             # Used for boilerplate LLM check
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 200
  image_describe:                     # Used for image description
    provider: "local"
    name: "qwen3.5-35b-a3b@bf16"
    max_tokens: 500
```

These can be overridden per-request via `agent_model` and `agent_provider` parameters.

### `extraction`

```yaml
extraction:
  dpi:
    vision: 200                       # DPI for vision LLM images (lower = faster)
    ocr: 300                          # DPI for OCR images (higher = more accurate)
  ocr_languages: "deu+eng+rus"        # Tesseract language packs
  max_pages: 50                       # Maximum pages per PDF
  skip_boilerplate: true              # Enable boilerplate detection
  boilerplate_patterns:               # Regex patterns for boilerplate detection
    - "(?i)allgemeine.{0,5}geschäft"
    - "(?i)terms.{0,10}conditions"
    - "(?i)datenschutz"
    - "(?i)impressum"
    - "(?i)privacy.{0,5}policy"
```

### `thresholds`

Controls page classification based on character count:

```yaml
thresholds:
  text_rich: 500       # >500 chars + tables → structured_text
  text_moderate: 200   # >200 chars → text_only
  text_sparse: 50      # >50 chars → mixed
                        # ≤50 chars → scanned
  min_image_size: 100   # Skip embedded images smaller than this (px)
```

### `retry`

```yaml
retry:
  max_attempts: 3              # Total extraction attempts per job
  backoff_base: 5              # Seconds between retries (5, 10, 15...)
```

On attempt 3, the agent analyzes the failure and adjusts the extraction plan.

### `queue`

```yaml
queue:
  max_concurrent_jobs: 2       # Parallel jobs
  job_timeout: 600             # Seconds per job before forced failure
  worker_poll_interval: 2      # Seconds between polling for new jobs
```

---

## Minimal Config (OpenAI only)

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  master_admin_key: "${IDES_ADMIN_KEY}"

storage:
  base_path: "./data"

providers:
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    timeout: 60

models:
  vision:
    provider: "openai"
    name: "gpt-4o"
    max_tokens: 4000
  merge:
    provider: "openai"
    name: "gpt-4o"
    max_tokens: 4000
  filter:
    provider: "openai"
    name: "gpt-4o-mini"
    max_tokens: 200
  image_describe:
    provider: "openai"
    name: "gpt-4o"
    max_tokens: 500

extraction:
  dpi:
    vision: 200
    ocr: 300
  ocr_languages: "deu+eng"
  max_pages: 50
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
  job_timeout: 600
  worker_poll_interval: 2
```
