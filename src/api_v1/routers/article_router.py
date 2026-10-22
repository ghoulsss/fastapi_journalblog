from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api_v1.schemas.article_schema import (
    ArticleCreateSchema,
    ArticleSchema,
    ArticleUpdateSchema,
)
from src.db.database import get_async_session
from src.db.models import Article, Category, Tag, User
from src.db.transactions import commit_or_conflict
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/articles", tags=["Посты"])


def article_query():
    return select(Article).options(
        selectinload(Article.tag),
        selectinload(Article.user),
        selectinload(Article.category),
    )


async def find_article(session: AsyncSession, article_id: int) -> Article:
    article = await session.scalar(article_query().where(Article.id == article_id))
    if article is None:
        raise HTTPException(404, "Пост не найден")
    return article


async def find_category(session: AsyncSession, category_id: int) -> Category:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    return category


async def find_tags(session: AsyncSession, tag_ids: list[int]) -> list[Tag]:
    ids = set(tag_ids)
    tags = list(
        await session.scalars(select(Tag).where(Tag.id.in_(ids)).order_by(Tag.id))
    )
    if len(tags) != len(ids):
        raise HTTPException(400, "Some tags not found")
    return tags


def require_owner(article: Article, user: User) -> None:
    if all(author.id != user.id for author in article.user):
        raise HTTPException(403, "Only an article's author can change it")


@router.post(
    "", response_model=ArticleSchema, status_code=201, summary="Создание поста"
)
async def create_article(
    article_data: ArticleCreateSchema,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_auth_user),
):
    category = await find_category(session, article_data.category_id)
    tags = await find_tags(session, article_data.tag_ids)
    article = Article(
        **article_data.model_dump(exclude={"tag_ids", "category_id"}),
        category=category,
        tag=tags,
        user=[user],
    )
    session.add(article)
    await commit_or_conflict(session, "Article references no longer exist")
    return article


@router.get("", response_model=list[ArticleSchema], summary="Получение всех постов")
async def get_all_articles(
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return (
        await session.scalars(
            article_query().order_by(Article.id).offset(offset).limit(limit)
        )
    ).all()


@router.get(
    "/{article_id}", response_model=ArticleSchema, summary="Получение одного поста"
)
async def get_article(
    article_id: int, session: AsyncSession = Depends(get_async_session)
):
    return await find_article(session, article_id)


@router.patch("/{article_id}", response_model=ArticleSchema, summary="Изменение поста")
async def update_article(
    article_id: int,
    article_data: ArticleUpdateSchema,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_auth_user),
):
    article = await find_article(session, article_id)
    require_owner(article, user)
    data = article_data.model_dump(exclude_unset=True)
    # Validate all references before mutating the ORM instance (autoflush may run).
    category = (
        await find_category(session, data["category_id"])
        if "category_id" in data
        else None
    )
    tags = await find_tags(session, data["tag_ids"]) if "tag_ids" in data else None
    if category is not None:
        article.category = category
    if tags is not None:
        article.tag = tags
    for field, value in data.items():
        if field not in {"category_id", "tag_ids"}:
            setattr(article, field, value)
    await commit_or_conflict(session, "Article references no longer exist")
    return article


@router.delete("/{article_id}", summary="Удаление поста")
async def delete_article(
    article_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_active_auth_user),
):
    article = await find_article(session, article_id)
    require_owner(article, user)
    await session.delete(article)
    await session.commit()
    return {"success_delete": True}
