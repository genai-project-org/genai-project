"""Notification service helper."""
from db import notifications_col
from models import Notification


async def notify(user_id: str, title: str, body: str = "", kind: str = "info", action_url: str = None):
    n = Notification(user_id=user_id, title=title, body=body, kind=kind, action_url=action_url)
    await notifications_col.insert_one(n.to_mongo())
