import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import datetime

from src.clients.news import NewsClient
from src.core.exceptions import RSSFeedError
from src.models.db_models import Articles, Categories
from tests.factories import (
    SourceFactory,
    CategoryFactory,
    ArticleFactory,
    set_factory_session,
)


@pytest.fixture
def mock_http_response():
    headers = MagicMock()
    headers.headers = {
        "Content-Type": "application/xml",
        "Content-Encoding": "",
    }
    return (
        headers,
        b"<rss><channel><item><title>Test Article</title></item></channel></rss>",
    )


@pytest.fixture
def mock_parser():
    parser = AsyncMock()
    parser.parse_content.return_value = [
        Articles(
            title="Test Article 1",
            pub_date=datetime.datetime.now(),
            pub_date_raw="Wed, 01 Mar 2025 13:00:00 +0000",
            content_hash="hash1",
            original_url="https://example.com/test-article-1",
            source_id=1,
        ),
        Articles(
            title="Test Article 2",
            pub_date=datetime.datetime.now(),
            pub_date_raw="Wed, 01 Mar 2025 13:00:00 +0000",
            content_hash="hash2",
            original_url="https://example.com/test-article-2",
            source_id=2,
        ),
    ]
    return parser


@pytest.fixture(autouse=True)
def setup_factories(db_session):
    set_factory_session(db_session)


class TestNewsClient:
    @pytest.fixture
    def news_client(self, db_session, mock_redis_client):
        yield NewsClient(db_session, mock_redis_client)
        db_session.rollback()

    @pytest.mark.asyncio
    async def test_fetch_headlines_success(
        self, news_client, db_session, mock_http_response, mock_parser
    ):
        source = SourceFactory()
        category = CategoryFactory(source_id=source.id)

        db_session.commit()

        news_client.http_client.request = AsyncMock(return_value=mock_http_response)
        news_client._get_parser = MagicMock(return_value=mock_parser)
        news_client.redis.pipeline_check_hashes = AsyncMock(return_value={})
        news_client.redis.pipeline_add_hashes = AsyncMock()

        result = await news_client.fetch_headlines(
            source.id, category.id, "https://example.com/feed.xml"
        )

        assert result == (2, 0)

        saved_articles = db_session.query(Articles).all()
        assert len(saved_articles) == 2

        news_client.redis.pipeline_add_hashes.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_headlines_with_existing_articles(
        self, news_client, db_session, mock_http_response, mock_parser
    ):
        source = SourceFactory()
        category = CategoryFactory(source_id=source.id)

        existing_article = ArticleFactory(
            source_id=source.id,
            content_hash="hash1",
        )

        news_client.http_client.request = AsyncMock(return_value=mock_http_response)
        news_client._get_parser = MagicMock(return_value=mock_parser)

        news_client.redis.pipeline_check_hashes = AsyncMock(
            return_value={"hash1": True, "hash2": False}
        )
        news_client.redis.pipeline_add_hashes = AsyncMock()

        result = await news_client.fetch_headlines(
            source.id, category.id, "https://example.com/feed.xml"
        )
        assert result == (1, 0)

        saved_articles = db_session.query(Articles).all()
        assert len(saved_articles) == 2

    @pytest.mark.asyncio
    async def test_fetch_headlines_timeout(self, news_client, db_session, mock_logger):
        source = SourceFactory()
        category = CategoryFactory(source_id=source.id)
        db_session.commit()

        news_client.http_client.request = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("src.clients.news.logger", mock_logger):
            result = await news_client.fetch_headlines(
                source.id, category.id, "https://example.com/feed.xml"
            )

            assert result == (0, 0)

            assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_fetch_multiple_feeds(self, news_client):
        source1 = SourceFactory()
        source2 = SourceFactory()
        category1 = CategoryFactory(source_id=source1.id)
        category2 = CategoryFactory(source_id=source2.id)

        feeds = [
            (source1.id, category1.id, "https://example.com/feed1.xml"),
            (source2.id, category2.id, "https://example.com/feed2.xml"),
        ]

        news_client.fetch_headlines = AsyncMock()
        news_client.fetch_headlines.side_effect = [(3, 0), (2, 0)]

        results = await news_client.fetch_multiple_feeds(feeds)

        assert results == [(3, 0), (2, 0)]

        assert news_client.fetch_headlines.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_multiple_feeds_with_errors(self, news_client, db_session):
        source1 = SourceFactory()
        source2 = SourceFactory()
        category1 = CategoryFactory(source_id=source1.id)
        category2 = CategoryFactory(source_id=source2.id)
        db_session.commit()

        feeds = [
            (source1.id, category1.id, "https://example.com/feed1.xml"),
            (source2.id, category2.id, "https://example.com/feed2.xml"),
        ]

        async def mock_fetch_headlines(source_id, category_id, feed_url):
            if source_id == source1.id:
                return (3, 0)
            else:
                raise RSSFeedError("Failed to fetch feed")

        with patch.object(
            news_client, "fetch_headlines", side_effect=mock_fetch_headlines
        ):
            results = await news_client.fetch_multiple_feeds(feeds)
            assert results[0] == (3, 0)
            assert results[1] == (0, 0)

    def test_get_parser_xml(self, news_client):
        parser = news_client._get_parser("application/xml", 1)
        assert parser.__class__.__name__ == "XMLFeedParser"

    def test_get_parser_json(self, news_client):
        parser = news_client._get_parser("application/json", 1)
        assert parser.__class__.__name__ == "JSONFeedParser"

    def test_get_parser_unknown(self, news_client, mock_logger):
        with patch("src.clients.news.logger", mock_logger):
            parser = news_client._get_parser("text/plain", 1)
            assert parser.__class__.__name__ == "XMLFeedParser"

            mock_logger.warning.assert_called_once_with(
                "Unknown content type: text/plain, defaulting to XML parser"
            )

    def test_get_parser_caching(self, news_client):
        parser1 = news_client._get_parser("application/xml", 1)
        parser2 = news_client._get_parser("application/xml", 1)

        assert parser1 is parser2

        parser3 = news_client._get_parser("application/json", 1)

        assert parser1 is not parser3

    @pytest.mark.asyncio
    async def test_process_feed_gzip(self, news_client, mock_parser):
        import gzip

        content = (
            b"<rss><channel><item><title>Test Article</title></item></channel></rss>"
        )

        gzipped_content = gzip.compress(content)

        headers = MagicMock()
        headers.headers = {
            "Content-Type": "application/xml",
            "Content-Encoding": "gzip",
        }

        response = (headers, gzipped_content)

        news_client._get_parser = MagicMock(return_value=mock_parser)

        articles = await news_client._process_feed(response, 1)

        mock_parser.parse_content.assert_called_once()

        assert len(articles) == 2
