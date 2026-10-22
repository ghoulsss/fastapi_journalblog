from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User


async def get_user_by_username(username: str, session: AsyncSession) -> User | None:
    return await session.scalar(select(User).where(User.username == username))
