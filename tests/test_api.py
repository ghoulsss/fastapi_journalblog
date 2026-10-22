from datetime import timedelta
from unittest.mock import AsyncMock

import jwt
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError

from config import Settings
from main import app
from src.auth.utils import encode_jwt
from src.db.database import async_session_factory, get_async_session
from src.db.models import User
from tests.conftest import register_and_login

API = "/api/v1"


async def test_root_docs_and_removed_destructive_route(client):
    assert (await client.get("/")).json() == {"info": "journalblog"}
    assert (await client.get("/docs")).status_code == 200
    spec = (await client.get("/openapi.json")).json()
    assert (
        spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"][
            "password"
        ]["tokenUrl"]
        == API + "/jwt/login"
    )
    assert (await client.get("/db-recreate")).status_code == 404


async def test_registration_login_refresh(client, account):
    user, tokens = account
    assert "password" not in user
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get(API + "/jwt/users/me", headers=headers)).json()[
        "username"
    ] == "alice"
    refreshed = await client.post(
        API + "/jwt/refresh",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert "refresh_token" not in refreshed.json()
    assert (
        await client.get(
            API + "/jwt/users/me",
            headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
        )
    ).status_code == 200
    assert (await client.post(API + "/jwt/refresh", headers=headers)).status_code == 401
    assert (
        await client.get(
            API + "/jwt/users/me",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
    ).status_code == 401
    async with async_session_factory() as session:
        stored = await session.get(User, user["id"])
        assert stored.password != b"password123"


@pytest.mark.parametrize(
    "username,password",
    [("missing", "password123"), ("alice", "wrong"), ("alice", "x" * 73)],
)
async def test_invalid_login(client, account, username, password):
    response = await client.post(
        API + "/jwt/login", data={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "kind",
    [
        "expired",
        "malformed",
        "missing_sub",
        "wrong_algorithm",
        "deleted",
        "mismatched_username",
    ],
)
async def test_invalid_tokens(client, account, kind):
    if kind == "expired":
        token = encode_jwt(
            {"sub": "alice", "type": "access"}, expired_timedelta=timedelta(seconds=-10)
        )
    elif kind == "malformed":
        token = "broken-token"
    elif kind == "missing_sub":
        token = encode_jwt({"type": "access"})
    elif kind == "wrong_algorithm":
        token = jwt.encode(
            {"sub": "alice", "type": "access"}, "test-key-" * 8, algorithm="HS256"
        )
    else:
        token = encode_jwt({"sub": "absent", "username": "alice", "type": "access"})
    response = await client.get(
        API + "/jwt/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


async def test_inactive_account_cannot_use_or_refresh_tokens(client, account):
    user, tokens = account
    async with async_session_factory() as session:
        stored = await session.get(User, user["id"])
        stored.active = False
        await session.commit()
    for path, token_name, method in [
        ("/jwt/users/me", "access_token", client.get),
        ("/jwt/refresh", "refresh_token", client.post),
    ]:
        assert (
            await method(
                API + path, headers={"Authorization": f"Bearer {tokens[token_name]}"}
            )
        ).status_code == 403
    assert (
        await client.post(
            API + "/jwt/login", data={"username": "alice", "password": "password123"}
        )
    ).status_code == 403


async def test_duplicate_users_and_username_lookup(client, account):
    for username, email in [
        ("alice", "new@example.com"),
        ("other", "alice@example.com"),
    ]:
        response = await client.post(
            API + "/users",
            json={"username": username, "email": email, "password": "password123"},
        )
        assert response.status_code == 409
    response = await client.get(API + "/users/by-username/alice")
    assert response.json()["id"] == account[0]["id"]
    assert (await client.get(API + "/users/by-username/unknown")).status_code == 404
    assert "password" not in (await client.get(API + "/users")).text


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "short"},
        {"password": "я" * 37},
        {"username": " "},
        {"email": "invalid"},
        {"active": False},
        {"is_author": "author"},
    ],
)
async def test_invalid_registration(client, changes):
    data = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
        **changes,
    }
    assert (await client.post(API + "/users", json=data)).status_code == 422


@pytest.mark.parametrize("resource", ["users", "articles", "tags", "categories"])
@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=101"])
async def test_pagination_validation(client, resource, query):
    assert (await client.get(f"{API}/{resource}?{query}")).status_code == 422


@pytest.mark.parametrize("resource", ["tags", "categories"])
async def test_taxonomy_crud(client, auth, resource):
    path = f"{API}/{resource}"
    assert (await client.post(path, json={"name": "Python"})).status_code == 401
    response = await client.post(path, json={"name": " Python "}, headers=auth)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["name"] == "Python"
    assert (
        await client.post(path, json={"name": "Python"}, headers=auth)
    ).status_code == 409
    assert (
        await client.post(path, json={"name": "  "}, headers=auth)
    ).status_code == 422
    assert (await client.get(f"{path}/{item['id']}")).json() == item
    assert (await client.get(path)).json() == [item]
    assert (
        await client.patch(f"{path}/{item['id']}", json={"name": "New"}, headers=auth)
    ).json()["name"] == "New"
    assert (
        await client.delete(f"{path}/{item['id']}", headers=auth)
    ).status_code == 200
    assert (await client.get(f"{path}/{item['id']}")).status_code == 404
    assert (
        await client.delete(f"{path}/{item['id']}", headers=auth)
    ).status_code == 404


async def test_article_lifecycle_and_ownership(client, auth, account):
    category = (
        await client.post(API + "/categories", json={"name": "News"}, headers=auth)
    ).json()
    tag = (
        await client.post(API + "/tags", json={"name": "Python"}, headers=auth)
    ).json()
    data = {
        "title": "First",
        "content": "Text",
        "category_id": category["id"],
        "tag_ids": [tag["id"], tag["id"]],
    }
    assert (await client.post(API + "/articles", json=data)).status_code == 401
    assert (
        await client.post(
            API + "/articles", json={**data, "category_id": 9999}, headers=auth
        )
    ).status_code == 404
    assert (
        await client.post(
            API + "/articles", json={**data, "tag_ids": [9999]}, headers=auth
        )
    ).status_code == 400
    response = await client.post(API + "/articles", json=data, headers=auth)
    assert response.status_code == 201, response.text
    article = response.json()
    assert article["user"][0]["id"] == account[0]["id"]
    assert article["tag"] == [tag]
    assert article["created_at"]
    path = f"{API}/articles/{article['id']}"
    assert (await client.get(path)).json() == article
    assert (await client.get(API + "/articles")).json() == [article]
    assert (await client.get(f"{API}/users/{account[0]['id']}/articles")).json()[
        "article"
    ] == [article]
    assert (
        await client.delete(f"{API}/categories/{category['id']}", headers=auth)
    ).status_code == 409
    assert (
        await client.delete(f"{API}/users/{account[0]['id']}", headers=auth)
    ).status_code == 409
    _, other_tokens = await register_and_login(client, "bob")
    other_auth = {"Authorization": f"Bearer {other_tokens['access_token']}"}
    assert (
        await client.patch(path, json={"title": "Stolen"}, headers=other_auth)
    ).status_code == 403
    assert (await client.delete(path, headers=other_auth)).status_code == 403
    assert (
        await client.delete(f"{API}/users/{account[0]['id']}", headers=other_auth)
    ).status_code == 403
    assert (
        await client.patch(path, json={"title": None}, headers=auth)
    ).status_code == 422
    assert (
        await client.patch(
            path, json={"title": "Not saved", "tag_ids": [9999]}, headers=auth
        )
    ).status_code == 400
    assert (await client.get(path)).json()["title"] == "First"
    updated = await client.patch(
        path,
        json={"title": "Updated", "is_published": "published", "tag_ids": []},
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tag"] == []
    assert updated.json()["is_published"] == "published"
    assert (await client.delete(path, headers=auth)).status_code == 200
    assert (await client.get(path)).status_code == 404
    assert (
        await client.delete(f"{API}/categories/{category['id']}", headers=auth)
    ).status_code == 200
    assert (
        await client.delete(f"{API}/users/{account[0]['id']}", headers=auth)
    ).status_code == 200
    assert (await client.get(API + "/jwt/users/me", headers=auth)).status_code == 401


async def test_removing_tag_from_existing_article(client, auth):
    category = (
        await client.post(API + "/categories", json={"name": "News"}, headers=auth)
    ).json()
    tag = (
        await client.post(API + "/tags", json={"name": "Python"}, headers=auth)
    ).json()
    article = (
        await client.post(
            API + "/articles",
            json={
                "title": "Title",
                "content": "Text",
                "category_id": category["id"],
                "tag_ids": [tag["id"]],
            },
            headers=auth,
        )
    ).json()
    assert (
        await client.delete(f"{API}/tags/{tag['id']}", headers=auth)
    ).status_code == 200
    assert (await client.get(f"{API}/articles/{article['id']}")).json()["tag"] == []


async def test_health_checks(client):
    assert (await client.get("/health/db")).status_code == 200
    assert (await client.get("/health/redis")).status_code == 200
    app.state.redis.ping.side_effect = ConnectionError("sensitive internal details")
    response = await client.get("/health/redis")
    assert response.status_code == 503
    assert "sensitive" not in response.text
    broken_session = AsyncMock()
    broken_session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("secret")
    )
    app.dependency_overrides[get_async_session] = lambda: broken_session
    try:
        assert (await client.get("/health/db")).status_code == 503
    finally:
        app.dependency_overrides.clear()


async def test_cors_preflight(client):
    response = await client.options(
        API + "/articles",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_database_url_escapes_password():
    config = Settings(_env_file=None, database_url=None, postgres_password="p@ss:/?#%")
    from sqlalchemy.engine import make_url

    url = make_url(config.DATABASE_URL_asyncpg.render_as_string(hide_password=False))
    assert url.password == "p@ss:/?#%"


async def test_recreated_username_cannot_reuse_old_tokens(client, account, auth):
    user, tokens = account
    assert (
        await client.delete(f"{API}/users/{user['id']}", headers=auth)
    ).status_code == 200
    new_user, _ = await register_and_login(client)
    assert new_user["id"] != user["id"]
    assert (await client.get(API + "/jwt/users/me", headers=auth)).status_code == 401
    assert (
        await client.post(
            API + "/jwt/refresh",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
    ).status_code == 401


async def test_startup_explains_missing_keys(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings.auth_jwt, "private_key_path", tmp_path / "missing.pem")
    with pytest.raises(RuntimeError, match="generate_jwt_keys"):
        async with app.router.lifespan_context(app):
            pass
