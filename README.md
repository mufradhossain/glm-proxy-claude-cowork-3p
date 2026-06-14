# GLM Proxy for Claude Cowork 3P

Use your **GLM coding plan** with [Claude Cowork 3P](https://docs.anthropic.com) by proxying requests through z.ai's Anthropic-compatible API. The proxy translates Claude model names to GLM models transparently, so Claude Cowork works out of the box.

```
Claude Cowork 3P  ──HTTPS──▶  Your Proxy  ──▶  api.z.ai/api/anthropic
                               (model name          (GLM models)
                                translation)
```

## How It Works

Claude Cowork 3P sends requests using Claude model names (e.g. `claude-sonnet-4-6`). The z.ai API doesn't recognize those names — it expects GLM model names (e.g. `glm-4.6v`). This proxy sits in between and:

1. Receives the request with a Claude model name
2. Maps it to the corresponding GLM model
3. Forwards it to z.ai's Anthropic-compatible endpoint
4. Rewrites the model name back to the Claude name in the response
5. Returns it to Claude Cowork — which thinks it's talking to Anthropic

Both **streaming** and **non-streaming** requests are fully supported.

## Model Mapping

| Claude Model | GLM Model |
|---|---|
| `claude-opus-4-8` | `glm-5.2` |
| `claude-sonnet-4-6` | `glm-4.6v` |
| `claude-haiku-4-5-20251001` | `glm-4.5-air` |

Unmapped model names fall back to the `default_model` setting. Prefix matching is used, so date-stamped variants (e.g. `claude-opus-4-8-20251120`) map automatically.

To customize mappings, edit `model_map` in `config.yaml`.

## Prerequisites

- A **GLM API key** from [z.ai](https://z.ai) (included with GLM coding plans)
- Python 3.11+ **or** Docker
- A way to expose the proxy over **HTTPS** (Claude Cowork requires HTTPS endpoints)

## Quick Start

### Option 1: Conda / pip

```bash
# Clone the repo
git clone <your-repo-url>
cd glm-proxy-claude-cowork-3p

# Create environment
conda create -y -n glm_proxy python=3.11
conda activate glm_proxy
pip install -r requirements.txt

# Set up secrets
cp .env.example .env
# Edit .env and add your GLM API key

# Set up config
cp config.example.yaml config.yaml
# Edit config.yaml — set your proxy_token and adjust model mappings

# Run
python proxy.py
```

### Option 2: Docker

```bash
# Set up secrets and config
cp .env.example .env
cp config.example.yaml config.yaml
# Edit both files with your key and token

# Build and run
docker compose up -d
```

The proxy listens on `127.0.0.1:8082` by default (configurable in `config.yaml`).

## HTTPS Requirement

> **Claude Cowork 3P requires an HTTPS endpoint.** The proxy itself runs plain HTTP. You need to tunnel it through something that provides TLS.

### Cloudflare Tunnel (recommended — free, stable URL)

```bash
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
cloudflared tunnel --url http://127.0.0.1:8082
```

This gives you a stable `https://<random>.trycloudflare.com` URL. Point Claude Cowork at this URL.

### Other options

- **ngrok**: `ngrok http 8082`
- **Caddy**: reverse proxy with automatic HTTPS
- **Nginx + Let's Encrypt**: for self-hosted setups

Use whatever you prefer — the proxy doesn't care as long as traffic reaches it over HTTP on the configured port.

## Configuring Claude Cowork 3P

1. Start your proxy and HTTPS tunnel
2. In Claude Cowork 3P settings:
   - **Base URL**: your tunnel URL (e.g. `https://abc123.trycloudflare.com`)
   - **API Key**: the `proxy_token` from your `config.yaml`
3. Select a Claude model as usual — the proxy handles the rest

## Configuration

All settings live in `config.yaml`. Copy `config.example.yaml` to start:

```yaml
server:
  host: 127.0.0.1
  port: 8082

upstream: https://api.z.ai/api/anthropic

proxy_token: ""           # Bearer token clients must send

model_map:
  claude-opus-4-8: glm-5.2
  claude-sonnet-4-6: glm-4.6v
  claude-haiku-4-5-20251001: glm-4.5-air

default_model: glm-5.2    # Fallback for unmapped model names
```

Your GLM API key goes in `.env`:

```
glmapikey=your-zai-api-key-here
```

| Setting | File | Description |
|---|---|---|
| `glmapikey` | `.env` | Your z.ai API key (secret) |
| `server.host` / `server.port` | `config.yaml` | Listen address |
| `proxy_token` | `config.yaml` | Bearer token for client auth |
| `model_map` | `config.yaml` | Claude → GLM name mapping |
| `default_model` | `config.yaml` | Fallback for unmapped names |
| `upstream` | `config.yaml` | Upstream API base URL |

## Features

- Transparent model name translation (Claude → GLM → Claude)
- Full streaming support (SSE pass-through with model rewriting)
- Bearer token authentication
- Connection pooling for concurrent requests
- Configurable via `config.yaml` — no code changes needed
- Works with any HTTPS tunnel (Cloudflare, ngrok, Caddy, etc.)

## License

MIT — see [LICENSE](LICENSE).
