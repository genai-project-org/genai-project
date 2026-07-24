"""S3 file storage service."""
import os
import uuid
import logging
from typing import Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "iema-ai-uploads")

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
    return _s3


def is_configured() -> bool:
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and S3_BUCKET)


async def upload_bytes(data: bytes, filename: str, content_type: str = "application/octet-stream", folder: str = "chat") -> str:
    """Upload bytes to S3 and return the S3 key (private)."""
    import asyncio
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    key = f"{folder}/{uuid.uuid4().hex}{'.' + ext if ext else ''}"

    def _put():
        _client().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    await asyncio.to_thread(_put)
    return key


async def upload_bytes_at_key(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload/overwrite bytes at an exact S3 key. Returns the key."""
    import asyncio

    def _put():
        _client().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    await asyncio.to_thread(_put)
    return key


def get_signed_url(key: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed URL for downloading a private S3 object."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
