import factory
import factory.fuzzy
from datetime import datetime, timezone
from sqlmodel import Session

from src.models.db_models import (
    ArticleContent,
    Articles,
    Categories,
    Sources,
    Users,
    FeedPreferences,
    ArticleCategories,
)
from src.auth.security import get_password_hash

TEST_TIMESTAMP = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


class BaseFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        abstract = True
        sqlalchemy_session_persistence = "flush"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        session = cls._meta.sqlalchemy_session
        if session is None:
            raise ValueError(
                "SQLAlchemy session not set. Call set_factory_session first"
            )
        obj = model_class(**kwargs)
        session.add(obj)
        session.flush()
        session.refresh(obj)
        return obj

    @classmethod
    def create(cls, **kwargs):
        obj = super().create(**kwargs)
        cls._meta.sqlalchemy_session.commit()
        return obj


class UserFactory(BaseFactory):
    class Meta:
        model = Users
        sqlalchemy_session = None

    username = factory.Sequence(lambda n: f"user{n}")
    password_hash = factory.LazyFunction(lambda: get_password_hash("password"))
    is_active = True
    created_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    last_login = factory.LazyFunction(lambda: TEST_TIMESTAMP)

    @classmethod
    def with_password(cls, password: str, **kwargs) -> Users:
        kwargs["password_hash"] = get_password_hash(password)
        return cls.create(**kwargs)


class SourceFactory(BaseFactory):
    class Meta:
        model = Sources
        sqlalchemy_session = None

    name = factory.Sequence(lambda n: f"Source {n}")
    feed_symbol = factory.Sequence(lambda n: f"src{n}")
    base_url = factory.Sequence(lambda n: f"https://source{n}.example.com")
    fetch_interval = 3600
    active_status = True
    created_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    updated_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    last_fetch_time = factory.LazyFunction(lambda: TEST_TIMESTAMP)


class CategoryFactory(BaseFactory):
    class Meta:
        model = Categories
        sqlalchemy_session = None

    name = factory.Sequence(lambda n: f"Category {n}")
    feed_url = factory.Sequence(lambda n: f"https://example.com/feed{n}.xml")
    created_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    updated_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)

    source = factory.SubFactory(SourceFactory)


class ArticleFactory(BaseFactory):
    class Meta:
        model = Articles
        sqlalchemy_session = None

    title = factory.Faker("sentence")
    pub_date = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    pub_date_raw = factory.LazyAttribute(
        lambda o: o.pub_date.strftime("%a, %d %b %Y %H:%M:%S %z")
    )
    content_hash = factory.Sequence(lambda n: f"hash{n}")
    original_url = factory.Sequence(lambda n: f"https://example.com/article-{n}")
    created_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    updated_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)

    source = factory.SubFactory(SourceFactory)

    @factory.post_generation
    def categories(self, create, extracted, **kwargs):
        if not create or not extracted:
            return

        session = ArticleFactory._meta.sqlalchemy_session

        associations = [
            ArticleCategories(article_id=self.id, category_id=category.id)
            for category in extracted
        ]

        if associations:
            session.add_all(associations)
            session.flush()


class FeedPreferencesFactory(BaseFactory):
    class Meta:
        model = FeedPreferences
        sqlalchemy_session = None

    is_active = True
    created_at = factory.LazyFunction(lambda: TEST_TIMESTAMP)
    last_fetched = factory.LazyFunction(lambda: TEST_TIMESTAMP)

    user = factory.SubFactory(UserFactory)
    feed = factory.SubFactory(CategoryFactory)


class ArticleContentFactory(BaseFactory):
    class Meta:
        model = ArticleContent
        sqlalchemy_session = None

    content = factory.Faker("paragraph", nb_sentences=5)
    content_type = "text/html"
    last_updated = factory.LazyFunction(lambda: TEST_TIMESTAMP)

    article = factory.SubFactory(ArticleFactory)


def set_factory_session(session: Session) -> None:
    if not isinstance(session, Session):
        raise ValueError("Must provide a valid SQLModel Session")

    for factory_class in [
        UserFactory,
        SourceFactory,
        CategoryFactory,
        ArticleFactory,
        ArticleContentFactory,
        FeedPreferencesFactory,
    ]:
        factory_class._meta.sqlalchemy_session = session
