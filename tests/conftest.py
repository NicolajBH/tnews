import asyncio
import os
import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.main import app
from src.core.config import settings
from src.db.database import get_session
from src.clients.redis import RedisClient
from src.models.db_models import (
    Articles,
    Categories,
    Sources,
    Users,
    FeedPreferences,
    ArticleCategories,
    ArticleContent,
)
from src.auth.security import get_password_hash, create_access_token

# Set up test database
TEST_DATABASE_URL = settings.TEST_DATABASE_URL


@pytest.fixture(scope="session")
def test_engine():
    """Create a test database engine"""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})

    SQLModel.metadata.create_all(engine)

    yield engine

    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture
def db_session(test_engine):
    """Create a new database session for a test using transaction rollback"""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """Create a test client for the FastAPI app"""

    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides = {}


@pytest.fixture
def test_user(db_session):
    """Create a test user in the database"""
    hashed_password = get_password_hash("Testpassword1")
    user = Users(
        username="testuser",
        password_hash=hashed_password,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        last_login=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_token(test_user):
    """Create a test JWT token"""
    return {
        "access_token": create_access_token(data={"sub": test_user.username}),
        "token_type": "bearer",
    }


@pytest.fixture
def auth_client(client, test_token):
    """Create a test client with authentication headers"""
    client.headers = {"Authorization": f"Bearer {test_token['access_token']}"}
    return client


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client"""
    mock_client = MagicMock(spec=RedisClient)
    mock_client.pipeline_check_hashes.return_value = {}
    mock_client.pipeline_add_hashes.return_value = None
    return mock_client


@pytest.fixture
def test_source(db_session):
    """Create a test news source"""
    source = Sources(
        name="Test Source",
        feed_symbol="testsrc",
        base_url="https://test.com",
        fetch_interval=3600,
        active_status=True,
        last_fetch_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


@pytest.fixture
def test_category(db_session, test_source):
    """Create a test category"""
    category = Categories(
        name="Test Category",
        feed_url="https://test.com/feed.xml",
        source_id=test_source.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


@pytest.fixture
def test_articles(db_session, test_source, test_category):
    """Create test articles"""
    articles = []
    for i in range(5):
        pub_date = datetime.now(timezone.utc) - timedelta(hours=i)
        pub_date_str = pub_date.strftime("%a, %d %b %Y %H:%M:%S %z")

        article = Articles(
            title=f"Test Article {i}",
            pub_date=pub_date,
            pub_date_raw=pub_date_str,
            content_hash=f"hash{i}",
            source_id=test_source.id,
            original_url=f"https://test.com/article-{i}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Add category association
        db_session.add(article)
        db_session.commit()
        db_session.refresh(article)

        # Create category association
        assoc = ArticleCategories(article_id=article.id, category_id=test_category.id)
        db_session.add(assoc)

        articles.append(article)

    db_session.commit()
    return articles


@pytest.fixture
def user_feed_preference(db_session, test_user, test_category):
    """Create a feed preference for the test user"""
    pref = FeedPreferences(
        user_id=test_user.id,
        feed_id=test_category.id,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        last_fetched=datetime.now(timezone.utc),
    )
    db_session.add(pref)
    db_session.commit()
    db_session.refresh(pref)
    return pref


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing logging"""
    with patch("logging.getLogger") as mock_get_logger:
        logger = MagicMock()
        mock_get_logger.return_value = logger
        yield logger


# Event loop for async tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
