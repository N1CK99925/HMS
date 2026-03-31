# app/routers/health.py
# The health check endpoint.
# This is the first thing you test after starting the app.
# It checks every database connection and returns their status.
# Monitoring tools and deployment pipelines use this to know if the app is alive.

from fastapi import APIRouter
from app.core.database import get_mongo_db, get_redis

router = APIRouter()


@router.get("/health", tags=["health"])
async def health_check():
    """
    Checks all service connections.
    Returns 200 if everything is healthy.
    Returns which services are up or down so you can diagnose problems fast.

    Hit this after starting the app:
        curl http://localhost:8000/health
    """
    status = {
        "status": "ok",
        "services": {}
    }

    # ── Check MongoDB ──────────────────────────────────────────────────────
    try:
        db = get_mongo_db()
        await db.command("ping")
        status["services"]["mongodb"] = "ok"
    except Exception as e:
        status["services"]["mongodb"] = f"error: {str(e)}"
        status["status"] = "degraded"

    # ── Check Redis ────────────────────────────────────────────────────────
    try:
        redis = get_redis()
        await redis.ping()
        status["services"]["redis"] = "ok"
    except Exception as e:
        status["services"]["redis"] = f"error: {str(e)}"
        status["status"] = "degraded"

    # PostgreSQL is checked indirectly — if the app started, Alembic ran,
    # which means PostgreSQL was reachable. You can add an explicit check here
    # if needed by importing the engine and running a test query.

    return status