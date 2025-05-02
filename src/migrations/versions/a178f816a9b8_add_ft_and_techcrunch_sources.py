"""add_ft_and_techcrunch_sources

Revision ID: a178f816a9b8
Revises: 86cb437a7895
Create Date: 2025-04-28 15:38:43.071708

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from src.constants import RSS_FEEDS
from src.models.db_models import Sources, Categories


# revision identifiers, used by Alembic.
revision: str = "a178f816a9b8"
down_revision: Union[str, None] = "86cb437a7895"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tc_config = RSS_FEEDS["techcrunch"]
    ft_config = RSS_FEEDS["financial_times"]

    sources_table = sqlmodel.SQLModel.metadata.tables["sources"]
    categories_table = sqlmodel.SQLModel.metadata.tables["categories"]

    op.bulk_insert(
        sources_table,
        [
            {
                "name": "techcrunch",
                "feed_symbol": tc_config["feed_symbol"],
                "base_url": tc_config["base_url"],
                "fetch_interval": 300,
            },
            {
                "name": "financial_times",
                "feed_symbol": ft_config["feed_symbol"],
                "base_url": ft_config["base_url"],
                "fetch_interval": 300,
            },
        ],
    )

    conn = op.get_bind()
    tc_source_id = conn.execute(
        sa.text("SELECT id FROM sources WHERE name = 'techcrunch'")
    ).scalar_one()
    ft_source_id = conn.execute(
        sa.text("SELECT id FROM sources WHERE name = 'financial_times'")
    ).scalar_one()

    op.bulk_insert(
        categories_table,
        [
            {
                "name": "latest",
                "feed_url": tc_config["feeds"]["latest"],
                "source_id": tc_source_id,
            },
            {
                "name": "latest",
                "feed_url": ft_config["feeds"]["latest"],
                "source_id": ft_source_id,
            },
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    tc_config = RSS_FEEDS["techcrunch"]
    ft_config = RSS_FEEDS["financial_times"]
    conn.execute(
        sa.text(
            "DELETE FROM categories WHERE feed_url = :tc_url OR feed_url = :ft_url"
        ),
        {
            "tc_url": tc_config["feeds"]["latest"],
            "ft_url": ft_config["feeds"]["latest"],
        },
    )
    conn.execute(
        sa.text("DELETE FROM sources WHERE name IN ('financial_times', 'techcrunch')")
    )
