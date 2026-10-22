import asyncio
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import TypeAdapter
from redis.exceptions import ConnectionError
from sqlalchemy import event

from config import CacheSettings
from main import app
from src.cache.generations import get_generation
from src.cache.service import RELEASE, ResponseCache
from src.db.database import async_engine, async_session_factory
from src.db.models import User

ADAPTER = TypeAdapter(dict[str, str])


@pytest.fixture
async def cache():
    redis = FakeRedis(decode_responses=True)
    yield ResponseCache(redis, CacheSettings())
    await redis.aclose()


async def read(cache, loader, version="v1"):
    return await cache.get_or_load(
        "articles", {"id": 1}, ADAPTER, AsyncMock(return_value=version), loader
    )


async def test_hit_ttl_and_expiration(cache):
    loader = AsyncMock(return_value={"value": "fresh"})
    assert (await read(cache, loader))[1] == "MISS"
    key = cache.key("articles", "v1", {"id": 1})
    assert 53 <= await cache.redis.ttl(key) <= 66
    assert (await read(cache, loader))[1] == "HIT"
    assert loader.await_count == 1
    await cache.redis.pexpire(key, 1)
    await asyncio.sleep(0.02)
    assert (await read(cache, loader))[1] == "MISS"
    assert loader.await_count == 2


async def test_only_one_loader_across_workers(cache):
    other_worker = ResponseCache(cache.redis, CacheSettings(wait_seconds=1))

    async def load():
        await asyncio.sleep(0.08)
        return {"value": "fresh"}

    loader = AsyncMock(side_effect=load)
    results = await asyncio.gather(
        *[read(cache if i % 2 else other_worker, loader) for i in range(12)]
    )
    assert loader.await_count == 1
    assert [status for _, status in results].count("MISS") == 1
    assert all(value == {"value": "fresh"} for value, _ in results)


async def test_old_fill_cannot_poison_new_generation(cache):
    started, finish = asyncio.Event(), asyncio.Event()

    async def old_loader():
        started.set()
        await finish.wait()
        return {"value": "old"}

    old_read = asyncio.create_task(read(cache, old_loader, "before-write"))
    await started.wait()
    fresh = AsyncMock(return_value={"value": "new"})
    assert (await read(cache, fresh, "after-write"))[0] == {"value": "new"}
    finish.set()
    await old_read
    assert await read(cache, fresh, "after-write") == ({"value": "new"}, "HIT")
    assert fresh.await_count == 1


async def test_expired_lock_owner_cannot_publish_or_unlock_successor(cache):
    key = cache.key("articles", "v1", {"id": 1})

    async def loader():
        await cache.redis.set(key + ":lock", "new-owner", px=5000)
        return {"value": "old"}

    assert (await read(cache, loader))[1] == "BYPASS"
    assert await cache.redis.get(key) is None
    assert await cache.redis.get(key + ":lock") == "new-owner"
    assert await cache.redis.eval(RELEASE, 1, key + ":lock", "wrong-owner") == 0


async def test_busy_lock_wait_is_bounded(cache):
    cache.config.wait_seconds = 0.01
    await cache.redis.set(
        cache.key("articles", "v1", {"id": 1}) + ":lock", "other", ex=10
    )
    loader = AsyncMock(return_value={"value": "database"})
    async with asyncio.timeout(0.5):
        assert (await read(cache, loader))[1] == "BYPASS"
    assert loader.await_count == 1


@pytest.mark.parametrize("raw", ["not-json", '{"value": [1]}', '"unexpected"'])
async def test_corrupt_payload_is_repaired(cache, raw):
    key = cache.key("articles", "v1", {"id": 1})
    await cache.redis.set(key, raw, ex=30)
    loader = AsyncMock(return_value={"value": "repaired"})
    assert (await read(cache, loader))[0] == {"value": "repaired"}
    assert await read(cache, loader) == ({"value": "repaired"}, "HIT")


async def test_unavailable_redis_opens_circuit_without_failing_requests(
    cache, monkeypatch
):
    get = AsyncMock(side_effect=ConnectionError("internal secret"))
    monkeypatch.setattr(cache.redis, "get", get)
    loader = AsyncMock(return_value={"value": "db"})
    assert (await read(cache, loader))[1] == "BYPASS"
    assert (await read(cache, loader))[1] == "BYPASS"
    assert get.await_count == 1
    assert loader.await_count == 2


async def test_slow_redis_has_deadline(cache, monkeypatch):
    async def slow_get(*args):
        await asyncio.sleep(60)

    monkeypatch.setattr(cache.redis, "get", slow_get)
    cache.config.timeout_seconds = 0.01
    async with asyncio.timeout(0.5):
        assert (await read(cache, AsyncMock(return_value={"value": "db"})))[
            1
        ] == "BYPASS"


async def test_cache_write_failure_does_not_repeat_database_load(cache, monkeypatch):
    monkeypatch.setattr(cache.redis, "eval", AsyncMock(side_effect=ConnectionError()))
    loader = AsyncMock(return_value={"value": "db"})
    assert (await read(cache, loader))[1] == "BYPASS"
    assert loader.await_count == 1


async def test_disabled_cache_avoids_redis_and_generation_read(cache, monkeypatch):
    cache.config.enabled = False
    get = AsyncMock(side_effect=AssertionError("Redis should not be called"))
    monkeypatch.setattr(cache.redis, "get", get)
    version = AsyncMock(side_effect=AssertionError("DB generation should not be read"))
    assert await cache.get_or_load(
        "articles", {}, ADAPTER, version, AsyncMock(return_value={"value": "db"})
    ) == ({"value": "db"}, "BYPASS")


async def test_errors_and_oversized_results_not_cached(cache):
    bad_loader = AsyncMock(side_effect=ValueError("database failure"))
    with pytest.raises(ValueError, match="database failure"):
        await read(cache, bad_loader)
    assert not await cache.redis.keys("*")
    cache.config.max_value_bytes = 1024
    loader = AsyncMock(return_value={"value": "x" * 2048})
    assert (await read(cache, loader))[1] == "BYPASS"
    assert not await cache.redis.keys("*")


async def test_cancelled_fill_releases_lock(cache):
    started = asyncio.Event()

    async def loader():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(read(cache, loader))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await cache.redis.keys("*")


@pytest.mark.parametrize("resource", ["tags", "categories"])
async def test_catalog_cache_hits_invalidation_and_pagination(client, auth, resource):
    path = f"/api/v1/{resource}"
    assert (await client.get(path)).headers["x-cache"] == "MISS"
    assert (await client.get(path)).headers["x-cache"] == "HIT"
    item = (await client.post(path, json={"name": "First"}, headers=auth)).json()
    assert (await client.get(path)).headers["x-cache"] == "MISS"
    assert (await client.get(path + "?offset=0&limit=100")).headers["x-cache"] == "HIT"
    assert (await client.get(path + "?offset=1&limit=100")).json() == []
    detail = f"{path}/{item['id']}"
    assert (await client.get(detail)).headers["x-cache"] == "MISS"
    hit = await client.get(detail)
    assert hit.headers["x-cache"] == "HIT"
    assert hit.headers["cache-control"] == "no-store"
    await client.patch(detail, json={"name": "Changed"}, headers=auth)
    assert (await client.get(detail)).json()["name"] == "Changed"
    assert (await client.get(path)).json()[0]["name"] == "Changed"
    await client.delete(detail, headers=auth)
    assert (await client.get(detail)).status_code == 404
    assert (await client.get(path)).json() == []


async def make_article(client, auth):
    category = (
        await client.post("/api/v1/categories", json={"name": "Category"}, headers=auth)
    ).json()
    tag = (await client.post("/api/v1/tags", json={"name": "Tag"}, headers=auth)).json()
    article = (
        await client.post(
            "/api/v1/articles",
            json={
                "title": "Article",
                "content": "Body",
                "category_id": category["id"],
                "tag_ids": [tag["id"]],
            },
            headers=auth,
        )
    ).json()
    return category, tag, article


async def test_article_cache_invalidation_including_nested_catalog(client, auth):
    category, tag, article = await make_article(client, auth)
    path = f"/api/v1/articles/{article['id']}"
    for route in [path, "/api/v1/articles"]:
        assert (await client.get(route)).headers["x-cache"] == "MISS"
        assert (await client.get(route)).headers["x-cache"] == "HIT"
    await client.patch(
        f"/api/v1/tags/{tag['id']}", json={"name": "Updated tag"}, headers=auth
    )
    assert (await client.get(path)).json()["tag"][0]["name"] == "Updated tag"
    await client.patch(
        f"/api/v1/categories/{category['id']}",
        json={"name": "Updated category"},
        headers=auth,
    )
    assert (await client.get(path)).json()["category"]["name"] == "Updated category"
    assert (
        await client.delete(f"/api/v1/categories/{category['id']}", headers=auth)
    ).status_code == 409
    assert (await client.get(path)).headers["x-cache"] == "HIT"
    await client.delete(f"/api/v1/tags/{tag['id']}", headers=auth)
    assert (await client.get(path)).json()["tag"] == []
    await client.patch(path, json={"title": "New title"}, headers=auth)
    assert (await client.get(path)).json()["title"] == "New title"
    assert (await client.get("/api/v1/articles")).json()[0]["title"] == "New title"
    await client.delete(path, headers=auth)
    assert (await client.get(path)).status_code == 404
    assert (await client.get("/api/v1/articles")).json() == []


async def test_redis_outage_during_write_cannot_resurrect_stale_data(
    client, auth, monkeypatch
):
    item = (
        await client.post("/api/v1/tags", json={"name": "Before"}, headers=auth)
    ).json()
    path = f"/api/v1/tags/{item['id']}"
    assert (await client.get(path)).headers["x-cache"] == "MISS"
    async with async_session_factory() as session:
        old_version = await get_generation(session, "tags")
    old_key = app.state.cache.key("tags", old_version, {"id": item["id"]})
    original_get = app.state.redis.get
    with monkeypatch.context() as patch:
        patch.setattr(app.state.redis, "get", AsyncMock(side_effect=ConnectionError()))
        assert (await client.get(path)).headers["x-cache"] == "BYPASS"
        assert (
            await client.patch(path, json={"name": "After"}, headers=auth)
        ).status_code == 200
    assert "Before" in await original_get(old_key)
    # A separate/restarted worker has no circuit-breaker memory, yet is safe.
    app.state.cache = ResponseCache(app.state.redis, CacheSettings())
    response = await client.get(path)
    assert response.headers["x-cache"] == "MISS"
    assert response.json()["name"] == "After"


async def test_user_fields_not_cached_and_account_routes_bypass_cache(
    client, auth, account
):
    _, _, article = await make_article(client, auth)
    path = f"/api/v1/articles/{article['id']}"
    await client.get(path)
    for key in await app.state.redis.keys("*"):
        raw = await app.state.redis.get(key)
        assert "alice@example.com" not in raw
        assert '"username"' not in raw
        assert '"password"' not in raw
    async with async_session_factory() as session:
        user = await session.get(User, account[0]["id"])
        user.email = "updated@example.com"
        await session.commit()
    response = await client.get(path)
    assert response.headers["x-cache"] == "HIT"
    assert response.json()["user"][0]["email"] == "updated@example.com"
    for route in [
        "/api/v1/users",
        f"/api/v1/users/{account[0]['id']}",
        "/api/v1/jwt/users/me",
        "/health/db",
    ]:
        assert "x-cache" not in (await client.get(route, headers=auth)).headers


async def test_cache_hit_skips_article_relationship_queries(client, auth):
    _, _, article = await make_article(client, auth)
    path = f"/api/v1/articles/{article['id']}"
    await client.get(path)
    statements = []

    def collect(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(async_engine.sync_engine, "before_cursor_execute", collect)
    try:
        assert (await client.get(path)).headers["x-cache"] == "HIT"
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", collect)
    assert len(statements) == 2  # One generation + fresh author attributes.
    assert not any(
        "from articles" in sql or "join articles" in sql for sql in statements
    )


async def test_metrics_have_bounded_labels(client):
    await client.get("/api/v1/tags")
    await client.get("/api/v1/tags")
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert 'blog_cache_requests_total{result="HIT",scope="tags"} 1.0' in metrics.text
    assert 'blog_cache_requests_total{result="MISS",scope="tags"} 1.0' in metrics.text
    assert "alice" not in metrics.text
