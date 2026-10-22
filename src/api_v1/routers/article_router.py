from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api_v1.schemas.article_schema import (
    ArticleCreateSchema,
    ArticleSchema,
    ArticleUpdateSchema,
    CachedArticleSchema,
)
from src.api_v1.schemas.user_schema import UserSchema
from src.cache.dependencies import cache_headers, get_response_cache
from src.cache.generations import get_generation
from src.cache.service import ResponseCache
from src.db.database import get_async_session
from src.db.models import Article, Category, Tag, User
from src.db.transactions import commit_or_conflict
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/articles", tags=["Посты"])
item_adapter = TypeAdapter(CachedArticleSchema)
list_adapter = TypeAdapter(list[CachedArticleSchema])


def cacheable_article(article: Article) -> CachedArticleSchema:
    return CachedArticleSchema(
        **ArticleSchema.model_validate(article).model_dump(exclude={"user"}),
        author_ids=[user.id for user in article.user],
    )


async def hydrate_authors(session: AsyncSession, items: list[CachedArticleSchema]):
    ids = {user_id for item in items for user_id in item.author_ids}
    users = (
        {
            user.id: UserSchema.model_validate(user)
            for user in await session.scalars(select(User).where(User.id.in_(ids)))
        }
        if ids
        else {}
    )
    return [
        ArticleSchema(
            **item.model_dump(exclude={"author_ids"}),
            user=[users[user_id] for user_id in item.author_ids if user_id in users],
        )
        for item in items
    ]


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
    await commit_or_conflict(
        session, "Article references no longer exist", cache_scopes=("articles",)
    )
    return article


@router.get("", response_model=list[ArticleSchema], summary="Получение всех постов")
async def get_all_articles(
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cache: ResponseCache = Depends(get_response_cache),
):
    async def load():
        articles = (
            await session.scalars(
                article_query().order_by(Article.id).offset(offset).limit(limit)
            )
        ).all()
        return [cacheable_article(article) for article in articles]

    result, status = await cache.get_or_load(
        "articles",
        {"offset": offset, "limit": limit},
        list_adapter,
        lambda: get_generation(session, "articles"),
        load,
    )
    cache_headers(response, status)
    return await hydrate_authors(session, result)


@router.get(
    "/{article_id}", response_model=ArticleSchema, summary="Получение одного поста"
)
async def get_article(
    article_id: int,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    cache: ResponseCache = Depends(get_response_cache),
):
    async def load():
        return cacheable_article(await find_article(session, article_id))

    result, status = await cache.get_or_load(
        "articles",
        {"id": article_id},
        item_adapter,
        lambda: get_generation(session, "articles"),
        load,
    )
    cache_headers(response, status)
    return (await hydrate_authors(session, [result]))[0]


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
    await commit_or_conflict(
        session, "Article references no longer exist", cache_scopes=("articles",)
    )
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
    await commit_or_conflict(
        session, "Article could not be deleted", cache_scopes=("articles",)
    )
    return {"success_delete": True}
