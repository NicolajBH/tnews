"""fix_duplicate_index_and_refresh_token_name

Revision ID: 86cb437a7895
Revises: 76dd46c400c5
Create Date: 2025-04-08 18:16:12.993062

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "86cb437a7895"
down_revision: Union[str, None] = "76dd46c400c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # drop duplicate incorrect index
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_articlescategories_category_article"))

    # rename fresh tokens column
    conn.execute(
        sa.text(
            """
        CREATE TABLE users_new (
        id INTEGER NOT NULL,
        username VARCHAR NOT NULL,
        created_at DATETIME NOT NULL,
        last_login DATETIME NOT NULL,
        password_hash VARCHAR NOT NULL,
        is_active BOOLEAN NOT NULL, 
        refresh_token_expires DATETIME, 
        refresh_token VARCHAR,
        PRIMARY KEY (id),
        UNIQUE (username)
        )
        """
        )
    )

    conn.execute(
        sa.text(
            """
        INSERT INTO users_new
        SELECT id, username, created_at, last_login, password_hash, is_active, refresh_token_expires, refresh_tokens
        FROM users
        """
        )
    )

    conn.execute(sa.text("DROP TABLE users"))
    conn.execute(sa.text("ALTER TABLE users_new RENAME TO users"))

    conn.execute(sa.text("CREATE INDEX ix_users_id ON users (id)"))
    conn.execute(
        sa.text("CREATE INDEX ix_users_password_hash ON users (password_hash)")
    )
    conn.execute(
        sa.text(
            """
        CREATE INDEX IF NOT EXISTS ix_users_refresh_token
        ON users (refresh_token)
        WHERE refresh_token IS NOT NULL
        """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # restore index with extra s
    conn.execute(
        sa.text(
            """
        CREATE INDEX IF NOT EXISTS ix_articlescategories_category_article
        ON articlecategories (category_id, article_id)
        """
        )
    )

    # rename refresh token back to refresh tokens
    conn.execute(
        sa.text(
            """
        CREATE TABLE users_new (
        id INTEGER NOT NULL,
        username VARCHAR NOT NULL,
        created_at DATETIME NOT NULL,
        last_login DATETIME NOT NULL,
        password_hash VARCHAR NOT NULL,
        is_active BOOLEAN NOT NULL, 
        refresh_token_expires DATETIME, 
        refresh_tokens VARCHAR,
        PRIMARY KEY (id),
        UNIQUE (username)
        )
        """
        )
    )

    conn.execute(
        sa.text(
            """
        INSERT INTO users_new
        SELECT id, username, created_at, last_login, password_hash, is_active, refresh_token_expires, refresh_token
        FROM users
        """
        )
    )

    conn.execute(sa.text("DROP TABLE users"))
    conn.execute(sa.text("ALTER TABLE users_new RENAME TO users"))

    conn.execute(sa.text("CREATE INDEX ix_users_id ON users (id)"))
    conn.execute(
        sa.text("CREATE INDEX ix_users_password_hash ON users (password_hash)")
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
