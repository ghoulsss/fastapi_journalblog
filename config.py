from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis

BASE_DIR = Path(__file__).resolve().parent


class AuthJWT(BaseModel):
    private_key_path: Path = BASE_DIR / "certs" / "jwt-private.pem"
    public_key_path: Path = BASE_DIR / "certs" / "jwt-public.pem"
    algorithm: str = "RS256"
    access_token_expired_minutes: int = 60
    refresh_token_expired_days: int = 30


class Settings(BaseSettings):
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # redis_password: str
    # redis_user: str
    # redis_user_password: str

    @property
    def DATABASE_URL_asyncpg(self):
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # @property
    # def Redis_URL(self):
    #     return f"redis://redis:6380/0"

    auth_jwt: AuthJWT = AuthJWT()
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

r = redis.Redis(
    host="redis",
    port=6379,
)
