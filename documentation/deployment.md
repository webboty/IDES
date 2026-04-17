# VPS Deployment Guide

## Target: Ubuntu 22.04 / 24.04 VPS

---

## 1. System Setup

```bash
apt update && apt upgrade -y
apt install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    poppler-utils \
    python3.12 \
    python3.12-venv \
    git \
    curl
```

## 2. Tailscale (for office LLM access)

If connecting to an office LLM over Tailscale:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
# Authenticate via the URL shown
```

Verify connectivity:
```bash
curl http://192.168.1.141:11435/v1/models
```

## 3. Application Setup

```bash
# Create user
useradd -r -s /bin/bash -m -d /opt/ides ides

# Clone
git clone https://github.com/your-org/ides.git /opt/ides
chown -R ides:ides /opt/ides

# Install
su - ides
python3.12 -m venv /opt/ides/.venv
source /opt/ides/.venv/bin/activate
cd /opt/ides && pip install -e .
```

## 4. Configure

```bash
# Set environment variables
cat > /opt/ides/.env <<'EOF'
IDES_ADMIN_KEY=generate-a-strong-random-key-here
OPENAI_API_KEY=sk-your-openai-key-here
EOF
chmod 600 /opt/ides/.env

# Edit config.yaml for your setup
nano /opt/ides/config.yaml
```

## 5. Systemd Service

```bash
cat > /etc/systemd/system/ides.service <<'EOF'
[Unit]
Description=IDES - Intelligent Document Extraction System
After=network.target

[Service]
Type=simple
User=ides
Group=ides
WorkingDirectory=/opt/ides
EnvironmentFile=/opt/ides/.env
ExecStart=/opt/ides/.venv/bin/uvicorn ides.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

```bash
systemctl daemon-reload
systemctl enable ides
systemctl start ides
```

## 6. Verify

```bash
# Check service
systemctl status ides

# Check logs
journalctl -u ides -f

# Test health
curl http://localhost:8000/health

# Create first API key
curl -X POST http://localhost:8000/admin/keys \
  -H "X-Admin-Key: $(grep IDES_ADMIN_KEY /opt/ides/.env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "owner": "admin"}'
```

## 7. Reverse Proxy (optional)

### Nginx with HTTPS

```nginx
server {
    listen 443 ssl;
    server_name ides.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/ides.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ides.yourdomain.com/privkey.pem;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }
}
```

## 8. Firewall

```bash
ufw allow 22/tcp
ufw allow 443/tcp
ufw allow 8000/tcp    # Only if not using nginx
ufw enable
```

## 9. Monitoring

```bash
# Watch logs
journalctl -u ides -f

# Check disk usage
du -sh /opt/ides/data/

# Check DB size
ls -lh /opt/ides/data/ides.db
```

## 10. Updates

```bash
su - ides
cd /opt/ides
git pull
source .venv/bin/activate
pip install -e .
exit
systemctl restart ides
```
