from sqlmodel import SQLModel, Session, select
from src.constants import RSS_FEEDS
from src.core.logging import LogContext
from src.db.database import engine, DatabaseConnectionError
from src.models.db_models import Sources, Feeds

logger = LogContext(__name__)


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
    # Check if any sources exist
    if not session.exec(select(Sources)).all():
        for provider, config in RSS_FEEDS.items():
            # Create source with name as primary key
            source = Sources(
                name=provider,
                feed_symbol=config["feed_symbol"],
                display_name=config["display_name"],
                base_url=f"https://{config['base_url']}",
                fetch_interval=300,
            )
            session.add(source)
            session.commit()
            # Create feeds with composite primary key
            feeds = []
            for feed_name, feed_config in config["feeds"].items():
                feed = Feeds(
                    source_name=provider,  # Use the source name directly
                    name=feed_name,
                    feed_url=feed_config["path"],
                    display_name=feed_config["display_name"],
                )
                feeds.append(feed)
            session.add_all(feeds)
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
        logger.error(
            "Database initialization failed",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise


def fetch_feed_urls(session: Session):
    """Fetch all feed URLs from the database"""
    return session.exec(select(Feeds, Sources).join(Sources)).all()
