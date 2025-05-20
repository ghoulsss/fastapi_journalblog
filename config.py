from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class AuthJWT(BaseModel):
    private_key_path: Path = BASE_DIR / "certs" / "jwt-private.pem"
    public_key_path: Path = BASE_DIR / "certs" / "jwt-public.pem"
    algorithm: str = "RS256"
    access_token_expired_minutes: int = 15
    refresh_token_expired_days: int = 30
    
    
class Settings(BaseSettings):
    postgres_db_host: str
    postgres_db_port: int
    postgres_db_user: str
    postgres_db_password: str
    postgres_db_name: str

    @property
    def DATABASE_URL_asyncpg(self):
        return f"postgresql+asyncpg://{self.postgres_db_user}:{self.postgres_db_password}@{self.postgres_db_host}:{self.postgres_db_port}/{self.postgres_db_name}"
    
    auth_jwt: AuthJWT = AuthJWT()
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="POSTGRES_DB_",
    )


settings = Settings()
