import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def migrate(database, *args, success=True):
    environment = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def test_migrations_match_models_and_roundtrip(tmp_path):
    database = tmp_path / "migrations.db"
    migrate(database, "upgrade", "head")
    migrate(database, "check")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "users",
            "articles",
            "tags",
            "categorys",
            "user_article_association",
            "article_tag_association",
        } <= tables
    migrate(database, "downgrade", "fd642891166b")
    migrate(database, "upgrade", "head")
    migrate(database, "check")
    migrate(database, "downgrade", "base")


def test_legacy_data_is_not_silently_discarded(tmp_path):
    database = tmp_path / "legacy.db"
    migrate(database, "upgrade", "fd642891166b")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO category (id, name) VALUES (1, 'Keep me')")
    result = migrate(database, "upgrade", "head", success=False)
    assert "Legacy tables contain data" in result.stderr
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT name FROM category").fetchone()[0] == "Keep me"
        )
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "fd642891166b"
        )
