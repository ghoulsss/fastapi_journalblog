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
