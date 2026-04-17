# Architecture & Pipeline

## System Architecture

```
n8n (cloud) ──HTTPS──▶ VPS (IDES API)
                         │
                         ├── Tailscale VPN ──▶ Office LLM (Ollama)
                         │
                         └── HTTPS ──────────▶ OpenAI Cloud API
```

## Request Flow

```
Client ──POST /extract──▶ FastAPI
                              │
                              ├── Validate API key
                              ├── Store PDF
                              ├── Create job (status: pending)
                              └── Return job_id
                                      
                              Worker (async background)
                              │
                              ├── Pick pending job
                              ├── Pre-filter all pages (cheap)
                              │   ├── Extract text with pdfplumber
                              │   ├── Classify each page
                              │   └── Detect boilerplate
                              │
                              ├── For each non-skipped page:
                              │   ├── Run needed extractors
                              │   │   ├── text_layer (pdfplumber)
                              │   │   ├── ocr (Tesseract + OpenCV)
                              │   │   ├── vision (LLM image→markdown)
                              │   │   └── images (extract + describe)
                              │   │
                              │   └── Fuse layers into page markdown
                              │       ├── Programmatic rules (cheap)
                              │       └── Agent fusion (LLM, if needed)
                              │
                              ├── Assemble final document
                              └── Store result (status: completed)
```

## Page Classification

Each page is classified based on text content:

| Classification | Condition | Layers Used |
|---|---|---|
| `structured_text` | >500 chars + tables | text_layer only |
| `text_only` | >200 chars | text_layer + OCR verify |
| `mixed` | 50-200 chars | text_layer + OCR + vision |
| `scanned` | ~0 chars, OCR has text | OCR + vision |
| `image_only` | ~0 chars, no OCR text | vision only |
| `boilerplate` | Pattern/LLM match | **SKIP** |

## Fusion Priority

When multiple extraction sources exist for a page:

**For text/numbers:**
1. pdfplumber char-level data (highest fidelity)
2. Tesseract OCR
3. Vision LLM (lowest priority for exact chars)

**For structure/layout:**
1. Vision LLM output (best at visual layout)
2. pdfplumber tables (good for tabular data)
3. Tesseract (no structure info)

## Number Validation

Every number found across sources is cross-validated:

1. Extract all numbers matching pattern `[\d\.,]+\d{2}`
2. If all sources agree → confidence: `high`
3. If sources disagree → prefer pdfplumber (confidence: `high`)
4. OCR-only number → confidence: `medium`
5. Vision-only number → confidence: `low`

## Job Storage Layout

```
data/
├── ides.db                              # SQLite database
└── jobs/
    └── {job_id}/
        ├── original.pdf                 # Uploaded PDF
        ├── meta.json                    # Job options + timestamps
        ├── classification.json          # Per-page classifications
        ├── pages/
        │   ├── page_001.pdf             # Split single-page PDF
        │   ├── page_001_vision.png      # 200 DPI image
        │   ├── page_001_ocr.png         # 300 DPI preprocessed
        │   └── page_001_images/
        │       ├── img_0.png
        │       └── img_1.png
        ├── layers/
        │   ├── page_001_text.json       # pdfplumber output
        │   ├── page_001_ocr.json        # Tesseract output
        │   ├── page_001_vision.md       # Vision LLM output
        │   └── page_001_images.json     # Extracted images
        ├── fusion/
        │   ├── page_001_merged.md       # Fused page markdown
        │   └── page_002_merged.md
        └── result/
            ├── final.md                 # Complete document
            └── result.json              # Full result object
```

## Database Schema

Two tables: `api_keys` and `jobs`. See `ides/storage/database.py` for the full schema.

Lightweight queries (status, progress) hit SQLite. Heavy content (full markdown, per-page details) is read from the filesystem.

## Retry & Recovery

Jobs retry up to `max_attempts` (default: 3) with exponential backoff:

- **Attempt 1**: Normal extraction
- **Attempt 2**: Retry with same config
- **Attempt 3**: Agent analyzes the error and produces an adjusted plan (e.g., skip OCR, skip vision, skip problematic pages)

If all attempts fail, the agent writes an `error_analysis` to the job record.

## Scaling Path

| Component | Current | Future |
|---|---|---|
| Queue | SQLite + asyncio poll | Redis + RQ/Celery |
| Workers | In-process asyncio | Separate worker processes |
| Storage | Local filesystem | S3/MinIO |
| DB | SQLite | PostgreSQL |
| API | Single uvicorn | nginx + gunicorn |
