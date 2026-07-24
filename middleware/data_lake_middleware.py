"""FastAPI middleware that logs every API request/response to the Data Lake."""
import time
import logging
import json
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from auth import decode_token
from services.data_lake import log_event

logger = logging.getLogger(__name__)

# Skip paths that add noise / SSE / uploads
SKIP_PATHS = {"/api/", "/api/health", "/api/webhook/stripe"}
SKIP_PREFIXES = ("/api/uploads",)

# We never persist full response bodies for streaming or large payloads.
MAX_BODY_CAPTURE = 2000  # bytes


def _extract_user_id(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return ""
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        return payload.get("sub", "") or ""
    except Exception:
        return ""


class DataLakeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        path = request.url.path
        method = request.method

        # Only log API calls
        should_log = path.startswith("/api")
        for pfx in SKIP_PREFIXES:
            if path.startswith(pfx):
                should_log = False
        if path in SKIP_PATHS:
            should_log = False

        response: Response
        try:
            response = await call_next(request)
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if should_log:
                await log_event(
                    "api_error",
                    user_id=_extract_user_id(request),
                    payload={"path": path, "method": method, "error": str(e)[:500]},
                    meta={"latency_ms": elapsed_ms, "status": 500},
                )
            raise

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if should_log:
            await log_event(
                "api_call",
                user_id=_extract_user_id(request),
                payload={
                    "path": path,
                    "method": method,
                    "query": str(request.url.query)[:MAX_BODY_CAPTURE],
                },
                meta={
                    "latency_ms": elapsed_ms,
                    "status": response.status_code,
                    "user_agent": request.headers.get("user-agent", "")[:200],
                    "ip": request.client.host if request.client else "",
                },
            )
        return response
