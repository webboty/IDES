# API Reference

## Authentication

### Admin Endpoints
All `/admin/*` endpoints require the `X-Admin-Key` header.

```
X-Admin-Key: <master-admin-key>
```

### Job Endpoints
All `/extract` and `/jobs/*` endpoints require the `X-API-Key` header.

```
X-API-Key: ides_<your-api-key>
```

---

## Endpoints

### `GET /health`

Health check. No authentication required.

**Response:** `200`
```json
{ "status": "ok" }
```

---

### `POST /extract`

Submit a PDF for extraction. Supports two content types.

#### Multipart Form Data

```
POST /extract
Content-Type: multipart/form-data
X-API-Key: ides_...
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | binary | Yes | — | PDF file |
| `pages` | text | No | `"all"` | Page range: `"1-5"`, `"1,3,7"`, `"all"` |
| `prompt` | text | No | built-in | Override vision extraction prompt |
| `merge_prompt` | text | No | built-in | Override fusion prompt |
| `lang` | text | No | config | OCR languages e.g. `"deu+eng"` |
| `skip_boilerplate` | text | No | `"true"` | `"true"` or `"false"` |
| `agent_model` | text | No | config | Override merge model name |
| `agent_provider` | text | No | config | `"local"` or `"openai"` |
| `opencode_skills` | text | No | `[]` | JSON array string `'["invoice_extraction"]'` |

#### JSON (base64)

```
POST /extract
Content-Type: application/json
X-API-Key: ides_...
```

```json
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

#### Response: `200`
```json
{ "job_id": "abc123def456", "status": "pending" }
```

#### Errors

| Code | Meaning |
|---|---|
| `400` | Invalid/empty PDF, too many pages |
| `401` | Missing or invalid API key |

---

### `GET /jobs/{job_id}`

Get job status and progress.

**Response: `200`**
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
    "layers_stats": { "text_layer": 1, "ocr": 1, "vision": 1 }
  },
  "retry_history": [],
  "opencode_session_id": null,
  "created_at": "2024-01-15T10:30:00",
  "updated_at": "2024-01-15T10:30:15"
}
```

#### Errors

| Code | Meaning |
|---|---|
| `401` | Invalid API key |
| `404` | Job not found |

---

### `GET /jobs/{job_id}/result`

Get the final markdown output. Only meaningful when `status == "completed"`.

**Response: `200`**
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

When status is not `completed`, returns empty markdown:
```json
{
  "job_id": "abc123def456",
  "status": "processing",
  "markdown": "",
  "metadata": { "pages_processed": 0, "pages_skipped": 0, "total_time_seconds": 0 }
}
```

---

### `GET /jobs/{job_id}/detail`

Get full per-page breakdown including layer results and classifications.

**Response: `200`**
```json
{
  "job_id": "abc123def456",
  "status": "completed",
  "markdown": "full document...",
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
      "markdown": "page 1 markdown..."
    }
  ],
  "images": [
    { "page": 1, "index": 0, "description": "Company logo" }
  ],
  "opencode_session_id": null,
  "metadata": {
    "pages_processed": 8,
    "pages_skipped": 2,
    "layers_stats": { "text_layer": 6, "ocr": 3, "vision": 2 },
    "total_time_seconds": 45.2,
    "storage_path": "jobs/abc123def456/"
  }
}
```

---

### `POST /admin/keys`

Create a new API key.

**Request:**
```json
{
  "name": "n8n-production",
  "owner": "automation team",
  "allowed_ips": ["203.0.113.50"]
}
```

`allowed_ips` is optional. When set, only requests from those IPs are accepted.

**Response: `200`**
```json
{
  "id": "a1b2c3d4e5f6",
  "key": "ides_a3f2b8c1d4e5f6g7h8i9j0k1l2m3n4o5",
  "key_prefix": "ides_a3f2",
  "name": "n8n-production",
  "owner": "automation team"
}
```

**The full key is shown only once.** It is stored as a SHA-256 hash and cannot be recovered.

---

### `GET /admin/keys`

List all active API keys.

**Response: `200`**
```json
[
  {
    "id": "a1b2c3d4e5f6",
    "key_prefix": "ides_a3f2",
    "name": "n8n-production",
    "owner": "automation team",
    "is_active": true,
    "allowed_ips": ["203.0.113.50"],
    "last_used_at": "2024-01-15T10:30:15",
    "expires_at": null
  }
]
```

---

### `DELETE /admin/keys/{key_id}`

Deactivate an API key (soft delete).

**Response: `200`**
```json
{ "deleted": true }
```

**Errors:**

| Code | Meaning |
|---|---|
| `404` | Key not found or already deactivated |

---

## Status Codes

| Code | Meaning |
|---|---|
| `200` | Success |
| `400` | Bad request (invalid PDF, missing file) |
| `401` | Unauthorized (invalid/missing API key or admin key) |
| `404` | Not found (job or key) |
| `503` | Service unavailable (database not connected) |
