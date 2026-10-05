"""At-rest encryption for MCP connector OAuth tokens.

Deliberately keyed off its own MCP_TOKEN_ENCRYPTION_KEY rather than reusing
JWT_SECRET (the shortcut builder_routes.py takes for the GitHub PAT) — these
guard third-party account access, so rotating login sessions should never
silently break stored connector tokens, and a leaked JWT_SECRET shouldn't
also expose them.
"""
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("MCP_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "MCP_TOKEN_ENCRYPTION_KEY is not set — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and add it to apps/api/.env before storing any connector tokens."
        )
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode()).decode()


def encrypt_json(data: Dict[str, Any]) -> str:
    return encrypt(json.dumps(data))


def decrypt_json(cipher: str) -> Dict[str, Any]:
    return json.loads(decrypt(cipher))


def demo() -> None:
    """Offline self-check: python -m services.crypto_service (requires the env var set)"""
    sample = "super-secret-oauth-token"
    enc = encrypt(sample)
    assert enc != sample
    assert decrypt(enc) == sample
    print("crypto_service self-check OK")


if __name__ == "__main__":
    demo()
