from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_v1.schemas.category_schema import CategoryCreateSchema, CategorySchema
from src.cache.dependencies import cache_headers, get_response_cache
from src.cache.generations import get_generation
from src.cache.service import ResponseCache
from src.db.database import get_async_session
from src.db.models import Category
from src.db.transactions import commit_or_conflict
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/categories", tags=["Категории"])
write_auth = [Depends(get_current_active_auth_user)]
item_adapter = TypeAdapter(CategorySchema)
list_adapter = TypeAdapter(list[CategorySchema])


@router.post(
    "", response_model=CategorySchema, status_code=201, dependencies=write_auth
)
async def create_category(
    data: CategoryCreateSchema, session: AsyncSession = Depends(get_async_session)
):
    item = Category(**data.model_dump())
    session.add(item)
    await commit_or_conflict(
        session, "Category already exists", cache_scopes=("categories", "articles")
    )
    return item


@router.get("", response_model=list[CategorySchema])
async def get_all_categories(
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cache: ResponseCache = Depends(get_response_cache),
):
    async def load():
        items = (
            await session.scalars(
                select(Category).order_by(Category.id).offset(offset).limit(limit)
            )
        ).all()
        return list_adapter.validate_python(items)

    result, status = await cache.get_or_load(
        "categories",
        {"offset": offset, "limit": limit},
        list_adapter,
        lambda: get_generation(session, "categories"),
        load,
    )
    cache_headers(response, status)
    return result


async def find_category(session: AsyncSession, item_id: int) -> Category:
    item = await session.get(Category, item_id)
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


@router.get("/{category_id}", response_model=CategorySchema)
async def get_category(
    category_id: int,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    cache: ResponseCache = Depends(get_response_cache),
):
    async def load():
        return item_adapter.validate_python(await find_category(session, category_id))

    result, status = await cache.get_or_load(
        "categories",
        {"id": category_id},
        item_adapter,
        lambda: get_generation(session, "categories"),
        load,
    )
    cache_headers(response, status)
    return result


@router.patch("/{category_id}", response_model=CategorySchema, dependencies=write_auth)
async def update_category(
    category_id: int,
    data: CategoryCreateSchema,
    session: AsyncSession = Depends(get_async_session),
):
    item = await find_category(session, category_id)
    item.name = data.name
    await commit_or_conflict(
        session, "Category already exists", cache_scopes=("categories", "articles")
    )
    return item


@router.delete("/{category_id}", dependencies=write_auth)
async def delete_category(
    category_id: int, session: AsyncSession = Depends(get_async_session)
):
    item = await find_category(session, category_id)
    await session.delete(item)
    await commit_or_conflict(
        session,
        "Category is still used by articles",
        cache_scopes=("categories", "articles"),
    )
    return {"success_delete": True}
