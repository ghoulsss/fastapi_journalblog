"""Create the current blog schema; retain legacy tables without deleting data.

Revision ID: c84e91a03f2b
Revises: fd642891166b
"""

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "c84e91a03f2b"
down_revision = "fd642891166b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old accounts have neither email nor active status. Do not silently orphan
    # production data or invent account details during an automatic upgrade.
    if not context.is_offline_mode():
        connection = op.get_bind()
        for name in ("article", "category", "tag", "user"):
            legacy = sa.table(name, sa.column("id"))
            if connection.execute(sa.select(legacy.c.id).limit(1)).first():
                raise RuntimeError(
                    "Legacy tables contain data. Back up the database and perform "
                    "an explicit data migration before upgrading to c84e91a03f2b. "
                    "See src/migrations/README. No legacy data has been deleted."
                )

    # PostgreSQL enum types already exist from the historical revisions.
    author_enum = sa.Enum("author", "not_author", name="checkauthor").with_variant(
        postgresql.ENUM("author", "not_author", name="checkauthor", create_type=False),
        "postgresql",
    )
    published_enum = sa.Enum(
        "published", "nonpublished", name="ispublished"
    ).with_variant(
        postgresql.ENUM(
            "published", "nonpublished", name="ispublished", create_type=False
        ),
        "postgresql",
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password", sa.LargeBinary(), nullable=False),
        sa.Column("is_author", author_enum, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sqlite_autoincrement=True,
    )
    for table in ("categorys", "tags"):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
        )
        op.create_index(f"ix_{table}_name", table, ["name"], unique=True)
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("is_published", published_enum, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categorys.id"), nullable=False
        ),
    )
    op.create_index("ix_articles_title", "articles", ["title"])
    op.create_table(
        "user_article_association",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False
        ),
        sa.UniqueConstraint("user_id", "article_id", name="idx_unique_user_article"),
    )
    op.create_table(
        "article_tag_association",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False
        ),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), nullable=False),
        sa.UniqueConstraint("article_id", "tag_id", name="idx_unique_article_tag"),
    )


def downgrade() -> None:
    op.drop_table("article_tag_association")
    op.drop_table("user_article_association")
    op.drop_index("ix_articles_title", table_name="articles")
    op.drop_table("articles")
    for table in ("tags", "categorys"):
        op.drop_index(f"ix_{table}_name", table_name=table)
        op.drop_table(table)
    op.drop_table("users")
