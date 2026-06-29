from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str

    database_url: str
    redis_url: str = "redis://redis:6379/0"

    backend_cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
