from functools import lru_cache
from typing import List
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://admin:secret@localhost:5432/diary"
    SECRET_KEY: str = "change-this-to-a-very-secret-random-key-in-production-min-32-chars"
    ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    ENVIRONMENT: str = "development"
    COOKIE_NAME: str = "locus_session"
    PORT: int = 8010
    TIMEZONE: str = "Asia/Almaty"
    HOMEWORK_RETENTION_DAYS: int = Field(default=30, ge=1)
    CORS_ORIGINS: str = ""
    # Enable only if the reverse proxy connects from a public address
    TRUST_PROXY_HEADERS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.SECRET_KEY:
            self.SECRET_KEY = self.SECRET_KEY.strip()
        if self.is_production:
            if (
                not self.SECRET_KEY
                or self.SECRET_KEY == "change-this-to-a-very-secret-random-key-in-production-min-32-chars"
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError(
                    "В production-окружении (ENVIRONMENT=production) необходимо задать уникальный стойкий SECRET_KEY длиной не менее 32 символов в .env"
                )
        return self

    @property
    def async_database_url(self) -> str:
        """Convert standard postgresql:// URL to asyncpg format and normalize SSL params."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # asyncpg does not support sslmode=..., it uses ssl=...
        if "sslmode=" in url:
            url = url.replace("sslmode=", "ssl=")

        if ("supabase.co" in url or "supabase.com" in url) and "ssl=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}ssl=require"

        return url

    @property
    def sync_database_url(self) -> str:
        """Convert URL to sync format for Alembic migrations."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        elif url.startswith("sqlite+aiosqlite://"):
            url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        return url

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")

    @property
    def parsed_cors_origins(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return ["*"] if not self.is_production else []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
