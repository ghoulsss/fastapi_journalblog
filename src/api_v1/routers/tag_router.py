from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_v1.schemas.tag_schema import TagCreateSchema, TagSchema
from src.db.database import get_async_session
from src.db.models import Tag
from src.db.transactions import commit_or_conflict
from src.demo_auth.validation import get_current_active_auth_user

router = APIRouter(prefix="/tags", tags=["Теги"])
write_auth = [Depends(get_current_active_auth_user)]


@router.post("", response_model=TagSchema, status_code=201, dependencies=write_auth)
async def create_tag(
    data: TagCreateSchema, session: AsyncSession = Depends(get_async_session)
):
    item = Tag(**data.model_dump())
    session.add(item)
    await commit_or_conflict(session, "Tag already exists")
    return item


@router.get("", response_model=list[TagSchema])
async def get_all_tags(
    session: AsyncSession = Depends(get_async_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return (
        await session.scalars(select(Tag).order_by(Tag.id).offset(offset).limit(limit))
    ).all()


async def find_tag(session: AsyncSession, item_id: int) -> Tag:
    item = await session.get(Tag, item_id)
    if item is None:
        raise HTTPException(404, "Tag not found")
    return item


@router.get("/{tag_id}", response_model=TagSchema)
async def get_tag(tag_id: int, session: AsyncSession = Depends(get_async_session)):
    return await find_tag(session, tag_id)


@router.patch("/{tag_id}", response_model=TagSchema, dependencies=write_auth)
async def update_tag(
    tag_id: int,
    data: TagCreateSchema,
    session: AsyncSession = Depends(get_async_session),
):
    item = await find_tag(session, tag_id)
    item.name = data.name
    await commit_or_conflict(session, "Tag already exists")
    return item


@router.delete("/{tag_id}", dependencies=write_auth)
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_async_session)):
    item = await find_tag(session, tag_id)
    await session.delete(item)
    await commit_or_conflict(session, "Tag is still used by articles")
    return {"success_delete": True}
