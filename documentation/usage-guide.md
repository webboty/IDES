# Usage Guide

## Authentication

IDES uses two types of authentication:

### Admin Key
Used for managing API keys. Set via `IDES_ADMIN_KEY` env var or `config.yaml`.

```bash
# All admin endpoints require this header
X-Admin-Key: your-admin-key
```

### API Keys
Per-user keys for submitting and querying jobs. Created via admin endpoint.

```bash
# All job endpoints require this header
X-API-Key: ides_a3f2b8c1d4e5f6g7h8i9j0k1l2m3n4o5
```

---

## Managing API Keys

### Create a Key

```bash
curl -X POST http://localhost:8000/admin/keys \
  -H "X-Admin-Key: your-admin-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "n8n-production",
    "owner": "automation team",
    "allowed_ips": ["203.0.113.50"]
  }'
```

Response:
```json
{
  "id": "a1b2c3d4e5f6",
  "key": "ides_a3f2b8c1d4e5f6g7h8i9j0k1l2m3n4o5",
  "key_prefix": "ides_a3f2",
  "name": "n8n-production",
  "owner": "automation team"
}
```

**Save the `key` value immediately.** It is shown only once. The stored hash cannot be reversed.

### List Keys

```bash
curl http://localhost:8000/admin/keys \
  -H "X-Admin-Key: your-admin-key"
```

### Deactivate a Key

```bash
curl -X DELETE http://localhost:8000/admin/keys/{key_id} \
  -H "X-Admin-Key: your-admin-key"
```

This is a soft delete. The key immediately stops working.

---

## Submitting PDFs for Extraction

### Option 1: File Upload (Multipart)

```bash
curl -X POST http://localhost:8000/extract \
  -H "X-API-Key: ides_your-key" \
  -F "file=@invoice.pdf" \
  -F "pages=all" \
  -F "skip_boilerplate=true" \
  -F "lang=deu+eng"
```

**Form fields:**

| Field | Required | Default | Description |
|---|---|---|---|
| `file` | Yes | — | PDF file binary |
| `pages` | No | `"all"` | Page range: `"1-5"`, `"1,3,7"`, `"all"` |
| `prompt` | No | Built-in | Override vision extraction prompt |
| `merge_prompt` | No | Built-in | Override fusion/merge prompt |
| `lang` | No | From config | OCR language e.g. `"deu+eng+rus"` |
| `skip_boilerplate` | No | `"true"` | `"true"` or `"false"` |
| `agent_model` | No | From config | Override fusion model name |
| `agent_provider` | No | From config | `"local"` or `"openai"` |
| `opencode_skills` | No | `[]` | JSON array: `'["invoice_extraction"]'` |

### Option 2: JSON with Base64

```bash
curl -X POST http://localhost:8000/extract \
  -H "X-API-Key: ides_your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "file_base64": "JVBERi0xLjQg...",
    "filename": "invoice.pdf",
    "pages": "1-3",
    "skip_boilerplate": true
  }'
```

### Response

```json
{
  "job_id": "abc123def456",
  "status": "pending"
}
```

---

## Checking Job Status

```bash
curl http://localhost:8000/jobs/{job_id} \
  -H "X-API-Key: ides_your-key"
```

Response:
```json
{
  "job_id": "abc123def456",
  "status": "processing",
  "attempt": 1,
  "max_attempts": 3,
  "progress": {
    "current_page": 3,
    "total_pages": 10,
    "pages_skipped": 2,
    "layers_stats": {
      "text_layer": 1,
      "ocr": 1,
      "vision": 1
    }
  },
  "retry_history": [],
  "created_at": "2024-01-15T10:30:00",
  "updated_at": "2024-01-15T10:30:15"
}
```

### Job Status Values

| Status | Meaning |
|---|---|
| `pending` | Queued, waiting for worker |
| `processing` | Active extraction in progress |
| `retrying` | Failed once, retrying |
| `recovering` | Agent analyzing failure (attempt 3) |
| `completed` | Done — result available |
| `failed` | All attempts exhausted |

---

## Getting Results

### Lightweight Result (markdown only)

```bash
curl http://localhost:8000/jobs/{job_id}/result \
  -H "X-API-Key: ides_your-key"
```

Response:
```json
{
  "job_id": "abc123def456",
  "status": "completed",
  "markdown": "# Invoice\n\n...",
  "metadata": {
    "pages_processed": 8,
    "pages_skipped": 2,
    "total_time_seconds": 45.2,
    "opencode_session_id": null
  }
}
```

### Full Detail (per-page breakdown)

```bash
curl http://localhost:8000/jobs/{job_id}/detail \
  -H "X-API-Key: ides_your-key"
```

This returns page-by-page classification, which layers were used, per-page markdown, and extracted image descriptions.

---

## Polling Pattern

IDES is asynchronous. Use this pattern to wait for results:

```python
import time
import httpx

API_URL = "http://localhost:8000"
API_KEY = "ides_your-key"

def extract_pdf(pdf_path: str) -> str:
    # 1. Submit
    with open(pdf_path, "rb") as f:
        resp = httpx.post(
            f"{API_URL}/extract",
            headers={"X-API-Key": API_KEY},
            files={"file": f},
            data={"pages": "all", "skip_boilerplate": "true"},
        )
    job_id = resp.json()["job_id"]

    # 2. Poll
    while True:
        resp = httpx.get(
            f"{API_URL}/jobs/{job_id}",
            headers={"X-API-Key": API_KEY},
        )
        status = resp.json()["status"]
        if status == "completed":
            break
        if status == "failed":
            raise Exception(f"Job failed: {resp.json()}")
        time.sleep(3)

    # 3. Fetch result
    resp = httpx.get(
        f"{API_URL}/jobs/{job_id}/result",
        headers={"X-API-Key": API_KEY},
    )
    return resp.json()["markdown"]
```

---

## n8n Workflow

### Step 1: Submit PDF

**HTTP Request node:**
```
Method: POST
URL: https://your-vps:8000/extract
Authentication: Header Auth
  Header Name: X-API-Key
  Header Value: ides_your-key
Body Content Type: Multipart-Form Data
Body Parameters:
  - Name: file, Type: n8n Binary Data
  - Name: pages, Type: Text, Value: "all"
  - Name: skip_boilerplate, Type: Text, Value: "true"
```

### Step 2: Wait + Poll

Add a **Wait** node (10 seconds), then a **Loop**:

```
HTTP Request → GET https://your-vps:8000/jobs/{{$json.job_id}}
  Header: X-API-Key = ides_your-key

IF node → {{$json.status}} == "completed"
  TRUE → continue
  FALSE → Wait 5s → loop back to HTTP Request
```

### Step 3: Get Result

```
HTTP Request → GET https://your-vps:8000/jobs/{{$json.job_id}}/result
  Header: X-API-Key = ides_your-key
```

The `markdown` field in the response contains the extracted document.

---

## Understanding the Pipeline

When you submit a PDF, IDES:

1. **Splits** the PDF into individual pages
2. **Classifies** each page using pdfplumber (cheap):
   - `structured_text` (>500 chars + tables) → text layer only
   - `text_only` (>200 chars) → text layer + OCR verify
   - `mixed` (50-200 chars) → all layers
   - `scanned` (~0 chars, OCR has text) → OCR + vision
   - `image_only` (~0 chars, no OCR text) → vision only
   - `boilerplate` (pattern match) → **skipped**
3. **Extracts** using only the layers needed per page
4. **Fuses** all layer outputs into clean Markdown with number validation
5. **Assembles** final document with page separators (`---`)

---

## Tips

- **Faster extraction**: Set `skip_boilerplate=true` (default) to skip legal pages
- **Custom prompts**: Use `prompt` parameter to customize vision extraction behavior
- **Page ranges**: Use `pages="1-3,7"` to extract specific pages only
- **Large PDFs**: Default max is 50 pages (configurable in `config.yaml`)
- **Number accuracy**: The fusion agent cross-validates every number across all sources
