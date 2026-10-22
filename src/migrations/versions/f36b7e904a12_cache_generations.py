"""Transactional generations for public response caches."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "f36b7e904a12"
down_revision = "c84e91a03f2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "cache_generations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("generation", sa.String(32), nullable=False),
    )
    op.bulk_insert(
        table,
        [
            {"id": scope, "generation": uuid4().hex}
            for scope in ("articles", "categories", "tags")
        ],
    )


def downgrade() -> None:
    op.drop_table("cache_generations")
