# app/core/security.py
# Everything related to JWT tokens and password hashing lives here.
# No route touches JWT logic directly — they all import from here.
#
# What is a JWT?
# A JWT (JSON Web Token) is a signed string the server gives to a user after login.
# The user sends it back on every request to prove who they are.
# It looks like: eyJhbGci...eyJ1c2VyX2lk...signature
# It has three parts: header.payload.signature
# The payload contains: user_id, tenant_id, role, expiry time
# The signature proves it hasn't been tampered with.

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

# ── Password hashing ───────────────────────────────────────────────────────
# bcrypt is the industry standard for hashing passwords.
# It's deliberately slow to make brute-force attacks impractical.
# NEVER store plain text passwords. NEVER use MD5 or SHA1 for passwords.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Converts a plain text password into a bcrypt hash for storage."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checks if a plain password matches a stored hash.
    Used during login — we never 'decrypt' a hash, we re-hash and compare.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT token creation ─────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a short-lived JWT access token (default: 15 minutes).
    The 'data' dict becomes the token payload.

    What goes in the payload:
      - sub (subject): the user's staff ID
      - tenant_id: which tenant this user belongs to
      - role: their current role (for RBAC)
      - exp: expiry timestamp (added automatically)
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Creates a long-lived JWT refresh token (default: 7 days).
    Used to get a new access token without logging in again.
    Stored securely (httpOnly cookie) — never in localStorage.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Verifies the token signature and returns the payload.
    Raises JWTError if the token is invalid, expired, or tampered with.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])