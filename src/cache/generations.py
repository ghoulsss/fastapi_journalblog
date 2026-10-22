from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import CacheGeneration

SCOPES = frozenset({"articles", "categories", "tags"})


async def get_generation(session: AsyncSession, scope: str) -> str:
    generation = await session.scalar(
        select(CacheGeneration.generation).where(CacheGeneration.id == scope)
    )
    if generation is None:
        raise RuntimeError("Cache generations missing: run alembic upgrade head")
    return generation


async def bump_generations(session: AsyncSession, scopes: tuple[str, ...]) -> None:
    # Same transaction as the write. Fixed order prevents cross-scope deadlocks.
    for scope in sorted(set(scopes)):
        if scope not in SCOPES:
            raise ValueError(f"Unknown cache scope: {scope}")
        result = await session.execute(
            update(CacheGeneration)
            .where(CacheGeneration.id == scope)
            .values(generation=uuid4().hex)
        )
        if result.rowcount != 1:
            raise RuntimeError("Cache generations missing: run alembic upgrade head")
