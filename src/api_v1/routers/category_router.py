from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_v1.schemas.category_schema import CategoryCreateSchema, CategorySchema
from src.db.database import get_async_session
from src.db.models import Category
from src.db.transactions import commit_or_conflict
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/categories", tags=["Категории"])
write_auth = [Depends(get_current_active_auth_user)]


@router.post(
    "", response_model=CategorySchema, status_code=201, dependencies=write_auth
)
async def create_category(
    data: CategoryCreateSchema, session: AsyncSession = Depends(get_async_session)
):
    item = Category(**data.model_dump())
    session.add(item)
    await commit_or_conflict(session, "Category already exists")
    return item


@router.get("", response_model=list[CategorySchema])
async def get_all_categories(
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return (
        await session.scalars(
            select(Category).order_by(Category.id).offset(offset).limit(limit)
        )
    ).all()


async def find_category(session: AsyncSession, item_id: int) -> Category:
    item = await session.get(Category, item_id)
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


@router.get("/{category_id}", response_model=CategorySchema)
async def get_category(
    category_id: int, session: AsyncSession = Depends(get_async_session)
):
    return await find_category(session, category_id)


@router.patch("/{category_id}", response_model=CategorySchema, dependencies=write_auth)
async def update_category(
    category_id: int,
    data: CategoryCreateSchema,
    session: AsyncSession = Depends(get_async_session),
):
    item = await find_category(session, category_id)
    item.name = data.name
    await commit_or_conflict(session, "Category already exists")
    return item


@router.delete("/{category_id}", dependencies=write_auth)
async def delete_category(
    category_id: int, session: AsyncSession = Depends(get_async_session)
):
    item = await find_category(session, category_id)
    await session.delete(item)
    await commit_or_conflict(session, "Category is still used by articles")
    return {"success_delete": True}
