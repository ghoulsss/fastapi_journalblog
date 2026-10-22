import asyncio
import hashlib
import json
import logging
import random
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TypeVar
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config import CacheSettings

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Lock and value share a Redis Cluster hash slot. A timed-out owner must never
# publish or release another worker's lock. Leases are only load protection;
# database generations provide correctness independently of Redis locks.
PUBLISH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
    redis.call('DEL', KEYS[1])
    return 1
end
return 0
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class CacheUnavailable(Exception):
    pass


class ResponseCache:
    def __init__(self, redis: Redis, config: CacheSettings):
        self.redis = redis
        self.config = config
        self.unavailable_until = 0.0
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "blog_cache_requests_total",
            "Cache read results",
            ["scope", "result"],
            registry=self.registry,
        )
        self.events = Counter(
            "blog_cache_events_total",
            "Cache operational events",
            ["event"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "blog_cache_redis_seconds",
            "Redis operation latency",
            registry=self.registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
        )

    def metrics(self) -> bytes:
        return generate_latest(self.registry)

    def key(self, scope: str, generation: str, parameters: dict) -> str:
        digest = hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"{self.config.prefix}:{{{scope}:{generation}:{digest}}}:data"

    async def _redis(self, operation: Callable[[], Awaitable]):
        if monotonic() < self.unavailable_until:
            raise CacheUnavailable
        started = monotonic()
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                return await operation()
        except (RedisError, OSError, TimeoutError, UnicodeError):
            if monotonic() >= self.unavailable_until:
                logger.warning("Redis cache unavailable; using database temporarily")
            self.unavailable_until = monotonic() + self.config.retry_seconds
            self.events.labels("redis_error").inc()
            raise CacheUnavailable from None
        finally:
            self.latency.observe(monotonic() - started)

    async def _read(self, key: str, adapter: TypeAdapter[T]) -> T | None:
        raw = await self._redis(lambda: self.redis.get(key))
        if raw is None:
            return None
        try:
            if len(raw) > self.config.max_value_bytes:
                raise ValueError("Cache payload too large")
            return adapter.validate_json(raw)
        except (ValidationError, ValueError):
            self.events.labels("invalid_payload").inc()
            return None

    async def get_or_load(
        self,
        scope: str,
        parameters: dict,
        adapter: TypeAdapter[T],
        generation: Callable[[], Awaitable[str]],
        loader: Callable[[], Awaitable[T]],
    ) -> tuple[T, str]:
        if not self.config.enabled or monotonic() < self.unavailable_until:
            return self._result(scope, await loader(), "BYPASS")
        # This small primary-key read survives Redis outages and lost cache data.
        key = self.key(scope, await generation(), parameters)
        lock = key + ":lock"
        token = uuid4().hex
        try:
            cached = await self._read(key, adapter)
            if cached is not None:
                return self._result(scope, cached, "HIT")
            acquired = await self._redis(
                lambda: self.redis.set(
                    lock,
                    token,
                    nx=True,
                    px=self.config.lock_seconds * 1000,
                )
            )
            if not acquired:
                deadline = monotonic() + self.config.wait_seconds
                while monotonic() < deadline:
                    await asyncio.sleep(min(0.025, max(0, deadline - monotonic())))
                    cached = await self._read(key, adapter)
                    if cached is not None:
                        return self._result(scope, cached, "HIT")
                self.events.labels("lock_wait_timeout").inc()
                return self._result(scope, await loader(), "BYPASS")
        except CacheUnavailable:
            return self._result(scope, await loader(), "BYPASS")

        try:
            # A worker may have filled the value between GET and lock acquisition.
            try:
                cached = await self._read(key, adapter)
                if cached is not None:
                    return self._result(scope, cached, "HIT")
            except CacheUnavailable:
                return self._result(scope, await loader(), "BYPASS")
            value = await loader()  # Exceptions/404s are never cached.
            payload = adapter.dump_json(value)
            if len(payload) > self.config.max_value_bytes:
                self.events.labels("oversized_payload").inc()
                return self._result(scope, value, "BYPASS")
            base_ttl = (
                self.config.article_ttl
                if scope == "articles"
                else self.config.catalog_ttl
            )
            ttl = max(1, round(base_ttl * random.uniform(0.9, 1.1)))
            try:
                published = await self._redis(
                    lambda: self.redis.eval(
                        PUBLISH,
                        2,
                        lock,
                        key,
                        token,
                        payload,
                        ttl,
                    )
                )
            except CacheUnavailable:
                return self._result(scope, value, "BYPASS")
            if not published:
                self.events.labels("lock_expired").inc()
            return self._result(scope, value, "MISS" if published else "BYPASS")
        finally:
            try:
                await self._redis(lambda: self.redis.eval(RELEASE, 1, lock, token))
            except CacheUnavailable:
                pass  # The lease expires even if Redis is unavailable/cancelled.

    def _result(self, scope: str, value: T, status: str) -> tuple[T, str]:
        self.requests.labels(scope, status).inc()
        return value, status
