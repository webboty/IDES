# Contributing Guide

## Development Setup

```bash
git clone https://github.com/your-org/ides.git
cd ides

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_api.py -v

# With coverage
pytest tests/ --cov=ides --cov-report=term-missing

# Quick (no verbose)
pytest tests/ -q
```

The test suite creates temporary directories and an in-memory SQLite database. No external services (LLM, Tesseract) are required for the core tests.

## Project Structure

```
ides/
├── ides/                        # Application
│   ├── main.py                  # FastAPI app + async worker
│   ├── config.py                # Pydantic settings from YAML + env vars
│   ├── models.py                # All Pydantic schemas
│   ├── security.py              # API key + admin key auth middleware
│   ├── api/
│   │   ├── jobs.py              # POST /extract, GET /jobs/{id}/*
│   │   └── admin.py             # POST/GET/DELETE /admin/keys
│   ├── pipeline/
│   │   ├── orchestrator.py      # Main pipeline + retry logic
│   │   ├── prefilter.py         # Page classification
│   │   └── page_plan.py         # Classification rules
│   ├── extractors/
│   │   ├── base.py              # Abstract extractor
│   │   ├── text_layer.py        # pdfplumber
│   │   ├── ocr.py               # Tesseract + OpenCV preprocessing
│   │   ├── vision.py            # Vision LLM
│   │   └── images.py            # Embedded image extraction + description
│   ├── agent/
│   │   ├── brain.py             # FusionAgent + number validation
│   │   ├── tools.py             # Recovery tools + failure analysis
│   │   └── skills/              # Markdown skill files
│   ├── fusion/
│   │   ├── rules.py             # Programmatic merge rules
│   │   └── llm_merge.py         # Agent-driven fusion dispatch
│   ├── llm/
│   │   ├── client.py            # Async OpenAI-compatible client
│   │   └── prompts.py           # Default prompt templates
│   ├── storage/
│   │   ├── database.py          # SQLite + aiosqlite setup
│   │   ├── job_store.py         # Job + API key CRUD
│   │   └── file_store.py        # File I/O for job artifacts
│   └── utils/
│       ├── pdf_ops.py           # PDF split, page→image, page count
│       └── image_ops.py         # Grayscale, OTSU threshold, dilate
├── tests/                       # 85 tests
├── config.yaml                  # Default config
├── pyproject.toml               # Dependencies + build config
└── documentation/               # Docs
```

## Code Conventions

- Python 3.11+ with `from __future__ import annotations`
- Pydantic v2 models for all schemas
- `async/await` throughout (aiosqlite, httpx, openai async client)
- No comments in code unless explicitly requested
- Tests use `pytest` with `pytest-asyncio` (asyncio_mode = "auto")
- Fixtures in `tests/conftest.py`

## Adding a New Extractor

1. Create `ides/extractors/your_extractor.py`
2. Inherit from `BaseExtractor` in `base.py`
3. Implement `async def extract(self, pdf_path, page_num, **kwargs)`
4. Return a Pydantic model from `models.py`
5. Add it to the orchestrator in `pipeline/orchestrator.py`
6. Add classification logic in `page_plan.py` if needed
7. Write tests in `tests/test_extractors.py`

## Adding a New API Endpoint

1. Add the route to the appropriate router in `ides/api/`
2. Add Pydantic models to `ides/models.py`
3. Use `_get_deps(request)` to access db, file_store, config
4. Write tests in `tests/test_api.py`
5. Update `documentation/api-reference.md`
