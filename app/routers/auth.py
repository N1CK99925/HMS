# app/routers/auth.py
# Handles login, token refresh, and logout.
# These are the only routes that don't require an existing JWT —
# because you don't have one yet when you're logging in.
#
# Flow:
#   1. Staff sends email + password to POST /api/v1/auth/login
#   2. We verify credentials against the staff collection in MongoDB
#   3. We issue an access token (15 min) and a refresh token (7 days)
#   4. Staff uses the access token on every request
#   5. When the access token expires, they use the refresh token to get a new one
#   6. Logout invalidates the refresh token in Redis

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from jose import JWTError

from app.core.database import get_mongo_db, get_redis
from app.core.security import (
    verify_password, create_access_token,
    create_refresh_token, decode_token
)
from app.core.config import settings

router = APIRouter(tags=["auth"])


# ── Request / Response shapes ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_slug: str    # Which hospital is logging in — determines tenant_id


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Routes ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """
    Authenticates a staff member and returns JWT tokens.

    Steps:
    1. Find the tenant by slug
    2. Find the staff by email within that tenant
    3. Verify the password
    4. Issue access + refresh tokens with tenant_id in the payload
    """
    db = get_mongo_db()

    # ── Step 1: Verify tenant exists ───────────────────────────────────────
    tenant = await db["tenants"].find_one({"slug": body.tenant_slug, "is_active": True})
    if not tenant:
        # Return the same error whether tenant or user is wrong —
        # don't reveal which one failed (security best practice)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    tenant_id = tenant["id"]

    # ── Step 2: Find the staff member ─────────────────────────────────────
    staff = await db["staff"].find_one({
        "tenant_id": tenant_id,
        "email": body.email,
        "employment_status": "active",
        "deleted_at": None
    })
    if not staff:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # ── Step 3: Verify password ────────────────────────────────────────────
    if not verify_password(body.password, staff["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # ── Step 4: Build token payload ────────────────────────────────────────
    # Everything in this payload is available in every route via the JWT.
    # The middleware extracts tenant_id from here — never trust the request body.
    token_data = {
        "sub": staff["id"],             # Subject = who this token belongs to
        "tenant_id": tenant_id,
        "email": staff["email"],
        "name": f"{staff['first_name']} {staff['last_name']}",
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # ── Step 5: Store refresh token in Redis ───────────────────────────────
    # Key: "refresh:{staff_id}" → Value: the refresh token
    # TTL: 7 days (matching the token expiry)
    # When the user logs out, we DEL this key — invalidating the token.
    redis = get_redis()
    await redis.setex(
        f"refresh:{staff['id']}",
        settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,  # TTL in seconds
        refresh_token
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(body: RefreshRequest):
    """
    Issues a new access token using a valid refresh token.
    Called automatically by the frontend when the access token expires.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token"
    )

    try:
        payload = decode_token(body.refresh_token)

        # Confirm it's a refresh token, not an access token
        if payload.get("type") != "refresh":
            raise credentials_error

        staff_id = payload.get("sub")
        if not staff_id:
            raise credentials_error

    except JWTError:
        raise credentials_error

    # ── Verify refresh token matches what we stored in Redis ───────────────
    # This is what makes logout work — if we deleted the Redis key on logout,
    # this check fails even with a valid token signature.
    redis = get_redis()
    stored_token = await redis.get(f"refresh:{staff_id}")
    if not stored_token or stored_token != body.refresh_token:
        raise credentials_error

    # Issue new tokens (token rotation — the old refresh token is replaced)
    token_data = {
        "sub": payload["sub"],
        "tenant_id": payload["tenant_id"],
        "email": payload["email"],
        "name": payload["name"],
    }

    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    # Replace old refresh token in Redis
    await redis.setex(
        f"refresh:{staff_id}",
        settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        new_refresh_token
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest):
    """
    Invalidates the refresh token and clears the RBAC cache.
    After this, the user's tokens stop working even before they expire.

    The access token is still technically valid until its 15-minute expiry,
    which is an acceptable tradeoff for a stateless JWT system.
    """
    try:
        payload = decode_token(body.refresh_token)
        staff_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")

        if staff_id:
            redis = get_redis()
            # Delete refresh token — future refresh calls will fail
            await redis.delete(f"refresh:{staff_id}")
            # Delete RBAC permission cache — clean up after logout
            await redis.delete(f"permissions:{tenant_id}:{staff_id}")

    except JWTError:
        pass  # If token is already invalid, logout is effectively done

    return  # 204 No Content