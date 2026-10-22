from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from config import settings
from src.api_v1.routers import router as main_router
from src.api_v1.routers.health_router import router as health_router
from src.auth.utils import validate_jwt_keys
from src.db.database import async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_jwt_keys()
    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await async_engine.dispose()


app = FastAPI(title="JournalBlog API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(main_router)
app.include_router(health_router)


@app.get("/")
async def root():
    return {"info": "journalblog"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=4000)
