"""
JWT utilities — issue and validate session tokens.

Tokens carry a single claim: user_id (UUID string).
Signed with HS256 using JWT_SECRET from config.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import jwt
from app.config import settings


def issue_token(user_id: str) -> str:
    """
    Issue a signed JWT for a user.

    Payload: { sub: user_id, iat: now, exp: now + JWT_EXPIRE_DAYS }
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def validate_token(token: str) -> str:
    """
    Validate a JWT and return the user_id (sub claim).

    Raises jwt.PyJWTError on invalid / expired tokens.
    Callers should catch and return 401.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    return payload["sub"]
