from sqlmodel import SQLModel, Session, select
from src.constants import RSS_FEEDS
from src.db.database import engine
from src.models.db_models import Sources, Categories
import logging

logger = logging.getLogger(__name__)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def seed_sources(session: Session):
    if not session.exec(select(Sources)).all():
        logger.info("Seeding sources")
        for provider, config in RSS_FEEDS.items():
            source = Sources(
                name=provider,
                feed_symbol=config["feed_symbol"],
                base_url=f"https://{config['base_url']}",
                fetch_interval=300,
            )
            session.add(source)
            session.commit()

            categories = [
                Categories(name=category_name, source_id=source.id, feed_url=feed_path)
                for category_name, feed_path in config["feeds"].items()
            ]
            session.add_all(categories)
            session.commit()
    else:
        logger.info(f"Sources already detected, {session.exec(select(Sources))}")


def initialize_db():
    create_db_and_tables()
    with Session(engine) as session:
        seed_sources(session)


def fetch_feed_urls(session: Session):
    return session.exec(select(Categories, Sources).join(Sources)).all()
