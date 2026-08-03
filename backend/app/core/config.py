"""Centralized application settings, read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    Values are read from environment variables and, for local development,
    from a `.env` file (see `.env.example` for the supported keys).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "keystone-backend"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./keystone.db"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
