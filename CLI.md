# IDES CLI Reference

The `ides` command-line tool lets you manage the server, API keys, and jobs directly from the terminal — without needing a running server for most operations (keys and job management talk to SQLite directly).

## Global option

```
ides [--config PATH] <command> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config PATH` | `config.yaml` | Path to the YAML configuration file |

---

## serve

Start the API server (foreground process).

```
ides serve [--host HOST] [--port PORT]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | from config | Bind address |
| `--port` | from config | Listen port |

**Example**
```bash
ides serve
ides serve --port 9000
ides --config /etc/ides/config.yaml serve
```

> In production, run via systemd (see DEPLOY.md). Use `ides restart` / `ides stop` to manage it.

---

## keys

API key management. All subcommands connect directly to SQLite — the server does not need to be running.

### keys create

```
ides keys create --name NAME --owner OWNER [--ips IP,IP,...]
```

| Flag | Required | Description |
|------|----------|-------------|
| `--name NAME` | yes | Human-readable label, e.g. `n8n-prod` |
| `--owner OWNER` | yes | Owner name or team |
| `--ips IP,IP,...` | no | Comma-separated list of allowed client IPs (unrestricted if omitted) |

The full API key is printed **once** — save it immediately.

```
$ ides keys create --name n8n-prod --owner "ops team"
API key created
  ID     : a3f1b2c4d5e6f708
  Name   : n8n-prod
  Owner  : ops team
  Prefix : ides_a3f1b

  Key : ides_a3f1b2c4d5e6f7089a0b1c2d

  Save this key — it will not be shown again.
```

**With IP restriction:**
```bash
ides keys create --name monitoring --owner devops --ips "10.0.0.5,10.0.0.6"
```

### keys list

```
ides keys list
```

Lists all active (non-revoked) keys — never shows the full key, only the prefix and metadata.

```
ID                 PREFIX       NAME                   OWNER                  LAST USED
───────────────────────────────────────────────────────────────────────────────────────────────
a3f1b2c4d5e6f708   ides_a3f1b   n8n-prod               ops team               2026-04-17 09:12:33
```

### keys revoke

```
ides keys revoke <id>
```

Immediately deactivates the key. The ID comes from `keys list`.

```bash
ides keys revoke a3f1b2c4d5e6f708
```

---

## jobs

Job management. All subcommands work without a running server.

### jobs list

```
ides jobs list [--date YYYY-MM-DD] [--status STATUS] [--limit N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--date YYYY-MM-DD` | (all) | Filter by submission date |
| `--status STATUS` | (all) | Filter by status (`pending`, `processing`, `completed`, `failed`, `cancelled`, `retrying`, `recovering`) |
| `--limit N` | 50 | Max rows returned |

```bash
ides jobs list
ides jobs list --date 2026-04-17
ides jobs list --status failed --limit 20
```

### jobs stats

```
ides jobs stats [--days N]
```

Daily summary table (completed / failed / cancelled / active) for the last N days.

| Flag | Default | Description |
|------|---------|-------------|
| `--days N` | 30 | Number of past days to include |

```bash
ides jobs stats
ides jobs stats --days 7
```

```
DATE           TOTAL      OK   FAILED  CANCELLED   ACTIVE
────────────────────────────────────────────────────────
2026-04-17         8       7        1          0        0
2026-04-16        12      12        0          0        0
```

### jobs cancel

```
ides jobs cancel <job_id>
```

Cancels a job that is in `pending` or `retrying` state. The DB record is kept; only the status changes. Has no effect on jobs that are already processing, completed, or failed.

```bash
ides jobs cancel abc123def456789012345678
```

### jobs purge

```
ides jobs purge <job_id> [--force]
```

Permanently deletes a job: removes all files on disk **and** the DB row. Without `--force`, asks for confirmation.

| Flag | Description |
|------|-------------|
| `--force` | Skip the confirmation prompt (useful in scripts) |

```bash
ides jobs purge abc123def456789012345678
ides jobs purge abc123def456789012345678 --force
```

### jobs cleanup

```
ides jobs cleanup [--older-than DAYS]
```

Bulk-delete files for all completed/failed/cancelled jobs older than N days. DB records are kept for audit purposes.

| Flag | Default | Description |
|------|---------|-------------|
| `--older-than DAYS` | 90 | Age threshold in days |

```bash
ides jobs cleanup
ides jobs cleanup --older-than 30
```

---

## status

```
ides status
```

Snapshot of the whole system: server reachability, worker activity, queue counts per status, and disk usage.

```
Server
  Status  : running
  Address : http://127.0.0.1:8000

Worker
  Status  : processing (1 active job)
  ↳ abc123...  invoice_april.pdf  page 3/12

Queue
  pending             0
  processing          1
  completed         423
  failed              2

Storage
  Path    : /var/lib/ides
  Disk    : [████████░░░░░░░░░░░░] 41%  (82.1 GB used, 117.9 GB free of 200.0 GB)
```

---

## llm

```
ides llm [--test]
```

Shows the configured LLM providers and model assignments. With `--test`, performs a live connectivity check via the running server.

| Flag | Description |
|------|-------------|
| `--test` | Check live provider health (server must be running) |

```bash
ides llm
ides llm --test
```

---

## restart / stop

Manage the IDES systemd service. Requires systemd (Linux production servers).

```bash
ides restart   # systemctl restart ides
ides stop      # systemctl stop ides
```

If systemd is not available (e.g. macOS dev machine), a hint to kill the process manually is printed instead.

> See DEPLOY.md §6 for systemd service setup.

---

## Common workflows

### First deployment — create the initial API key

```bash
# Server does not need to be running yet
ides --config /etc/ides/config.yaml keys create --name first-key --owner admin
# Copy the printed key, then start the server
ides --config /etc/ides/config.yaml serve
```

### Investigate failures

```bash
ides jobs list --status failed --limit 10
# pick a job_id from the output, then check the server logs or purge:
ides jobs purge <job_id>
```

### Weekly disk cleanup

```bash
ides jobs cleanup --older-than 7
```

### Rotate a compromised key

```bash
ides keys list          # find the ID
ides keys revoke <id>   # revoke immediately
ides keys create --name replacement --owner ops
```
