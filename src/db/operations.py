from sqlmodel import SQLModel, Session, select
from src.constants import RSS_FEEDS
from src.db.database import engine, DatabaseConnectionError
from src.models.db_models import Sources, Categories
import logging

logger = logging.getLogger(__name__)


def create_db_and_tables():
    """
    Create all database tables
    """
    if engine is None:
        raise DatabaseConnectionError(
            "Cannot create tables: database engine not initialized"
        )
    SQLModel.metadata.create_all(engine)


def seed_sources(session: Session):
    """Seed initial data sources if not already present"""
    if not session.exec(select(Sources)).all():
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


def initialize_db():
    """
    initialize database, create tables, and seed data
    """
    if engine is None:
        raise DatabaseConnectionError(
            "Cannot initialize database: engine not available"
        )

    try:
        create_db_and_tables()
        with Session(engine) as session:
            seed_sources(session)

        logger.info("Database initialized successfully")
    except Exception as e:
        logger.critical(f"Database initialization failed: {str(e)}")
        raise


def fetch_feed_urls(session: Session):
    """Fetch all feed URLs from the database"""
    return session.exec(select(Categories, Sources).join(Sources)).all()
