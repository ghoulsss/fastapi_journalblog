from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.generations import bump_generations


async def commit_or_conflict(
    session: AsyncSession, detail: str, *, cache_scopes: tuple[str, ...] = ()
) -> None:
    try:
        await bump_generations(session, cache_scopes)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=detail) from None
