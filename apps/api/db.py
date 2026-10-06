"""MongoDB helpers and base document model."""
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


def _coerce_object_id(v: Any) -> str:
    if v is None:
        return v
    if isinstance(v, ObjectId):
        return str(v)
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(_coerce_object_id)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        if not doc:
            return None
        data = dict(doc)
        if "_id" in data:
            data["id"] = str(data.pop("_id"))
        return cls(**data)

    def to_mongo(self, exclude_id: bool = True) -> dict:
        data = self.model_dump(by_alias=False, exclude_none=False)
        if exclude_id and "id" in data:
            data.pop("id")
        # Convert datetimes to ISO strings
        for k, v in list(data.items()):
            if isinstance(v, datetime):
                data[k] = v.isoformat()
        return data


# Collections
users_col = db["users"]
sessions_col = db["sessions"]
wallets_col = db["wallets"]
transactions_col = db["credit_transactions"]
payment_transactions_col = db["payment_transactions"]
conversations_col = db["conversations"]
messages_col = db["messages"]
credit_packs_col = db["credit_packs"]
notifications_col = db["notifications"]
ai_requests_col = db["ai_requests"]
settings_col = db["settings"]
audit_logs_col = db["audit_logs"]
counseling_history_col = db["counseling_history"]
content_reports_col = db["content_reports"]
gmail_connections_col = db["gmail_connections"]   # one per user: Gmail OAuth tokens for Career Pipeline
career_profile_col = db["career_profile"]         # one per user: fit-scoring profile blurb
career_pipeline_col = db["career_pipeline"]       # one per user+job: scanned Gmail job alerts

# ---- MCP orchestration engine ----
mcp_connections_col = db["mcp_connections"]       # one per user+connector: encrypted OAuth tokens
mcp_audit_log_col = db["mcp_audit_log"]           # append-only: every MCP tool call made on a user's behalf
mcp_oauth_states_col = db["mcp_oauth_states"]     # short-lived CSRF state for the connect redirect round-trip

# ---- Resume Intelligence (persisted profile, shared by Career + Mock Interview) ----
resume_profiles_col = db["resume_profiles"]       # one per user: structured/parsed CV

# ---- Mock Interview ----
interview_packs_col = db["interview_packs"]                             # catalog (admin-managed), each carries a `config` (durations/topics/languages/etc.)
# One doc per purchase/admin-grant, NOT one per user — each grant snapshots the
# pack's config at grant time, so a later admin edit to a pack never
# retroactively changes what an already-purchased batch of sessions promised,
# and a user who owns sessions from two different packs can pick which
# format to use per interview. See services/interview_service.py.
interview_entitlement_grants_col = db["interview_entitlement_grants"]
interview_entitlement_tx_col = db["interview_entitlement_transactions"]  # purchase/consume/refund ledger
interview_sessions_col = db["interview_sessions"]
interview_turns_col = db["interview_turns"]                             # append-only transcript
interview_violations_col = db["interview_violations"]
interview_score_events_col = db["interview_score_events"]               # per-question rubric datapoints
interview_reports_col = db["interview_reports"]


async def ensure_indexes():
    await users_col.create_index("email", unique=True)
    await sessions_col.create_index("refresh_token", unique=True)
    await sessions_col.create_index("user_id")
    await wallets_col.create_index("user_id", unique=True)
    await transactions_col.create_index([("user_id", 1), ("created_at", -1)])
    await payment_transactions_col.create_index("session_id")
    await payment_transactions_col.create_index("order_id")
    await conversations_col.create_index([("user_id", 1), ("updated_at", -1)])
    await messages_col.create_index([("conversation_id", 1), ("created_at", 1)])
    await notifications_col.create_index([("user_id", 1), ("created_at", -1)])
    await ai_requests_col.create_index([("user_id", 1), ("created_at", -1)])
    await counseling_history_col.create_index([("user_id", 1), ("created_at", -1)])
    await content_reports_col.create_index([("status", 1), ("created_at", -1)])
    await content_reports_col.create_index([("user_id", 1), ("created_at", -1)])
    await gmail_connections_col.create_index("user_id", unique=True)
    await career_profile_col.create_index("user_id", unique=True)
    await career_pipeline_col.create_index([("user_id", 1), ("created_at", -1)])
    # sparse: docs whose parser couldn't recover a job_url omit the field entirely
    # (never store it as literal null) so they don't collide under this unique index.
    await career_pipeline_col.create_index([("user_id", 1), ("job_url", 1)], unique=True, sparse=True)
    await resume_profiles_col.create_index("user_id", unique=True)
    await mcp_connections_col.create_index([("user_id", 1), ("connector_id", 1)], unique=True)
    await mcp_audit_log_col.create_index([("user_id", 1), ("created_at", -1)])
    await mcp_oauth_states_col.create_index("state", unique=True)
    # TTL index: a state doc is only ever needed for the few minutes between
    # "Connect" and the provider's redirect back — auto-expire abandoned ones.
    # Requires `created_at` to be a real BSON date on this collection only
    # (services/mcp/oauth_service.py stores now_utc(), not now_iso()) —
    # Mongo TTL indexes don't expire ISO-string fields, unlike every other
    # `created_at` in this codebase.
    await mcp_oauth_states_col.create_index("created_at", expireAfterSeconds=600)
    # Mock Interview collections' indexes are owned by services/interview_service.py
    # (ensure_indexes(), called from server.py startup), mirroring contest_service.py.
