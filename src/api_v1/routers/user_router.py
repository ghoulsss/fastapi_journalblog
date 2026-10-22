from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api_v1.schemas.article_schema import UserWithArticlesSchema
from src.api_v1.schemas.user_schema import UserSchema, UserSecretSchema
from src.auth.utils import hash_password
from src.db.database import get_async_session
from src.db.models import Article, User
from src.db.transactions import commit_or_conflict
from src.demo_auth.crud import get_user_by_username
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/users", tags=["Пользователи"])


@router.post(
    "", response_model=UserSchema, status_code=201, summary="Создание пользователя"
)
async def create_user(
    user: UserSecretSchema, session: AsyncSession = Depends(get_async_session)
):
    user_model = User(
        **user.model_dump(exclude={"password"}),
        password=await run_in_threadpool(hash_password, user.password),
    )
    session.add(user_model)
    await commit_or_conflict(session, "Username or email already exists")
    return user_model


@router.get("", response_model=list[UserSchema], summary="Получение всех пользователей")
async def get_all_users(
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return (
        await session.scalars(
            select(User).order_by(User.id).offset(offset).limit(limit)
        )
    ).all()


@router.get(
    "/by-username/{username}",
    response_model=UserSchema,
    summary="Поиск пользователя по имени",
)
async def get_user_by_name(
    username: str, session: AsyncSession = Depends(get_async_session)
):
    user = await get_user_by_username(username, session)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


@router.get(
    "/{user_id}", response_model=UserSchema, summary="Получение одного пользователя"
)
async def get_user(user_id: int, session: AsyncSession = Depends(get_async_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


@router.delete("/{user_id}", summary="Удаление пользователя")
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_auth_user),
):
    if user_id != current_user.id:
        raise HTTPException(403, "You can only delete your own account")
    # Keep articles owned: the author must delete or transfer them first.
    article_id = await session.scalar(
        select(Article.id).where(Article.user.any(User.id == user_id)).limit(1)
    )
    if article_id is not None:
        raise HTTPException(409, "Delete your articles before deleting your account")
    await session.delete(current_user)
    await session.commit()
    return {"success_delete": True}


@router.get(
    "/{user_id}/articles",
    response_model=UserWithArticlesSchema,
    summary="Получение пользователя и его постов",
)
async def get_user_with_articles(
    user_id: int, session: AsyncSession = Depends(get_async_session)
):
    user = await session.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.article).selectinload(Article.tag),
            selectinload(User.article).selectinload(Article.category),
            selectinload(User.article).selectinload(Article.user),
        )
    )
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user
