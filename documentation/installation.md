# Installation Guide

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.12 |
| RAM | 512 MB | 2 GB |
| Disk | 100 MB | 1 GB (depends on PDF volume) |
| CPU | 1 core | 2+ cores |

## System Dependencies

### macOS

```bash
brew install tesseract tesseract-lang poppler
```

### Ubuntu / Debian

```bash
apt update && apt install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    poppler-utils \
    python3.12 \
    python3.12-venv
```

### Verifying Install

```bash
tesseract --version          # Should show 5.x+
pdftoppm -h                  # Should show poppler help
python3 --version            # Should show 3.11+
```

## Application Install

### From Source

```bash
git clone https://github.com/your-org/ides.git
cd ides

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Dev Install (with test tools)

```bash
pip install -e ".[dev]"
```

### Verify Install

```bash
python -c "import ides; print('OK')"
pytest tests/ -q
```

## Configuration

Copy and edit the config file:

```bash
cp config.yaml config.yaml
```

Set required environment variables:

```bash
export IDES_ADMIN_KEY="a-strong-random-secret"
export OPENAI_API_KEY="sk-..."       # Only if using OpenAI provider
```

See [configuration.md](configuration.md) for all config options.

## Running

### Development

```bash
source .venv/bin/activate
uvicorn ides.main:app --reload --host 0.0.0.0 --port 8000
```

### Production (systemd)

Create `/etc/systemd/system/ides.service`:

```ini
[Unit]
Description=IDES API
After=network.target

[Service]
Type=simple
User=ides
WorkingDirectory=/opt/ides
Environment=IDES_ADMIN_KEY=your-admin-key
Environment=OPENAI_API_KEY=sk-your-key
ExecStart=/opt/ides/.venv/bin/uvicorn ides.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable ides
systemctl start ides
```

### Production (Docker)

```dockerfile
FROM python:3.12-slim

RUN apt update && apt install -y \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-rus \
    poppler-utils && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "ides.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t ides .
docker run -d -p 8000:8000 \
  -e IDES_ADMIN_KEY=your-admin-key \
  -e OPENAI_API_KEY=sk-your-key \
  -v ides-data:/app/data \
  ides
```

## First Steps After Install

1. Start the server
2. Create your first API key via admin endpoint
3. Submit a test PDF via `/extract`
4. Poll `/jobs/{id}` for completion
5. Fetch result from `/jobs/{id}/result`

See [usage-guide.md](usage-guide.md) for detailed examples.
