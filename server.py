"""Server entry point."""
import os
import logging
from pathlib import Path
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from db import ensure_indexes, users_col, credit_packs_col, now_iso
from auth import hash_password
from models import User, CreditPack

from routers.auth_routes import router as auth_router
from routers.wallet_routes import router as wallet_router
from routers.chat_routes import router as chat_router
from routers.usage_routes import router as usage_router
from routers.pack_routes import router as pack_router
from routers.payments_routes import router as payments_router
from routers.notifications_routes import router as notifications_router
from routers.admin_routes import router as admin_router
from routers.uploads_routes import router as uploads_router
from routers.studio_routes import router as studio_router
from routers.career_routes import router as career_router
from routers.builder_routes import router as builder_router
from routers.counseling_routes import router as counseling_router
from middleware.data_lake_middleware import DataLakeMiddleware
from middleware.security import SecurityHeadersMiddleware, AdminHMACMiddleware, limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from services.data_lake import ensure_events_indexes
from services.knowledge_retriever import ensure_kb_indexes
from services.pricing_engine import seed_defaults as seed_pricing, ensure_indexes as ensure_pricing_indexes
from services.knowledge_engine import start as start_kb_engine

app = FastAPI(title="IEMA.ai v2 API", version="2.0.0")

from fastapi import Request
from fastapi.responses import RedirectResponse

api_router = APIRouter(prefix="/api")

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "IEMA.ai API"
    }

@api_router.get("/")
async def root():
    return {"name": "IEMA.ai v2", "version": "2.0.0", "status": "ok"}


@api_router.get("/health")
async def health():
    return {"status": "healthy"}


app.include_router(auth_router, prefix="/auth", include_in_schema=False)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(wallet_router)
api_router.include_router(chat_router)
api_router.include_router(usage_router)
api_router.include_router(pack_router)
api_router.include_router(payments_router)
api_router.include_router(notifications_router)
api_router.include_router(admin_router)
api_router.include_router(uploads_router)
api_router.include_router(studio_router)
api_router.include_router(career_router)
api_router.include_router(builder_router)
api_router.include_router(counseling_router)

# Stripe was removed; nothing to mount at /api/webhook/stripe anymore.

app.include_router(api_router)

# Serve locally-generated media (Sora 2 videos, etc.) under /api/media-static/
# so the frontend can display them via a public URL even when S3 upload is not
# configured. The route is under /api/ so Kubernetes ingress reaches port 8001.
_uploads_dir = Path(os.environ.get("BACKEND_UPLOADS_DIR", str(ROOT_DIR / "uploads")))
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/media-static", StaticFiles(directory=str(_uploads_dir)), name="media-static")

app.add_middleware(DataLakeMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AdminHMACMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


DEFAULT_PACKS = [
    {"name": "Starter", "slug": "starter-usd", "description": "Casual explorers", "price": 5.0, "currency": "usd", "credits": 500, "bonus_credits": 0, "is_popular": False, "sort_order": 1},
    {"name": "Standard", "slug": "standard-usd", "description": "Regular users", "price": 15.0, "currency": "usd", "credits": 1800, "bonus_credits": 200, "is_popular": True, "sort_order": 2},
    {"name": "Pro", "slug": "pro-usd", "description": "Power users", "price": 39.0, "currency": "usd", "credits": 5000, "bonus_credits": 750, "is_popular": False, "sort_order": 3},
    {"name": "Business", "slug": "business-usd", "description": "Teams & startups", "price": 99.0, "currency": "usd", "credits": 15000, "bonus_credits": 2500, "is_popular": False, "sort_order": 4},
    {"name": "Starter", "slug": "starter-inr", "description": "Casual explorers", "price": 399.0, "currency": "inr", "credits": 500, "bonus_credits": 0, "is_popular": False, "sort_order": 1},
    {"name": "Standard", "slug": "standard-inr", "description": "Regular users", "price": 1199.0, "currency": "inr", "credits": 1800, "bonus_credits": 200, "is_popular": True, "sort_order": 2},
    {"name": "Pro", "slug": "pro-inr", "description": "Power users", "price": 2999.0, "currency": "inr", "credits": 5000, "bonus_credits": 750, "is_popular": False, "sort_order": 3},
    {"name": "Business", "slug": "business-inr", "description": "Teams & startups", "price": 7999.0, "currency": "inr", "credits": 15000, "bonus_credits": 2500, "is_popular": False, "sort_order": 4},
]


@app.on_event("startup")
async def startup():
    await ensure_indexes()
    await ensure_events_indexes()
    await ensure_kb_indexes()
    await seed_pricing()
    await ensure_pricing_indexes()
    # Continuous Knowledge Engine — enriches KB from Wikipedia/DDG every 4h
    try:
        start_kb_engine(interval_hours=4)
    except Exception as e:
        logger.warning(f"Knowledge Engine failed to start: {e}")
    # Idempotently seed builder templates
    try:
        from scripts.seed_templates import seed as seed_templates
        await seed_templates()
    except Exception as e:
        logger.warning(f"Template seed skipped: {e}")
    # Seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_email and admin_password:
        existing = await users_col.find_one({"email": admin_email})
        if not existing:
            admin = User(
                email=admin_email,
                name="IEMA Admin",
                password_hash=hash_password(admin_password),
                role="admin",
                provider="email",
                email_verified=True,
            )
            await users_col.insert_one(admin.to_mongo())
            logger.info(f"Seeded admin user: {admin_email}")
        else:
            # Ensure role is admin
            if existing.get("role") != "admin":
                await users_col.update_one({"email": admin_email}, {"$set": {"role": "admin"}})

    # Seed credit packs ONLY on cold-start (when zero packs exist). This lets
    # admins freely edit / delete / add packs from the admin panel without the
    # next server restart clobbering their changes.
    existing_pack_count = await credit_packs_col.count_documents({})
    if existing_pack_count == 0:
        logger.info("No packs found — seeding defaults")
        for pack_data in DEFAULT_PACKS:
            pack = CreditPack(**pack_data)
            await credit_packs_col.insert_one(pack.to_mongo())
    logger.info("IEMA.ai v2 API started")


@app.on_event("shutdown")
async def shutdown():
    from db import client
    client.close()
