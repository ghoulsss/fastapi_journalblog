import os
from pathlib import Path
from unittest.mock import AsyncMock

# Configure the application before its first import. No developer database is used.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:1/0"

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from config import settings
from main import app
from src.db.database import Base, async_engine


@pytest.fixture(scope="session", autouse=True)
def jwt_keys(tmp_path_factory):
    directory = tmp_path_factory.mktemp("jwt")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = directory / "private.pem"
    public_path = directory / "public.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    original = settings.auth_jwt.model_copy()
    settings.auth_jwt.private_key_path = Path(private_path)
    settings.auth_jwt.public_key_path = Path(public_path)
    yield
    settings.auth_jwt = original


@pytest.fixture
async def client():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with app.router.lifespan_context(app):
        original_redis = app.state.redis
        app.state.redis = AsyncMock()
        app.state.redis.ping.return_value = True
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
        app.state.redis = original_redis
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)


async def register_and_login(client, username="alice"):
    response = await client.post(
        "/api/v1/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201, response.text
    user = response.json()
    login = await client.post(
        "/api/v1/jwt/login", data={"username": username, "password": "password123"}
    )
    assert login.status_code == 200, login.text
    return user, login.json()


@pytest.fixture
async def account(client):
    return await register_and_login(client)


@pytest.fixture
async def auth(account):
    return {"Authorization": f"Bearer {account[1]['access_token']}"}
