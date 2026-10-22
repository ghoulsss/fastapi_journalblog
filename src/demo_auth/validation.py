from fastapi import Depends, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import utils as auth_utils
from src.db.database import get_async_session
from src.db.models import User
from src.demo_auth.crud import get_user_by_username
from src.demo_auth.helpers import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TOKEN_TYPE_FIELD,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/jwt/login")


def unauthorized(detail: str = "Invalid credentials") -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return auth_utils.decode_jwt(token)
    except InvalidTokenError:
        raise unauthorized("Invalid or expired token") from None


def validate_token_type(payload: dict, token_type: str) -> None:
    if payload.get(TOKEN_TYPE_FIELD) != token_type:
        raise unauthorized("Invalid token type")


async def get_user_by_token_sub(payload: dict, session: AsyncSession) -> User:
    subject = payload.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
        or len(subject) > 19
    ):
        raise unauthorized()
    user_id = int(subject)
    if not 0 < user_id <= 9223372036854775807:
        raise unauthorized()
    user = await session.get(User, user_id)
    if user is None:
        raise unauthorized()
    if not user.active:
        raise HTTPException(403, "User inactive")
    return user


def get_auth_user_from_token_of_type(token_type: str):
    async def get_auth_user_from_token(
        payload: dict = Depends(get_current_token_payload),
        session: AsyncSession = Depends(get_async_session),
    ) -> User:
        validate_token_type(payload, token_type)
        return await get_user_by_token_sub(payload, session)

    return get_auth_user_from_token


get_current_active_auth_user = get_auth_user_from_token_of_type(ACCESS_TOKEN_TYPE)
get_current_auth_user = get_current_active_auth_user
get_current_auth_user_for_refresh = get_auth_user_from_token_of_type(REFRESH_TOKEN_TYPE)


async def validate_auth_user(
    username: str = Form(),
    password: str = Form(),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    user = await get_user_by_username(username, session)
    if user is None or not await run_in_threadpool(
        auth_utils.validate_password, password, user.password
    ):
        raise unauthorized("Invalid username or password")
    if not user.active:
        raise HTTPException(403, "User inactive")
    return user
