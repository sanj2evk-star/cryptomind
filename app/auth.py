"""
auth.py - JWT authentication for the API.

Multi-user login that issues JWT tokens. Users are stored
in data/users.json via user_manager. Protected routes
require a valid Bearer token and extract user_id from it.

Usage:
    POST /login  {"username": "admin", "password": "changeme"}
    → {"access_token": "eyJ...", "token_type": "bearer"}

    GET /status  -H "Authorization: Bearer eyJ..."
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from user_manager import verify_user, ensure_admin

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", os.urandom(32).hex())
JWT_EXPIRY_HOURS = 24

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# JWT helpers (minimal, no dependencies)
# ---------------------------------------------------------------------------

def _b64encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(s) % 4
    return urlsafe_b64decode(s + "=" * padding)


def _sign(payload: str) -> str:
    """HMAC-SHA256 sign a string."""
    return _b64encode(
        hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    )


def create_token(user_id: str) -> str:
    """Create a JWT access token.

    Args:
        user_id: Authenticated username.

    Returns:
        JWT token string.
    """
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time() + JWT_EXPIRY_HOURS * 3600),
    }).encode())

    signature = _sign(f"{header}.{payload}")
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token.

    Args:
        token: JWT token string.

    Returns:
        Decoded payload dict.

    Raises:
        ValueError: If token is invalid or expired.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")

    header_b64, payload_b64, signature = parts

    expected = _sign(f"{header_b64}.{payload_b64}")
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid signature")

    payload = json.loads(_b64decode(payload_b64))

    if payload.get("exp", 0) < time.time():
        raise ValueError("Token expired")

    return payload


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> str | None:
    """Verify credentials against user_manager and return a token.

    Args:
        username: Provided username.
        password: Provided password.

    Returns:
        JWT token string if valid, None if invalid.
    """
    ensure_admin()

    if verify_user(username, password):
        return create_token(username.strip().lower())
    return None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency that enforces JWT auth on a route.

    Returns:
        Decoded JWT payload dict with 'sub' (user_id).

    Raises:
        HTTPException 401 if token is missing, invalid, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_token(credentials.credentials)
        return payload
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_id(user: dict = Depends(require_auth)) -> str:
    """Extract user_id from the authenticated token.

    Convenience dependency for routes that need the user_id string.

    Returns:
        user_id string.
    """
    return user["sub"]
