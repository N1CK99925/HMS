# main.py
# The entry point of the entire application.
# FastAPI starts here. Think of this as the front door of the building.
#
# Run the app with:
#   uvicorn main:app --reload
#
# --reload means the server restarts automatically when you save a file.
# Only use --reload in development, never in production.

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_mongo, close_mongo, connect_redis, close_redis
from app.routers import health, auth, patients
from app.middleware.tenant import TenantMiddleware


# ── Lifespan ───────────────────────────────────────────────────────────────
# Lifespan manages what happens when the app STARTS and when it SHUTS DOWN.
# This is where we open and close database connections.
#
# Why here and not inside each route?
# Because opening a new DB connection on every request is extremely slow.
# We open ONE connection when the app starts and reuse it for every request.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────
    print("Starting HMS API...")
    await connect_mongo()     # Opens MongoDB connection pool
    await connect_redis()     # Opens Redis connection
    # PostgreSQL sessions are created per-request via Depends()
    # so we don't need to connect it here explicitly
    print("All services connected. HMS API is ready.")

    yield  # The app runs here — everything above is startup, below is shutdown

    # ── Shutdown ───────────────────────────────────────────────
    print("Shutting down HMS API...")
    await close_mongo()
    await close_redis()
    print("Connections closed.")


# ── App instance ───────────────────────────────────────────────────────────
app = FastAPI(
    title="HMS SaaS API",
    description="Multi-tenant Hospital Management System",
    version="0.1.0",
    lifespan=lifespan,
    # Disable the automatic /docs in production for security
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)


# ── CORS Middleware ────────────────────────────────────────────────────────
# CORS controls which websites are allowed to call this API from a browser.
# In development we allow everything. In production, restrict to your domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["https://yourhospital.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Tenant Middleware ──────────────────────────────────────────────────────
# Runs on every request. Extracts tenant_id from JWT and attaches it
# to request.state so every route can access it without repeating the logic.
app.add_middleware(TenantMiddleware)


# ── Routers ────────────────────────────────────────────────────────────────
# Each router handles one domain of the API.
# prefix="/api/v1" means all routes start with /api/v1/...

app.include_router(health.router)                              # GET /health
app.include_router(auth.router,     prefix="/api/v1/auth")    # POST /api/v1/auth/login
app.include_router(patients.router, prefix="/api/v1")         # GET  /api/v1/patients