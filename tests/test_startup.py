"""Exercise the documented migration/startup flow over a real HTTP connection."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from config import settings

ROOT = Path(__file__).resolve().parents[1]


def test_uvicorn_with_migrated_database(tmp_path):
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}",
        "AUTH_JWT__PRIVATE_KEY_PATH": str(settings.auth_jwt.private_key_path),
        "AUTH_JWT__PUBLIC_KEY_PATH": str(settings.auth_jwt.public_key_path),
        "REDIS_URL": "redis://127.0.0.1:1/0",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    with socket.socket() as listener, (tmp_path / "uvicorn.log").open("w+") as log:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--fd",
                str(listener.fileno()),
            ],
            pass_fds=(listener.fileno(),),
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False
            ) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        if client.get("/").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(log.read())
                    time.sleep(0.05)
                else:
                    raise AssertionError("Uvicorn did not become ready")
                assert client.get("/health/db").status_code == 200
                assert client.get("/health/redis").status_code == 503
                assert client.get("/docs").status_code == 200
                response = client.post(
                    "/api/v1/users",
                    json={
                        "username": "smoke",
                        "email": "smoke@example.com",
                        "password": "password123",
                    },
                )
                assert response.status_code == 201, response.text
                login = client.post(
                    "/api/v1/jwt/login",
                    data={"username": "smoke", "password": "password123"},
                )
                assert login.status_code == 200, login.text
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
                category = client.post(
                    "/api/v1/categories", json={"name": "Smoke"}, headers=headers
                )
                assert category.status_code == 201, category.text
                article = client.post(
                    "/api/v1/articles",
                    json={
                        "title": "Smoke",
                        "content": "Migrated database works",
                        "category_id": category.json()["id"],
                    },
                    headers=headers,
                )
                assert article.status_code == 201, article.text
                assert (
                    client.get(f"/api/v1/articles/{article.json()['id']}").status_code
                    == 200
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
