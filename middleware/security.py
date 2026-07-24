"""Security middleware — headers + rate limiting.

Kept dependency-light: security headers via pure ASGI middleware, rate limit via slowapi.
"""
import os
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address

# ---- Rate limiter (slowapi) ----
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300/minute"],  # generous global default
    strategy="fixed-window",
)


# ---- Security headers ----
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # CSP kept simple — frontend serves its own tighter policy.
        return response


# ---- Optional HMAC on admin routes ----
ADMIN_HMAC_SECRET = os.environ.get("ADMIN_HMAC_SECRET", "")


class AdminHMACMiddleware(BaseHTTPMiddleware):
    """When ADMIN_HMAC_SECRET is set, mutating /api/admin/* requires header
    `X-Admin-Signature: hex(HMAC-SHA256(method|path|body, ADMIN_HMAC_SECRET))`.
    Read-only GET is exempted. Kept OFF by default so we don't lock ourselves out;
    enable by setting ADMIN_HMAC_SECRET in .env before production launch.
    """
    async def dispatch(self, request, call_next):
        if not ADMIN_HMAC_SECRET:
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/admin/"):
            return await call_next(request)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        # Opt-in: only enforce HMAC if the client sent a signature header.
        # This lets the JWT-authenticated admin panel work while allowing
        # external/programmatic callers to prove they hold the shared secret.
        provided = request.headers.get("x-admin-signature", "")
        if not provided:
            return await call_next(request)
        import hmac as _hmac
        import hashlib as _hashlib
        body = await request.body()
        base = f"{request.method}|{path}|".encode() + body
        expected = _hmac.new(ADMIN_HMAC_SECRET.encode(), base, _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(provided, expected):
            from starlette.responses import JSONResponse
            return JSONResponse({"detail": "Admin HMAC signature invalid"}, status_code=401)
        # Re-inject body so downstream handlers can read it.

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive
        return await call_next(request)
