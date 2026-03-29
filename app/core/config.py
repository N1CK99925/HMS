# config.py
# Reads every value from the .env file and makes them available
# as a typed Python object called `settings`.
# Any file that needs a secret imports settings from here.
# Never hardcode secrets directly in code — always use settings.

from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):

    MONGO_URL: str
    MONGO_DB_NAME: str = "hms"

#    asyncpg+
    POSTGRES_URL: str


    REDIS_URL: str = "redis://localhost:6379/0"


    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

   
    JWT_SECRET_KEY: str               
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15    
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    
    RBAC_CACHE_TTL: int = 300          # 5 minutes
    SLOT_AVAILABILITY_TTL: int = 30    # 30 s
    FEATURE_FLAG_TTL: int = 600        # 10 m
    OTP_TTL: int = 600                 # 10 m

    class Config:
        env_file = Path(__file__).parent.parent.parent / ".env"
        case_sensitive = True
        extra = "ignore"


# singleton 
@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()