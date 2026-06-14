import json
import logging
import os
from typing import Any, AsyncIterator

import httpx
import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from contextlib import asynccontextmanager

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("glm_proxy")


def _load_config() -> dict[str, Any]:
    path = os.getenv("CONFIG_FILE", "config.yaml")
    if not os.path.isfile(path):
        path = "config.example.yaml"
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        log.info("Loaded config from %s", path)
        return cfg or {}
    log.warning("No config file found, using built-in defaults")
    return {}


CFG = _load_config()

UPSTREAM = CFG.get("upstream", "https://api.z.ai/api/anthropic")
API_KEY = os.getenv("glmapikey") or os.getenv("ZAI_API_KEY")
PROXY_TOKEN = CFG.get("proxy_token", "")
LISTEN_HOST = os.getenv("HOST", CFG.get("server", {}).get("host", "127.0.0.1"))
LISTEN_PORT = int(os.getenv("PORT", str(CFG.get("server", {}).get("port", 8082))))

MODEL_MAP: dict[str, str] = CFG.get("model_map", {
    "claude-opus-4-8": "glm-5.2",
    "claude-sonnet-4-6": "glm-4.6v",
    "claude-haiku-4-5-20251001": "glm-4.5-air",
})
DEFAULT_GLM_MODEL = CFG.get("default_model", "glm-4.6")
log.info("Model map: %s", MODEL_MAP)


class _AuthError(Exception):
    def __init__(self, response: JSONResponse):
        self.response = response


async def verify_token(authorization: str | None = Header(default=None)) -> None:
    if not PROXY_TOKEN:
        return
    if authorization != f"Bearer {PROXY_TOKEN}":
        raise _AuthError(JSONResponse(
            {"type": "error", "error": {"type": "authentication_error", "message": "invalid or missing bearer token"}},
            status_code=401,
            headers={"www-authenticate": "Bearer"},
        ))


def map_model(claude_model: str) -> str:
    if claude_model in MODEL_MAP:
        return MODEL_MAP[claude_model]
    for prefix, glm in MODEL_MAP.items():
        base = prefix.rsplit("-", 1)[0]
        if claude_model.startswith(base):
            return glm
    log.warning("Unmapped model %r -> default %r", claude_model, DEFAULT_GLM_MODEL)
    return DEFAULT_GLM_MODEL


def rev_map_model(glm_model: str, requested: str) -> str:
    for claude, glm in MODEL_MAP.items():
        if glm == glm_model:
            return requested or claude
    return requested or glm_model


_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    log.info("HTTP client pool started")
    yield
    await _http_client.aclose()
    log.info("HTTP client pool closed")


app = FastAPI(title="GLM Anthropic Proxy", lifespan=lifespan)


@app.exception_handler(_AuthError)
async def _auth_error_handler(_: Request, exc: _AuthError) -> JSONResponse:
    return exc.response


@app.get("/v1/models")
async def list_models(_=Depends(verify_token)) -> dict[str, Any]:
    data = [
        {"type": "model", "id": m, "display_name": m, "created_at": "2024-01-01T00:00:00Z"}
        for m in MODEL_MAP
    ]
    return {"data": data, "firstId": data[0]["id"] if data else None, "hasMore": False, "lastId": data[-1]["id"] if data else None}


@app.post("/v1/messages")
async def proxy_messages(request: Request, _=Depends(verify_token)) -> Any:
    body_raw = await request.body()
    try:
        payload = json.loads(body_raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    requested_model = payload.get("model", "")
    glm_model = map_model(requested_model)
    payload["model"] = glm_model

    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    log.info("%s stream=%s -> %s", requested_model, payload.get("stream", False), glm_model)

    is_stream = bool(payload.get("stream"))

    assert _http_client is not None

    if not is_stream:
        resp = await _http_client.post(f"{UPSTREAM}/v1/messages", headers=headers, json=payload)
        data = resp.json()
        if isinstance(data, dict) and "model" in data:
            data["model"] = rev_map_model(data["model"], requested_model)
        return JSONResponse(data, status_code=resp.status_code)

    client = _http_client

    async def stream_gen() -> AsyncIterator[bytes]:
        async with client.stream("POST", f"{UPSTREAM}/v1/messages", headers=headers, json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    yield b"\n"
                    continue
                out = line
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        yield (line + "\n").encode()
                        continue
                    if obj.get("type") == "message_start" and isinstance(obj.get("message"), dict):
                        m = obj["message"]
                        if "model" in m:
                            m["model"] = rev_map_model(m["model"], requested_model)
                    out = "data: " + json.dumps(obj)
                yield (out + "\n").encode()

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    log.info("Listening on http://%s:%d", LISTEN_HOST, LISTEN_PORT)
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")
