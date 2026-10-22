"""Optional real Redis checks; always start an isolated server, never use user data.

REDIS_SERVER_BIN=/path/to/redis-server uv run pytest tests/test_redis_integration.py
"""

import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from config import CacheSettings
from main import app
from src.cache.generations import get_generation
from src.cache.service import ResponseCache
from src.db.database import async_session_factory

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_SERVER_BIN"),
    reason="Set REDIS_SERVER_BIN to test real Redis",
)


class RedisProcess:
    def __init__(self, directory):
        self.directory = directory
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.redis = Redis(
            host="127.0.0.1",
            port=self.port,
            decode_responses=True,
            socket_timeout=0.2,
            socket_connect_timeout=0.2,
            retry=Retry(NoBackoff(), 0),
        )
        self.process = None

    async def start(self):
        binary = str(Path(os.environ["REDIS_SERVER_BIN"]).resolve())
        self.process = subprocess.Popen(
            [
                binary,
                "--bind",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--dir",
                str(self.directory),
                "--save",
                "",
                "--appendonly",
                "no",
                "--logfile",
                str(self.directory / "redis.log"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if self.process.poll() is not None:
                raise AssertionError((self.directory / "redis.log").read_text())
            try:
                if await self.redis.ping():
                    return
            except (RedisError, OSError):
                pass
            await asyncio.sleep(0.02)
        raise AssertionError("Redis did not become ready")

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None


@pytest.fixture
async def redis_process(tmp_path):
    server = RedisProcess(tmp_path)
    try:
        await server.start()
        yield server
    finally:
        server.stop()
        await server.redis.aclose()


async def test_real_redis_lua_locks_ttl_and_concurrent_workers(redis_process):
    adapter = TypeAdapter(dict[str, str])
    config = CacheSettings(wait_seconds=1)
    workers = [ResponseCache(redis_process.redis, config) for _ in range(2)]
    calls = 0

    async def generation():
        return "generation1"

    async def loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"title": "Redis integration"}

    async def read(worker):
        return await worker.get_or_load(
            "articles", {"id": 1}, adapter, generation, loader
        )

    results = await asyncio.gather(*[read(workers[i % 2]) for i in range(12)])
    assert calls == 1
    assert [status for _, status in results].count("MISS") == 1
    assert [status for _, status in results].count("HIT") == 11
    key = workers[0].key("articles", "generation1", {"id": 1})
    assert 53 <= await redis_process.redis.ttl(key) <= 66
    assert await redis_process.redis.get(key + ":lock") is None
    await redis_process.redis.pexpire(key, 1)
    await asyncio.sleep(0.02)
    assert (await read(workers[1]))[1] == "MISS"
    assert calls == 2


async def test_real_redis_api_outage_restart_and_persisted_stale_data(
    client, auth, redis_process
):
    original_redis, original_cache = app.state.redis, app.state.cache
    app.state.redis = redis_process.redis
    app.state.cache = ResponseCache(redis_process.redis, CacheSettings())
    try:
        item = (
            await client.post(
                "/api/v1/categories", json={"name": "Before outage"}, headers=auth
            )
        ).json()
        path = f"/api/v1/categories/{item['id']}"
        assert (await client.get(path)).headers["x-cache"] == "MISS"
        assert (await client.get(path)).headers["x-cache"] == "HIT"
        async with async_session_factory() as session:
            generation = await get_generation(session, "categories")
        old_key = app.state.cache.key("categories", generation, {"id": item["id"]})
        # Deliberately save stale data to exercise a Redis restore as well as outage.
        await redis_process.redis.save()
        redis_process.stop()
        assert (await client.get(path)).headers["x-cache"] == "BYPASS"
        assert (
            await client.patch(path, json={"name": "After outage"}, headers=auth)
        ).status_code == 200
        await redis_process.start()
        assert "Before outage" in await redis_process.redis.get(old_key)
        app.state.cache = ResponseCache(redis_process.redis, CacheSettings())
        response = await client.get(path)
        assert response.headers["x-cache"] == "MISS"
        assert response.json()["name"] == "After outage"
        assert (await client.get(path)).headers["x-cache"] == "HIT"
    finally:
        app.state.redis, app.state.cache = original_redis, original_cache


async def test_real_redis_non_utf8_value_falls_back(redis_process):
    cache = ResponseCache(redis_process.redis, CacheSettings())
    await redis_process.redis.set(cache.key("tags", "v1", {"id": 1}), b"\xff", ex=10)

    async def version():
        return "v1"

    async def load():
        return {"name": "valid"}

    result = await cache.get_or_load(
        "tags", {"id": 1}, TypeAdapter(dict[str, str]), version, load
    )
    assert result == ({"name": "valid"}, "BYPASS")
