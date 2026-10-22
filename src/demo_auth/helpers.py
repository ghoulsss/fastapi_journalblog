from datetime import timedelta

from config import settings
from src.api_v1.schemas.user_schema import UserSchema
from src.auth import utils as auth_utils

TOKEN_TYPE_FIELD = "type"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_jwt(
    token_type: str,
    token_data: dict,
    expire_minute: int | None = None,
    expired_timedelta: timedelta | None = None,
) -> str:
    jwt_payload = {**token_data, "type": token_type}
    return auth_utils.encode_jwt(
        payload=jwt_payload,
        expired_minutes=expire_minute,
        expired_timedelta=expired_timedelta,
    )


def create_access_token(user: UserSchema) -> str:
    jwt_payload = {
        "sub": str(user.id),
        "username": user.username,
        "email": user.email,
    }
    return create_jwt(
        token_type=ACCESS_TOKEN_TYPE,
        token_data=jwt_payload,
        expire_minute=settings.auth_jwt.access_token_expired_minutes,
    )


def create_refresh_token(user: UserSchema) -> str:
    jwt_payload = {
        "sub": str(user.id),
    }
    return create_jwt(
        token_type=REFRESH_TOKEN_TYPE,
        token_data=jwt_payload,
        expired_timedelta=timedelta(days=settings.auth_jwt.refresh_token_expired_days),
    )
