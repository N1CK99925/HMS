
#   uvicorn main:app --reload


from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_mongo, close_mongo, connect_redis, close_redis
from app.routers import health, auth, patients, encounters, clinical_notes, prescriptions, lab_orders, imaging_studies
from app.middleware.tenant import TenantMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────
    print("Starting HMS API...")
    await connect_mongo()     
    await connect_redis()   

    print("All services connected. HMS API is ready.")

    yield  

    # ── Shutdown ───────────────────────────────────────────────
    print("Shutting down HMS API...")
    await close_mongo()
    await close_redis()
    print("Connections closed.")


app = FastAPI(
    title="HMS SaaS API",
    description="Multi-tenant Hospital Management System",
    version="0.1.0",
    lifespan=lifespan,
    # Disable the automatic /docs in production for security
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)



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




app.include_router(health.router)                         
app.include_router(auth.router,     prefix="/api/v1/auth")    
app.include_router(patients.router,         prefix="/api/v1")
app.include_router(encounters.router,       prefix="/api/v1")
app.include_router(clinical_notes.router,   prefix="/api/v1")
app.include_router(prescriptions.router,    prefix="/api/v1")
app.include_router(lab_orders.router,       prefix="/api/v1")
app.include_router(imaging_studies.router,  prefix="/api/v1")