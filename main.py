from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from config import settings
from src.api_v1.routers import router as main_router
from src.api_v1.routers.health_router import router as health_router
from src.auth.utils import validate_jwt_keys
from src.cache.service import ResponseCache
from src.db.database import async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_jwt_keys()
    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        max_connections=settings.cache.max_connections,
        retry=Retry(NoBackoff(), 0),
    )
    app.state.cache = ResponseCache(app.state.redis, settings.cache)
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
    expose_headers=["X-Cache"],
)
app.include_router(main_router)
app.include_router(health_router)


@app.get("/")
async def root():
    return {"info": "journalblog"}


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    return Response(request.app.state.cache.metrics(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=4000)
