"""Shared pytest infrastructure for the FastAPI backend's REAL unit/integration
tests (tests/unit/, tests/integration/) — as opposed to the legacy tests/*.py
files, which are live HTTP scripts against an external preview deployment and
are explicitly out of scope here (see tests/README_LEGACY.md-equivalent notes
in the task history; do not follow that pattern).

Design goals for everything in this file:
  * No real MongoDB connection — `motor`'s client is swapped for an in-memory
    `mongomock_motor` client before `db.py` (imported by nearly every module)
    constructs it.
  * No real network calls to any external host (Razorpay, Resend, S3, OAuth
    providers, LLM providers, the live FX-rate API, ...). Anything that would
    hit the network is either left unconfigured (falls back to a safe no-op /
    dev-mode path already built into the app) or mocked per-test.
  * No real credentials anywhere — every credential-shaped env var below is an
    obviously-fake placeholder.
  * Safe under `pytest-xdist -n 2 --dist loadscope`: state (the mongomock
    database, the rate limiter) is process-wide, and `loadscope` can and will
    schedule multiple unrelated test modules/classes onto the same worker
    process, so it is wiped between every single test rather than only
    between modules.
"""
import os
import asyncio

import pytest

# ---------------------------------------------------------------------------
# 1. Environment — MUST be set before importing `db` (or anything that
#    imports `db`, i.e. almost the whole app). `db.py` does
#    `os.environ['MONGO_URL']` / `os.environ['DB_NAME']` at import time (a
#    plain KeyError if absent), and several services/routers read their own
#    env vars at import time too.
# ---------------------------------------------------------------------------
os.environ.setdefault("MONGO_URL", "mongodb://mock-host-not-used:27017")
os.environ.setdefault("DB_NAME", "iema_test")
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-do-not-use-in-prod")
os.environ.setdefault("JWT_ACCESS_MINUTES", "60")
os.environ.setdefault("JWT_REFRESH_DAYS", "30")
os.environ.setdefault("WELCOME_CREDITS", "100")
os.environ.setdefault("DAILY_CREDITS", "20")
os.environ.setdefault("CORS_ORIGINS", "*")

# Obviously-fake placeholder "credentials". These make `if RAZORPAY_KEY_ID:`
# style "is this provider configured" checks behave like a configured
# deployment (so the code path under test is the real one, not the "not
# configured" 501 branch) — any actual outbound call a test would trigger is
# mocked at the call site instead of ever leaving the process.
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_0000000000FAKE")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "fake_test_secret_not_real")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "fake_test_webhook_secret")
os.environ.setdefault("REVENUECAT_WEBHOOK_AUTH", "fake-test-revenuecat-auth")
os.environ.setdefault("ADMIN_HMAC_SECRET", "")  # keep AdminHMACMiddleware a no-op
os.environ.setdefault("ADMIN_EMAIL", "")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("RESEND_API_KEY", "")  # keep email_service in its dev/no-op mode
os.environ.setdefault("AWS_ACCESS_KEY_ID", "")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# 2. Swap Motor's real client for mongomock-motor's in-memory one BEFORE
#    `db.py` runs `client = AsyncIOMotorClient(MONGO_URL)`.
# ---------------------------------------------------------------------------
import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient

import db as _db  # noqa: E402  (import order matters: after the patch above)

assert isinstance(_db.client, AsyncMongoMockClient), (
    "db.client is a real AsyncIOMotorClient — something imported db.py before "
    "conftest.py patched motor.motor_asyncio.AsyncIOMotorClient. Make sure no "
    "test module imports `db`/`server`/`routers.*`/`services.*` at collection "
    "time ahead of this conftest."
)

# ---------------------------------------------------------------------------
# 3. Import the FastAPI app now that the DB layer is safely mocked.
# ---------------------------------------------------------------------------
from server import app  # noqa: E402
from middleware.security import limiter  # noqa: E402

# slowapi's in-memory rate-limit counters live for the lifetime of the worker
# process and are keyed by client IP. Every request made through TestClient
# comes from the same fake address, so real limits (e.g. `5/hour` on
# /auth/register) would start rejecting requests after a handful of tests in
# the same xdist worker. Disable rate limiting for the whole test session —
# it is exercised at the unit level (`middleware/security.py`) separately if
# ever needed, not something these tests are trying to verify.
limiter.enabled = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    """Backend for `@pytest.mark.anyio` async tests (service-layer unit tests
    that `await` coroutines directly, without going through TestClient)."""
    return "asyncio"


def _wipe_db_sync():
    async def _wipe():
        names = await _db.db.list_collection_names()
        for name in names:
            await _db.db[name].delete_many({})
    asyncio.run(_wipe())


@pytest.fixture(autouse=True)
def _reset_db():
    """Wipe every mongomock collection before AND after each test so tests
    are independent regardless of which worker/module/class runs them, or in
    what order — required because `-n 2 --dist loadscope` can and does put
    multiple unrelated test modules on the same worker process, sharing the
    same in-memory "database"."""
    _wipe_db_sync()
    yield
    _wipe_db_sync()


@pytest.fixture
def client():
    """Plain FastAPI TestClient — deliberately NOT used as a context manager.
    That would run `server.py`'s `@app.on_event("startup")` handler, which
    calls `ensure_indexes()` / `seed_pricing()` / admin auto-seed / starts the
    APScheduler-based Knowledge Engine — behavior meant for a real deployment,
    not a hermetic test. Tests instead seed whatever fixture data they need
    directly into the mongomock collections."""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def register_user(client):
    """Factory fixture: register a brand-new user through the real
    `POST /api/auth/register` endpoint and return `(user, tokens, headers)`.
    Exercises the real registration code path (hashing, wallet creation,
    token issuance) rather than hand-rolling a JWT."""
    state = {"n": 0}

    def _make(email: str = None, password: str = "Test@12345", name: str = "Test User"):
        state["n"] += 1
        email = email or f"user{state['n']}.{os.getpid()}@example.com"
        resp = client.post("/api/auth/register", json={
            "email": email, "password": password, "name": name,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
        return body["user"], body["tokens"], headers

    return _make


@pytest.fixture
def auth_user(register_user):
    """A single ready-to-use `(user, tokens, headers)` tuple for tests that
    just need *a* logged-in user and don't care about the specifics."""
    return register_user()
