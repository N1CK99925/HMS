# app/middleware/tenant.py
# Runs on EVERY request before it reaches any route.
# Extracts tenant_id, user_id, AND roles from the JWT + DB,
# then attaches them all to request.state.


from starlette.middleware.base import BaseRequestMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from jose import JWTError
from app.core.security import decode_token
from app.core.database import get_mongo_db, get_redis
from app.core.config import settings

PUBLIC_ROUTES = {
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/docs",
    "/redoc",
    "/openapi.json"
}


class TenantMiddleware(BaseRequestMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_ROUTES:
            return await call_next(request)

        # ── Extract and verify JWT ─────────────────────────────────────────
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"}
            )

        token = auth_header.split(" ")[1]
        try:
            payload = decode_token(token)
        except JWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"}
            )

        user_id   = payload.get("sub")
        tenant_id = payload.get("tenant_id")

        # ── Attach identity to request.state ──────────────────────────────
        request.state.user_id   = user_id
        request.state.tenant_id = tenant_id
        request.state.email     = payload.get("email")
        request.state.user_name = payload.get("name")

        # ── Fetch and attach roles ─────────────────────────────────────────
        # Roles are cached in Redis to avoid a DB hit on every request.
        # Cache key: "roles:{tenant_id}:{user_id}"
        # TTL: 5 minutes — same as permission cache per ADR Decision 3.
        # On role change: actively delete this key (don't wait for TTL).

        redis = get_redis()
        roles_cache_key = f"roles:{tenant_id}:{user_id}"

        cached_roles = await redis.lrange(roles_cache_key, 0, -1)
        if cached_roles:
            request.state.roles = cached_roles
        else:
            # Cache miss — fetch from MongoDB
            db = get_mongo_db()
            assignments = await db["user_roles"].find(
                {"tenant_id": tenant_id, "staff_id": user_id, "is_active": True},
                {"role_name": 1}
            ).to_list(length=50)

            roles = [a["role_name"] for a in assignments]
            request.state.roles = roles

            # Cache the roles list
            if roles:
                await redis.delete(roles_cache_key)
                await redis.rpush(roles_cache_key, *roles)
                await redis.expire(roles_cache_key, settings.RBAC_CACHE_TTL)

        return await call_next(request)