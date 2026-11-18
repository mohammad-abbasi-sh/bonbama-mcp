# DEPLOY.md — hosting bonbama-mcp (for Bonbama's dev team / Bazaar MCP Hub)

Bazaar's MCP Hub connects to a **hosted** MCP URL. This server speaks MCP
streamable HTTP at `/mcp`, so it can be deployed at e.g.
`https://api.bonbama.ir/mcp` and submitted to Bazaar with that URL.

- **MCP endpoint:** `POST /mcp` (MCP streamable HTTP, JSON-RPC over SSE)
- **Liveness probe:** `GET /health` → `{"status": "ok", "server": "bonbama-mcp", ...}`
  (plain liveness — it does NOT call bonbama.ir; use it for load-balancer /
  Docker health checks. The live bonbama.ir probe is the `bb_health` tool.)
- **State:** none. Stateless HTTP (`stateless_http=True`) — no sessions, no
  database, no disk writes. Any number of replicas behind any reverse proxy.
- **Auth:** none on the endpoint itself for v1 — the data is public,
  read-only bonbama.ir content. Bazaar connects with its own token on
  Bazaar's side; if Bonbama later wants an API key on this endpoint, add it
  in the reverse proxy (see below), not in this code.
- **Resources:** tiny — one uvicorn worker, ~100MB RAM. It only fetches
  bonbama.ir pages on demand (a few hundred KB per tool call, 30s timeout).

## Option A — Docker (recommended)

```bash
docker build -t bonbama-mcp .
docker run -d --name bonbama-mcp -p 8000:8000 --restart unless-stopped bonbama-mcp
curl http://localhost:8000/health   # {"status": "ok", ...}
```

The image runs `uvicorn bonbama_mcp.server:app --host 0.0.0.0 --port 8000`
as a non-root user, with a Docker `HEALTHCHECK` on `/health`.

## Option B — bare metal / systemd

```bash
python3.12 -m venv /opt/bonbama-mcp/.venv
/opt/bonbama-mcp/.venv/bin/pip install bonbama-mcp   # from PyPI, or pip install .
```

`/etc/systemd/system/bonbama-mcp.service`:

```ini
[Unit]
Description=bonbama-mcp (MCP streamable HTTP for bonbama.ir)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/bonbama-mcp
Environment=BONBAMA_MCP_HOST=127.0.0.1
Environment=BONBAMA_MCP_PORT=8000
ExecStart=/opt/bonbama-mcp/.venv/bin/bonbama-mcp --transport streamable-http
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now bonbama-mcp
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `BONBAMA_MCP_HOST` | `127.0.0.1` | Bind host for streamable HTTP |
| `BONBAMA_MCP_PORT` | `8000` | Bind port for streamable HTTP |

CLI flags override env vars: `bonbama-mcp --transport streamable-http --host 0.0.0.0 --port 8000`.
Plain `bonbama-mcp` with no flags runs stdio (local uvx use) — same tools.

## Reverse proxy (nginx + TLS)

```nginx
server {
    listen 443 ssl;
    server_name api.bonbama.ir;
    # ssl_certificate / ssl_certificate_key here

    location /mcp {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;   # MCP uses long-lived SSE responses
        proxy_buffering off;       # do not buffer the event stream
    }
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

Notes:
- **Do not buffer SSE** (`proxy_buffering off`) and allow long reads — MCP
  streamable HTTP holds the response open while the tool runs.
- Optional API key (if Bonbama wants one later): enforce it in nginx
  (`auth_request` or a simple `if ($http_authorization != "Bearer …")`),
  not in this server.
- Optional rate limiting: a few requests/second per IP is plenty — each
  tool call is 1–5 fetches of bonbama.ir pages.

## Verify after deploy

```bash
curl https://api.bonbama.ir/health
# {"status":"ok","server":"bonbama-mcp","transport":"streamable-http","mcp_path":"/mcp"}

curl -X POST https://api.bonbama.ir/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0.1"}}}'
# 200 + SSE "event: message" with serverInfo.name = "bonbama-mcp"
```

Then submit `https://api.bonbama.ir/mcp` in Bazaar's form
("آدرس سرور MCP").

## Updating

New version = rebuild the image (or `pip install --upgrade bonbama-mcp`)
and restart. No migrations, no state to preserve.
