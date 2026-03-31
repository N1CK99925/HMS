# app/middleware/tenant.py
# Runs on EVERY request before it reaches any route.
# Extracts tenant_id and user info from the JWT and attaches them
# to request.state so routes don't need to repeat this logic.
#
# Think of this as the hotel security desk — everyone passes through,
# gets their keycard scanned, and is identified before entering.

from starlette.middleware.base import BaseRequestMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from jose import JWTError
from app.core.security import decode_token

# Routes that don't need a JWT token to access
PUBLIC_ROUTES = {"/health", "/api/v1/auth/login", "/api/v1/auth/refresh", "/docs", "/redoc", "/openapi.json"}


class TenantMiddleware(BaseRequestMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip JWT check for public routes
        if request.url.path in PUBLIC_ROUTES:
            return await call_next(request)

        # ── Extract token from Authorization header ─────────────────────────
        # Expected format: "Authorization: Bearer eyJhbGci..."
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

        # ── Attach to request.state ─────────────────────────────────────────
        # Every route can now access:
        #   request.state.user_id
        #   request.state.tenant_id
        #   request.state.email
        # Without repeating the JWT decode logic in every route.
        request.state.user_id   = payload.get("sub")
        request.state.tenant_id = payload.get("tenant_id")
        request.state.email     = payload.get("email")
        request.state.user_name = payload.get("name")

        return await call_next(request)