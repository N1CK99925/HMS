# app/middleware/rbac.py
# Handles permission checking for every protected route.
#
# This is NOT a middleware in the Starlette sense — it's a FastAPI dependency.
# The difference:
#   - Middleware runs on EVERY request (like TenantMiddleware)
#   - A dependency runs only on routes that explicitly require it
#
# Usage in a route:
#   @router.get("/patients")
#   async def list_patients(
#       _: None = Depends(require_permission("patient:read"))
#   ):
#
# This means: "Only allow this route if the current user has patient:read"

from fastapi import Depends, HTTPException, status, Request
from app.core.database import get_mongo_db, get_redis
from app.core.config import settings


async def get_current_user(request: Request) -> dict:
    """
    Extracts the current user from request.state (set by TenantMiddleware).
    Used as a base dependency in all protected routes.
    """
    user_id   = getattr(request.state, "user_id", None)
    tenant_id = getattr(request.state, "tenant_id", None)

    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    return {"user_id": user_id, "tenant_id": tenant_id}


async def get_user_permissions(user_id: str, tenant_id: str) -> set:
    """
    Returns the full set of permissions for a user.

    Resolution order (from ADR Decision 3):
    1. Check Redis cache — fast path, hits on most requests
    2. On cache miss: query MongoDB for user's roles,
       build permission set, cache it for 5 minutes

    Returns a set of strings like: {"patient:read", "prescription:write"}
    """
    redis = get_redis()
    cache_key = f"permissions:{tenant_id}:{user_id}"

    # ── Step 1: Check Redis cache ───────────────────────────────────────────
    cached = await redis.smembers(cache_key)   # smembers returns a set
    if cached:
        return cached  # Cache hit — return immediately

    # ── Step 2: Cache miss — build from DB ─────────────────────────────────
    db = get_mongo_db()

    # Get all role assignments for this user
    role_assignments = await db["user_roles"].find({
        "tenant_id": tenant_id,
        "staff_id": user_id,
        "is_active": True
    }).to_list(length=50)

    if not role_assignments:
        return set()  # No roles = no permissions = default deny

    role_names = [r["role_name"] for r in role_assignments]

    # Get all permissions for those roles
    roles = await db["roles"].find({
        "tenant_id": tenant_id,
        "name": {"$in": role_names}
    }).to_list(length=50)

    # Merge all permissions from all roles (additive model)
    # If a user has Nurse + Department Head, they get the union of both
    all_permissions = set()
    for role in roles:
        all_permissions.update(role.get("permissions", []))

    # ── Step 3: Cache the result in Redis ───────────────────────────────────
    if all_permissions:
        await redis.sadd(cache_key, *all_permissions)
        await redis.expire(cache_key, settings.RBAC_CACHE_TTL)  # 5 minutes

    return all_permissions


def require_permission(permission: str):
    """
    Returns a FastAPI dependency that checks for a specific permission.

    Usage:
        @router.get("/patients")
        async def list_patients(
            _: None = Depends(require_permission("patient:read"))
        ):

    If the user doesn't have the permission, FastAPI returns 403 automatically.
    The route body never executes.
    """
    async def dependency(
        request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        user_id   = current_user["user_id"]
        tenant_id = current_user["tenant_id"]

        permissions = await get_user_permissions(user_id, tenant_id)

        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission}"
            )

        # Return user context so the route can use it
        return current_user

    return dependency


async def invalidate_permission_cache(user_id: str, tenant_id: str):
    """
    Called whenever a user's roles are changed.
    Deletes the Redis cache key immediately — don't wait for TTL expiry.
    This is the active invalidation strategy from ADR Decision 3.

    Usage in a role-change endpoint:
        await invalidate_permission_cache(staff_id, tenant_id)
    """
    redis = get_redis()
    await redis.delete(f"permissions:{tenant_id}:{user_id}")