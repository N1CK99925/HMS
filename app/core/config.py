from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    postgres_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    mongo_url: str
    
    class Config:
        env_file = ".env"


settings = Settings()