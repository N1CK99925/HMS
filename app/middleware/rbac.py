# app/middleware/rbac.py
# Permission enforcement — the Python equivalent of Spring Security's
# filter chain + @PreAuthorize annotations combined.
#
# Two dependency functions mirror Spring's two approaches:
#
#   require_roles(Role.DOCTOR, Role.NURSE)
#   → Spring: .hasAnyRole("DOCTOR", "NURSE")
#
#   require_permission(Permission.PRESCRIPTION_WRITE)
#   → Spring: @PreAuthorize("hasAuthority('prescription:write')")

from fastapi import Depends, HTTPException, status, Request
from app.core.roles import Role
from app.core.permissions import get_permissions_for_roles
from app.core.database import get_redis, get_mongo_db
from app.core.config import settings


async def get_current_user(request: Request) -> dict:
    """Base dependency — every protected route uses this."""
    user_id   = getattr(request.state, "user_id", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    roles     = getattr(request.state, "roles", [])

    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    return {"user_id": user_id, "tenant_id": tenant_id, "roles": roles}


async def resolve_permissions(user_id: str, tenant_id: str, roles: list[str]) -> set[str]:
    """
    Builds the full permission set for a user.
    Standard roles → resolved from ROLE_PERMISSIONS in memory (no DB).
    Custom tenant roles → Redis cache → MongoDB fallback.
    """
    all_permissions: set[str] = set()

    for role_str in roles:
        try:
            role_enum = Role(role_str)
            all_permissions.update(get_permissions_for_roles([role_enum]))
        except ValueError:
            # Custom tenant-defined role — not in standard enum
            redis = get_redis()
            cache_key = f"custom_role:{tenant_id}:{role_str}"
            cached = await redis.smembers(cache_key)
            if cached:
                all_permissions.update(cached)
            else:
                db = get_mongo_db()
                role_doc = await db["roles"].find_one({
                    "name": role_str, "tenant_id": tenant_id
                })
                if role_doc:
                    perms = set(role_doc.get("permissions", []))
                    all_permissions.update(perms)
                    if perms:
                        await redis.sadd(cache_key, *perms)
                        await redis.expire(cache_key, settings.RBAC_CACHE_TTL)

    return all_permissions


def require_roles(*allowed_roles: Role):
    """
    Spring equivalent: .hasAnyRole("DOCTOR", "NURSE")

    Usage:
        @router.get("/patients")
        async def list_patients(
            _=Depends(require_roles(Role.DOCTOR, Role.NURSE, Role.HOSPITAL_ADMIN))
        ):
    """
    async def dependency(
        request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        user_role_enums = set()
        for r in current_user["roles"]:
            try:
                user_role_enums.add(Role(r))
            except ValueError:
                pass

        if not any(role in user_role_enums for role in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required one of: {[r.value for r in allowed_roles]}"
            )
        return current_user

    return dependency


def require_permission(permission: str):
    """
    Spring equivalent: @PreAuthorize("hasAuthority('patient:read')")

    Always use Permission constants — never raw strings:
        CORRECT: require_permission(Permission.PATIENT_READ)
        WRONG:   require_permission("patient:read")
    """
    async def dependency(
        request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        permissions = await resolve_permissions(
            current_user["user_id"],
            current_user["tenant_id"],
            current_user["roles"]
        )
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Missing permission: {permission}"
            )
        return current_user

    return dependency


async def invalidate_role_cache(tenant_id: str, roles: list[str]):
    """Deletes cached permission sets so role changes take effect immediately."""
    redis = get_redis()
    keys = [f"custom_role:{tenant_id}:{role}" for role in roles]
    if keys:
        await redis.delete(*keys)