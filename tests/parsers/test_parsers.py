import json
import pytest
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

from src.parsers.json import JSONFeedParser
from src.parsers.xml import XMLFeedParser
from src.models.db_models import Articles


@pytest.fixture
def mock_xml_response():
    headers = MagicMock()
    headers.headers = {
        "Content-Type": "application/xml",
        "Content-Encoding": "",
    }
    content = b"""
    <rss version="2.0">
        <channel>
            <title>Test RSS Feed</title>
            <description>A test RSS feed for unit testing</description>
            <item>
                <title>First Test Article</title>
                <pubDate>Wed, 01 Mar 2023 12:00:00 GMT</pubDate>
                <link>https://example.com/article1</link>
            </item>
            <item>
                <title>Second Test Article</title>
                <pubDate>Thu, 02 Mar 2023 14:30:00 GMT</pubDate>
                <link>https://example.com/article2</link>
            </item>
        </channel>
    </rss>
    """
    return (headers, content)


@pytest.fixture
def mock_json_response():
    headers = MagicMock()
    headers.headers = {"Content-Type": "application/json", "Content-Encoding": ""}
    content = b"""[
        {
            "headline": "First JSON Test Article",
            "publishedAt": "2023-03-01T12:00:00Z",
            "url": "https://example.com/json-article1"
        },
        {
            "headline": "Second JSON Test Article",
            "publishedAt": "2023-03-02T14:30:00Z",
            "url": "https://example.com/json-article2"
        }
    ]"""
    return (headers, content)


@pytest.fixture
def mock_html_response():
    headers = MagicMock()
    headers.headers = {"Content-Type": "application/html", "Content-Encoding": ""}
    content = b"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Test HTML Page</title>
        </head>
        <body>
            <h1>This is not a supported format</h1>
            <p>This response should trigger an unsupported content type error.</p>
        </body>
    </html>
    """
    return (headers, content)


class TestXMLParser:
    @pytest.mark.asyncio
    async def test_parse_content_returns_articles_list(self, mock_xml_response):
        parser = XMLFeedParser(source_id=1)
        _, content = mock_xml_response
        articles = await parser.parse_content(content.decode())
        assert isinstance(articles, list)
        assert all(isinstance(article, Articles) for article in articles)

    @pytest.mark.asyncio
    async def test_handles_incomplete_xml(self):
        parser = XMLFeedParser(source_id=1)
        incomplete_xml = "<rss><channel><item><title>Test</title></item></channel>"
        with pytest.raises(ET.ParseError):
            await parser.parse_content(incomplete_xml)

    @pytest.mark.asyncio
    async def test_missing_fields_handled(self):
        parser = XMLFeedParser(source_id=1)
        # xml with missing url
        xml_with_missing_link = b"""
        <rss version="2.0">
            <channel>
                <title>Test RSS Feed</title>
                <description>A test RSS feed for unit testing</description>
                <item>
                    <title>First Test Article</title>
                    <pubDate>Wed, 01 Mar 2023 12:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>
        """
        articles = await parser.parse_content(xml_with_missing_link.decode())
        print(articles)
        assert len(articles) == 1
        assert articles[0].title == "First Test Article"
        assert articles[0].original_url == ""

        # xml with missing title
        xml_with_missing_title = b"""
        <rss><channel><item>
        <pubDate>Wed, 01 Jan 2023 12:00:00 GMT</pubDate>
        <link>https://example.com</link>
        </item></channel></rss>
        """
        articles = await parser.parse_content(xml_with_missing_title.decode())
        assert len(articles) == 0

        # xml with missing date
        xml_with_missing_date = b"""
         <rss><channel><item>
            <title>Test Article</title>
            <link>https://example.com</link>
            </item></channel></rss>
        """
        articles = await parser.parse_content(xml_with_missing_date.decode())
        assert len(articles) == 0

        # xml with mixed validity
        xml_with_mixed_items = b"""
        <rss><channel>
        <item>
            <title>Valid Article</title>
            <pubDate>Wed, 01 Jan 2023 12:00:00 GMT</pubDate>
        </item>
        <item>
            <pubDate>Wed, 01 Jan 2023 12:00:00 GMT</pubDate>
            <link>https://example.com/invalid</link>
        </item>
        </channel></rss>
        """
        articles = await parser.parse_content(xml_with_mixed_items.decode())
        assert len(articles) == 1
        assert articles[0].title == "Valid Article"


class TestJSONParser:
    async def test_parse_content_returns_articles_list(self, mock_json_response):
        parser = JSONFeedParser(source_id=1)
        _, content = mock_json_response
        articles = await parser.parse_content(content.decode())
        assert isinstance(articles, list)
        assert len(articles) == 2
        assert articles[0].title == "First JSON Test Article"
        assert articles[0].original_url == "https://example.com/json-article1"

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self):
        parser = JSONFeedParser(source_id=1)
        malformed_json = "{'headline': 'Test Article'"
        with pytest.raises(json.JSONDecodeError):
            await parser.parse_content(malformed_json)

    @pytest.mark.asyncio
    async def test_datetime_conversion(self):
        parser = JSONFeedParser(source_id=1)
        json_content = json.dumps(
            [
                {
                    "headline": "Test Article",
                    "publishedAt": "2025-01-01T12:00:00Z",
                    "url": "https://example.com",
                }
            ]
        )
        articles = await parser.parse_content(json_content)

        assert len(articles) == 1
        assert articles[0].pub_date.year == 2025
        assert articles[0].pub_date.month == 1
        assert articles[0].pub_date.day == 1
        assert articles[0].pub_date.hour == 12
        assert articles[0].pub_date.tzinfo is not None

    @pytest.mark.asyncio
    async def test_missing_fields_handled(self):
        parser = JSONFeedParser(source_id=1)
        json_missing_url = json.dumps(
            [
                {
                    "headline": "Test Article",
                    "publishedAt": "2025-01-01T12:00:00Z",
                }
            ]
        )

        articles = await parser.parse_content(json_missing_url)
        assert len(articles) == 1
        assert articles[0].original_url == ""

        json_missing_headline = json.dumps(
            [
                {
                    "publishedAt": "2025-01-01T12:00:00Z",
                    "url": "https://example.com",
                }
            ]
        )

        articles = await parser.parse_content(json_missing_headline)
        assert len(articles) == 0

        json_mixed_items = json.dumps(
            [
                {
                    "headline": "Valid Article",
                    "publishedAt": "2025-01-01T12:00:00Z",
                },
                {
                    "url": "https://example.com/invalid",
                },
            ]
        )

        articles = await parser.parse_content(json_mixed_items)
        assert len(articles) == 1
        assert articles[0].title == "Valid Article"
