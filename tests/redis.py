from fastapi import APIRouter, Depends, HTTPException
import redis
from fastapi.responses import JSONResponse
from config import settings

router = APIRouter(prefix="/health", tags=["Health Check"])


@router.get("/redis")
async def check_redis():
    try:
        r = redis.Redis(
            host="redis",
            port=6379,
        )

        # Проверка ping
        if not r.ping():
            raise Exception("Redis ping failed")

        # Проверка записи/чтения
        test_key = "healthcheck:test"
        r.set(test_key, "1", ex=10)
        if r.get(test_key) != "1":
            raise Exception("Redis read/write test failed")

        return {"status": "success", "message": "Redis is working"}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Redis health check failed: {str(e)}"
        )
