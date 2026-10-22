from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BASE_DIR = Path(__file__).resolve().parent


class AuthJWT(BaseModel):
    private_key_path: Path = BASE_DIR / "certs" / "jwt-private.pem"
    public_key_path: Path = BASE_DIR / "certs" / "jwt-public.pem"
    algorithm: Literal["RS256"] = "RS256"
    access_token_expired_minutes: int = Field(default=60, gt=0)
    refresh_token_expired_days: int = Field(default=30, gt=0)


class CacheSettings(BaseModel):
    enabled: bool = True
    prefix: str = Field(
        default="journalblog:v1", pattern=r"^[a-zA-Z0-9:_-]+$", max_length=80
    )
    article_ttl: int = Field(default=60, ge=1, le=3600)
    catalog_ttl: int = Field(default=300, ge=1, le=3600)
    timeout_seconds: float = Field(default=0.1, gt=0, le=2)
    retry_seconds: float = Field(default=5, gt=0, le=60)
    lock_seconds: int = Field(default=10, ge=1, le=60)
    wait_seconds: float = Field(default=0.2, ge=0, le=1)
    max_value_bytes: int = Field(default=1048576, ge=1024, le=10485760)
    max_connections: int = Field(default=50, ge=1, le=500)


class Settings(BaseSettings):
    # DATABASE_URL also permits an isolated SQLite database for local use/tests.
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "journalblog"
    postgres_password: str = ""
    postgres_db: str = "journalblog"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    auth_jwt: AuthJWT = Field(default_factory=AuthJWT)
    cache: CacheSettings = Field(default_factory=CacheSettings)

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_nested_delimiter="__", extra="ignore"
    )

    @property
    def DATABASE_URL_asyncpg(self) -> str | URL:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
