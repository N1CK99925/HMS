# database.py
# This file creates and exports connections to all 3 databases.
# Every other file in the project imports from here.
# Think of this as the plumbing room — everything connects through it.

from motor.motor_asyncio import AsyncIOMotorClient          # MongoDB async driver
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import redis.asyncio as aioredis
from app.core.config import settings

# ─────────────────────────────────────────────
# MONGODB
# Motor is the async version of PyMongo.
# We create ONE client for the entire app lifetime.
# Each request does NOT create a new connection — it reuses this one.
# ─────────────────────────────────────────────

mongo_client: AsyncIOMotorClient = None  # filled in on startup
mongo_db = None                          # filled in on startup


async def connect_mongo():
    """Called once when the app starts."""
    global mongo_client, mongo_db
    mongo_client = AsyncIOMotorClient(settings.MONGO_URL)
    mongo_db = mongo_client[settings.MONGO_DB_NAME]
    await mongo_client.admin.command("ping")
    print("MongoDB connected")


async def close_mongo():
    """Called once when the app shuts down."""
    global mongo_client
    if mongo_client:
        mongo_client.close()


def get_mongo_db():
    """
    Returns the MongoDB database object.
    Usage in a route:
        db = get_mongo_db()
        patient = await db["patients"].find_one({"tenant_id": tenant_id})
    """
    return mongo_db




postgres_engine = create_async_engine(
    settings.POSTGRES_URL,
    echo=True,        # setf alse when prod
    pool_size=10,      
    max_overflow=20,   
)

AsyncSessionLocal = sessionmaker(
    bind=postgres_engine,
    class_=AsyncSession,
    expire_on_commit=False, 
)


async def get_postgres_session():
    """
    FastAPI dependency — injects a database session into a route.
    The 'async with' block ensures the session is always closed,
    even if an error occurs halfway through.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_postgres_session)):
            result = await db.execute(select(Billing))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# REDIS
# Used for: RBAC permission cache, JWT tokens,
# rate limiting, appointment slot availability.
# One client, reused across all requests.
# ─────────────────────────────────────────────

redis_client: aioredis.Redis = None 

async def connect_redis():

    global redis_client
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,  
    )
    await redis_client.ping() 
    print("Redis connected")


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()


def get_redis():
    """
    Returns the Redis client.
    Usage in a service:
        redis = get_redis()
        cached = await redis.get(f"permissions:{tenant_id}:{user_id}")
    """
    return redis_client