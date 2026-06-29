from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str

    database_url: str
    redis_url: str = "redis://redis:6379/0"

    # Comma-separated origins string; split at use-site to avoid pydantic-settings
    # trying to JSON-decode a plain URL string into list[str].
    backend_cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    ml_model_path:      str = "/app/models/anomaly_detector.pkl"
    forecast_model_dir: str = "/app/models"
    reports_dir:        str = "/app/reports"

    anthropic_api_key: str = ""

    # Comma-separated API keys. Empty string = auth disabled (dev default).
    # Example: API_KEYS=key-abc123,key-xyz789
    api_keys: str = ""


settings = Settings()
