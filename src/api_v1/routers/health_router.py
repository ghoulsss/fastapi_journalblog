from asyncpg import PostgresError
from fastapi import APIRouter, Depends, HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session

router = APIRouter(prefix="/health", tags=["Health Check"])


@router.get("/redis")
async def check_redis(request: Request):
    try:
        if not await request.app.state.redis.ping():
            raise HTTPException(503, "Redis unavailable")
    except (RedisError, OSError):
        raise HTTPException(503, "Redis unavailable") from None
    return {"status": "success", "message": "Redis is working"}


@router.get("/db")
async def check_database(session: AsyncSession = Depends(get_async_session)):
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, PostgresError, OSError):
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "success"}
