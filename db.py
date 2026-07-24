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
