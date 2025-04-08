"""add_performance_indexes

Revision ID: 76dd46c400c5
Revises: ee3c2f74184f
Create Date: 2025-04-07 18:29:23.592709

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "76dd46c400c5"
down_revision: Union[str, None] = "ee3c2f74184f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    context = op.get_context()
    dialect_name = context.dialect.name
    conn = op.get_bind()

    if dialect_name == "sqlite":
        conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_articles_pub_date_id
                ON articles (pub_date DESC, id DESC)
                """
            )
        )

        conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_articlescategories_category_article
                ON articlecategories (category_id, article_id)
                """
            )
        )

        conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_feedpreferences_user_active_feed
                ON feedpreferences (user_id, is_active, feed_id)
                """
            )
        )

        conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_users_refresh_tokens
                ON users (refresh_tokens)
                WHERE refresh_tokens IS NOT NULL
                """
            )
        )

    else:
        try:
            op.create_index(
                "ix_articles_pub_date_id",
                "articles",
                [sa.text("pub_date DESC"), sa.text("id DESC")],
                unique=False,
            )
        except Exception as e:
            print(f"Index creation warning: {e}")

        try:
            op.create_index(
                "ix_articlescategories_category_article",
                "articlescategories",
                ["category_id", "article_id"],
                unique=False,
            )
        except Exception as e:
            print(f"Index creation warning: {e}")

        try:
            op.create_index(
                "ix_feedpreferences_user_active_feed",
                "feedpreferences",
                ["user_id", "is_active", "feed_id"],
                unique=False,
            )
        except Exception as e:
            print(f"Index creation warning: {e}")

        if dialect_name == "postgresql":
            try:
                op.create_index(
                    "ix_users_refresh_tokens",
                    "users",
                    ["refresh_tokens"],
                    unique=False,
                    postgresql_where=sa.text("refresh_tokens IS NOT NULL"),
                )
            except Exception as e:
                print(f"Index creation warning: {e}")
        else:
            try:
                op.create_index(
                    "ix_users_refresh_tokens", "users", ["refresh_tokens"], unique=False
                )
            except Exception as e:
                print(f"Index creation warning: {e}")


def downgrade() -> None:
    context = op.get_context()
    dialect_name = context.dialect.name

    if dialect_name == "sqlite":
        conn = op.get_bind()
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_articles_pub_date_id"))
        conn.execute(
            sa.text("DROP INDEX IF EXISTS ix_articlescategories_category_article")
        )
        conn.execute(
            sa.text("DROP INDEX IF EXISTS ix_feedpreferences_user_active_feed")
        )
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_users_refresh_tokens"))
    else:
        try:
            op.drop_index("ix_articles_pub_date_id", table_name="articles")
        except Exception as e:
            print(f"Index dropping warning: {e}")
        try:
            op.drop_index(
                "ix_articlescategories_category_article",
                table_name="articlecategories",
            )
        except Exception as e:
            print(f"Index dropping warning: {e}")
        try:
            op.drop_index(
                "ix_feedpreferences_user_active_feed", table_name="feedpreferences"
            )
        except Exception as e:
            print(f"Index dropping warning: {e}")
        try:
            op.drop_index("ix_users_refresh_tokens", table_name="users")
        except Exception as e:
            print(f"Index dropping warning: {e}")
