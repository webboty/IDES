# IDES — Deployment Guide

Fresh-server deployment from zero. Target: Ubuntu 22.04 / 24.04 VPS.

---

## 1. System Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 50 GB+ (PDFs + results accumulate) |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Python | 3.11 | 3.12 |

---

## 2. System Packages

```bash
apt update && apt upgrade -y

apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    poppler-utils \
    libgl1 \
    git \
    curl \
    nginx \
    ufw

# Verify Tesseract languages installed
tesseract --list-langs
# Expected output includes: deu, eng, rus
```

> **Why each package:**
> - `tesseract-ocr-*` — OCR for scanned pages
> - `poppler-utils` — required by `pdf2image` to convert PDF pages to images
> - `libgl1` — required by OpenCV headless
> - `nginx` — reverse proxy (HTTPS termination)

---

## 3. Tailscale (VPN to office LLM)

Only needed if your local LLM server is on the office network.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
# Follow the auth URL printed in the terminal
# After auth, verify connectivity:
ping 192.168.1.107   # adjust to your office LLM IP
```

If the office LLM is not reachable, IDES automatically falls back to OpenAI for all operations.

---

## 4. Application Setup

```bash
# Create app user (don't run as root)
useradd -m -s /bin/bash ides
su - ides

# Clone repository
git clone https://github.com/webboty/IDES.git /home/ides/app
cd /home/ides/app

# Create virtualenv and install
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# Verify install
ides --help
```

---

## 5. Configuration

### 5.1 Create `.env`

```bash
cat > /home/ides/app/.env << 'EOF'
IDES_ADMIN_KEY=your-very-long-random-admin-key-here
OPENAI_API_KEY=sk-...
EOF
chmod 600 /home/ides/app/.env
```

Generate a strong admin key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5.2 Create `config.yaml`

Copy the example and adjust:

```bash
cp /home/ides/app/config.yaml /home/ides/app/config.yaml.bak
```

Full working example:

```yaml
server:
  host: "127.0.0.1"     # listen on localhost only — nginx proxies externally
  port: 8000
  master_admin_key: "${IDES_ADMIN_KEY}"

storage:
  base_path: "/home/ides/data"    # absolute path recommended in production

providers:
  local:
    base_url: "http://192.168.1.107:11435/v1"   # office LLM via Tailscale
    api_key: "not-needed"
    timeout: 180
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "${OPENAI_API_KEY}"
    timeout: 60

models:
  vision:
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 4000
  merge:
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 4000
  filter:
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 200
  image_describe:
    provider: "openai"
    name: "gpt-5.4-nano"
    max_tokens: 500

extraction:
  dpi:
    vision: 200
    ocr: 300
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

### 5.3 Create data directory

```bash
mkdir -p /home/ides/data
```

---

## 6. systemd Service

The IDES worker runs **inside the uvicorn process** — no separate worker or cron is needed. One service manages everything.

```bash
cat > /etc/systemd/system/ides.service << 'EOF'
[Unit]
Description=IDES — Intelligent Document Extraction System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ides
Group=ides
WorkingDirectory=/home/ides/app
EnvironmentFile=/home/ides/app/.env
ExecStart=/home/ides/app/.venv/bin/uvicorn ides.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ides

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ides
systemctl start ides

# Check it's running
systemctl status ides
journalctl -u ides -f
```

> **Important:** `--workers 1` is required. Multiple workers would each start their own job polling loop and process the same jobs twice. The async model handles concurrency within a single worker.

---

## 7. nginx Reverse Proxy

```bash
cat > /etc/nginx/sites-available/ides << 'EOF'
server {
    listen 80;
    server_name your-domain.com;    # replace with your domain or server IP

    # Must be >= extraction.max_file_size_mb in config.yaml
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;    # long-running extraction jobs
    }
}
EOF

ln -s /etc/nginx/sites-available/ides /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

### 7.1 HTTPS with Let's Encrypt

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
# Certbot auto-configures nginx and sets up renewal
```

---

## 8. Firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'    # ports 80 + 443
ufw enable
ufw status
```

Port 8000 is **not** opened externally — nginx proxies to it on localhost.

---

## 9. CLI Management Tool

The `ides` CLI is installed with the package and lets you manage keys, jobs, and the server from the command line. Most commands connect directly to SQLite — **the server does not need to be running**.

See **[CLI.md](CLI.md)** for the full command reference.

Quick examples:

```bash
# Create your first API key before starting the server
ides --config /home/ides/app/config.yaml keys create --name n8n-prod --owner admin

# Check server and worker state
ides status

# View recent jobs
ides jobs list --limit 20

# Clean up job files older than 30 days
ides jobs cleanup --older-than 30

# Check LLM provider config and live connectivity
ides llm --test

# Restart / stop via systemd
ides restart
ides stop
```

---

## 10. First-Run Verification

```bash
# Health check
curl https://your-domain.com/health
# Expected: {"status":"ok"}

# LLM provider status
curl https://your-domain.com/health/llm
# Expected: both local and openai showing "ok" (or "timeout" if no Tailscale yet)

# Create your first API key (via CLI — no server needed)
ides --config /home/ides/app/config.yaml keys create --name n8n-production --owner n8n
# Copy the printed key — it is shown only once

# Or via the admin HTTP API if the server is already running:
curl -X POST https://your-domain.com/admin/keys \
  -H "X-Admin-Key: your-very-long-random-admin-key-here" \
  -H "Content-Type: application/json" \
  -d '{"name": "n8n-production", "owner": "n8n"}'

# Test extraction
curl -X POST https://your-domain.com/extract \
  -H "X-API-Key: ides_xxxxx..." \
  -F "file=@/path/to/test.pdf" \
  -F "pages=all"
# Expected: {"job_id":"...","status":"pending"}
```

---

## 11. n8n Integration

In n8n, use an **HTTP Request** node:

| Field | Value |
|---|---|
| Method | POST |
| URL | `https://your-domain.com/extract` |
| Authentication | Header Auth |
| Header Name | `X-API-Key` |
| Header Value | `ides_xxxxx...` |
| Body Content Type | Multipart/Form-Data |
| Body param `file` | Binary data from previous node |
| Body param `pages` | `all` |
| Body param `skip_boilerplate` | `true` |

**Polling workflow:**
1. POST `/extract` → get `job_id`
2. Wait 10s
3. GET `/jobs/{job_id}` → check `status`
4. If not `completed` → wait 5s → repeat step 3
5. GET `/jobs/{job_id}/result` → get `markdown`

---

## 12. Data Layout

Jobs are stored under `storage.base_path`:

```
/home/ides/data/
├── ides.db                          # SQLite — job metadata, API keys
└── jobs/
    └── 2026/
        └── 04/
            └── 17/
                └── {job_id}/
                    ├── original.pdf
                    ├── meta.json
                    ├── classification.json
                    ├── pages/
                    ├── layers/
                    ├── fusion/
                    └── result/
                        ├── final.md
                        └── result.json
```

**Useful SQL queries:**

```sql
-- Jobs today
SELECT id, original_filename, status, created_at
FROM jobs WHERE job_date = date('now');

-- Jobs this month
SELECT id, original_filename, status, created_at
FROM jobs WHERE job_date LIKE '2026-04-%';

-- Failed jobs
SELECT id, original_filename, last_error, created_at
FROM jobs WHERE status = 'failed' ORDER BY created_at DESC;

-- Processing stats per day
SELECT job_date, COUNT(*) as total,
       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok,
       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
FROM jobs GROUP BY job_date ORDER BY job_date DESC;
```

---

## 13. Maintenance

### Backup

```bash
# Back up DB + all job results
tar -czf ides-backup-$(date +%Y%m%d).tar.gz \
    /home/ides/data/ides.db \
    /home/ides/data/jobs/

# DB only (fast, for daily automated backup)
sqlite3 /home/ides/data/ides.db ".backup /tmp/ides-db-$(date +%Y%m%d).db"
```

### Cleanup old job files

```bash
# Delete job folders older than 90 days (keeps DB records intact)
find /home/ides/data/jobs -mindepth 3 -maxdepth 3 -type d \
    -name "20*" -mtime +90 -exec rm -rf {} +
```

Add to crontab for automation:
```bash
crontab -e
# Add:
0 3 * * * find /home/ides/data/jobs -mindepth 3 -maxdepth 3 -type d -name "20*" -mtime +90 -exec rm -rf {} +
```

### Logs

```bash
journalctl -u ides -f                    # live logs
journalctl -u ides --since "1 hour ago"  # last hour
journalctl -u ides --since "2026-04-17"  # specific date
```

### Update application

```bash
su - ides
cd /home/ides/app
git pull
source .venv/bin/activate
pip install -e .
exit

systemctl restart ides
systemctl status ides
```

---

## 14. Troubleshooting

| Symptom | Check |
|---|---|
| `502 Bad Gateway` | `systemctl status ides` — service crashed |
| Jobs stuck in `pending` | Worker loop running? Check logs. Only 1 uvicorn worker allowed. |
| `LLM provider 'local': timeout` | Tailscale connected? `ping 192.168.1.107` |
| `LLM provider 'openai': error` | `OPENAI_API_KEY` set in `.env`? |
| PDF upload fails with 413 | Increase `client_max_body_size` in nginx config |
| Tesseract language missing | `apt install tesseract-ocr-deu` etc., then `systemctl restart ides` |
| `401 Invalid admin key` | `IDES_ADMIN_KEY` in `.env` matches `master_admin_key` in `config.yaml`? |
