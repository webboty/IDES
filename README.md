# IDES — Intelligent Document Extraction System

> Async PDF-to-Markdown extraction service with adaptive multi-layer pipeline.
> Built for integration with n8n, automation platforms, and direct API consumption.

---

## What It Does

IDES takes a PDF (invoice, offer, contract, any business document) and returns structured Markdown. It uses a **cheapest-first** strategy:

1. **pdfplumber** reads the digital text layer (free, instant)
2. **Tesseract OCR** handles scanned pages (free, fast)
3. **Vision LLM** handles everything else (paid API or local model)
4. An **agent fusion layer** cross-validates numbers across all sources and merges results

Every page is classified automatically. Boilerplate pages (AGB, impressum, privacy policy) are skipped. Only the layers a page actually needs are invoked.

---

## Features

- **Async job queue** — submit a PDF, poll for results
- **Multi-layer extraction** — text layer, OCR, vision LLM, embedded images
- **Number validation** — cross-validates every number across all sources
- **Boilerplate detection** — regex + optional LLM-based skipping
- **API key security** — per-user keys with IP restrictions, admin key management
- **Retry + agent recovery** — up to 3 attempts with LLM-analyzed failure recovery
- **n8n-ready** — works with n8n HTTP Request nodes out of the box
- **Dual LLM backend** — local Ollama (via Tailscale VPN) and/or OpenAI cloud

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) with language packs (`deu`, `eng`, `rus`)
- [Poppler](https://poppler.freedesktop.org/) for `pdf2image`
- (Optional) Local LLM server like [Ollama](https://ollama.com) for vision/merge

### Install

```bash
git clone https://github.com/your-org/ides.git
cd ides

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### System Dependencies

**macOS:**
```bash
brew install tesseract tesseract-lang poppler
```

**Ubuntu/Debian:**
```bash
apt update && apt install -y \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-rus \
    poppler-utils python3.12-venv
```

### Configure

```bash
cp config.yaml config.yaml         # edit to match your setup

# Required environment variables
export IDES_ADMIN_KEY="your-secret-admin-key"
export OPENAI_API_KEY="sk-..."     # only if using OpenAI provider
```

See [documentation/configuration.md](documentation/configuration.md) for all options.

### Run

```bash
# Development
uvicorn ides.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn ides.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### First API Key

```bash
curl -X POST http://localhost:8000/admin/keys \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-key", "owner": "me"}'
```

Save the returned `key` (starts with `ides_`) — it's shown only once.

### Extract a PDF

```bash
curl -X POST http://localhost:8000/extract \
  -H "X-API-Key: ides_your-key-here" \
  -F "file=@invoice.pdf" \
  -F "pages=all" \
  -F "skip_boilerplate=true"

# Response: {"job_id": "abc123...", "status": "pending"}

# Poll status
curl http://localhost:8000/jobs/abc123... \
  -H "X-API-Key: ides_your-key-here"

# Get result
curl http://localhost:8000/jobs/abc123.../result \
  -H "X-API-Key: ides_your-key-here"
```

---

## API Reference

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/extract` | POST | API Key | Submit PDF for extraction |
| `/jobs/{id}` | GET | API Key | Get job status & progress |
| `/jobs/{id}/result` | GET | API Key | Get final markdown output |
| `/jobs/{id}/detail` | GET | API Key | Get full per-page breakdown |
| `/admin/keys` | POST | Admin Key | Create new API key |
| `/admin/keys` | GET | Admin Key | List all API keys |
| `/admin/keys/{id}` | DELETE | Admin Key | Deactivate an API key |
| `/health` | GET | None | Health check |

See [documentation/api-reference.md](documentation/api-reference.md) for full request/response schemas.

---

## n8n Integration

In an n8n HTTP Request node:

```
Method: POST
URL: https://your-vps:8000/extract
Authentication: Header Auth
  Header Name: X-API-Key
  Header Value: ides_your-key-here
Body Content Type: Multipart-Form Data
Body Parameters:
  - file: n8n Binary Data
  - pages: "all"
  - skip_boilerplate: "true"
```

Then poll `GET /jobs/{job_id}` until `status == "completed"`, then fetch `GET /jobs/{job_id}/result`.

---

## Project Structure

```
ides/
├── ides/                    # Application source
│   ├── main.py              # FastAPI app + worker
│   ├── config.py            # YAML + env var config
│   ├── models.py            # Pydantic schemas
│   ├── security.py          # Auth middleware
│   ├── api/                 # HTTP endpoints
│   ├── pipeline/            # Pre-filter + orchestrator
│   ├── extractors/          # Text, OCR, vision, images
│   ├── agent/               # Fusion agent + tools
│   ├── fusion/              # Merge rules + LLM fusion
│   ├── llm/                 # OpenAI-compatible client
│   ├── storage/             # SQLite + file store
│   └── utils/               # PDF/image operations
├── tests/                   # 85 tests
├── config.yaml              # Configuration file
├── pyproject.toml           # Dependencies
└── documentation/           # Docs
```

---

## License

MIT
