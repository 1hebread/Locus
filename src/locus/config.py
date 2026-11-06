from functools import lru_cache
from typing import List
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Local development default (matches docker-compose.yml). Never use in production.
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
    # Web Push is disabled while either key is empty; generate both with `uv run locus-vapid`
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@example.com"
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
        # Empty env vars would otherwise override these defaults with ""
        self.VAPID_PUBLIC_KEY = self.VAPID_PUBLIC_KEY.strip().strip("\"'").strip()
        self.VAPID_PRIVATE_KEY = self.VAPID_PRIVATE_KEY.strip().strip("\"'").strip()
        self.VAPID_SUBJECT = self.VAPID_SUBJECT.strip().strip("\"'").strip() or "mailto:admin@example.com"
        if self.VAPID_PUBLIC_KEY and len(self.VAPID_PUBLIC_KEY) < 60:
            raise ValueError(
                "VAPID_PUBLIC_KEY некорректен (длина менее 60 символов). "
                "Убедитесь, что в VAPID_PUBLIC_KEY не был по ошибке скопирован приватный ключ. "
                "Публичный ключ имеет длину 87 символов и генерируется через `uv run locus-vapid`."
            )
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
