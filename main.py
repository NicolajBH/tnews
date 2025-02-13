from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, date, timezone
import itertools
import ssl
import logging
import gzip
import html
import asyncio
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Any
from collections import defaultdict
from asyncio import Queue, QueueFull, QueueEmpty
from contextlib import asynccontextmanager

# TODO dependency injection
# TODO request/response middleware
# TODO background tasks

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="api_log.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class BaseAPIException(HTTPException):
    """Base exception class for API errors"""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str,
        additional_info: Dict[str, Any] | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
        self.additional_info = additional_info or {}


class RSSFeedError(BaseAPIException):
    """Raised when there\'s an error fetching or parsing RSS feeds"""

    def __init__(
        self, detail: str, source: str | None = None, category: str | None = None
    ):
        additional_info = {"source": source, "category": category} if source else {}
        super().__init__(
            status_code=500,
            detail=detail,
            error_code="RSS_FEED_ERROR",
            additional_info=additional_info,
        )


class DateParsingError(BaseAPIException):
    """Raised when there\'s an error parsing article dates"""

    def __init__(self, detail: str, date_string: str):
        super().__init__(
            status_code=500,
            detail=detail,
            error_code="DATE_PARSING_ERROR",
            additional_info={"invalid_date": date_string},
        )


class InvalidSourceError(BaseAPIException):
    """Raised when an invalid source is requested"""

    def __init__(self, source: str):
        super().__init__(
            status_code=404,
            detail=f"Invalid source: {source}",
            error_code="INVALID_SOURCE",
            additional_info={"source": source},
        )


class InvalidCategoryError(BaseAPIException):
    """Raised when an invalid category is requested"""

    def __init__(self, source: str, category: str):
        super().__init__(
            status_code=404,
            detail=f"Invalid category '{category}' for source '{source}'",
            error_code="INVALID_CATEGORY",
            additional_info={"source": source, "category": category},
        )


class HTTPClientError(BaseAPIException):
    """Raised when there\'s an error in the HTTP client"""

    def __init__(
        self,
        detail: str,
        status_code: int = 500,
        host: str | None = None,
    ):
        additional_info = {"host": host} if host else {}
        super().__init__(
            status_code=status_code,
            detail=detail,
            error_code="HTTP_CLIENT_ERROR",
            additional_info=additional_info,
        )


class Article(BaseModel):
    title: str
    pubDate: str
    source: str
    formatted_time: str


class ArticleQueryParameters(BaseModel):
    start_date: date | None = Field(
        default=None,
        description="Start date for filtering articles(inclusive)",
        examples=["2024-02-10"],
    )
    end_date: date | None = Field(
        default=None,
        description="End date for filtering articles (inclusive)",
        examples=["2025-02,13"],
    )

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, end_date: date | None, info) -> date | None:
        start_date = info.data.get("start_date")
        if start_date and end_date and end_date < start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return end_date


class CategoryParams(BaseModel):
    source: str = Field(
        description="News source identifier", examples=["borsen"], min_length=1
    )
    category: str = Field(
        description="Category identifier for the specified source",
        examples=["tech", "finans"],
        min_length=1,
    )

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in RSS_FEEDS:
            raise ValueError(
                f"Invalid source. Must be one of: {', '.join(RSS_FEEDS.keys())}"
            )
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str, info) -> str:
        source = info.data.get("source")
        if source not in RSS_FEEDS[source]:
            raise ValueError(f"Invalid category for source {source}")
        return v


class RSSFeed(BaseModel):
    url: str
    categories: Dict[str, str]


class ArticleContent(BaseModel):
    title: str
    pubDate: str
    source: str

    @property
    def formatted_date(self) -> str:
        dt = datetime.strptime(self.pubDate, "%a, %d %b %Y %H:%M:%S %z")
        return datetime.strftime(dt, "%H:%M")


class HTTPHeaders(BaseModel):
    status_line: str
    headers: Dict[str, str]

    @classmethod
    def from_bytes(cls, header_data: bytes) -> "HTTPHeaders":
        header_lines = header_data.split(b"\r\n")
        headers = {}
        status_line = header_lines[0].decode()

        for line in header_lines[1:]:
            if b": " in line:
                key, value = line.decode().split(": ", 1)
                headers[key.strip()] = value.strip()

        return cls(status_line=status_line, headers=headers)


RSS_FEEDS = {
    "borsen": {
        "rss": "borsen.dk/rss",
        "breaking": "borsen.dk/rss/breaking",
        "baeredygtig": "borsen.dk/rss/baeredygtig",
        "ejendomme": "borsen.dk/rss/ejendomme",
        "finans": "borsen.dk/rss/finans",
        "investor": "borsen.dk/rss/investor",
        "ledelse": "borsen.dk/rss/executive",
        "longread": "borsen.dk/rss/longread",
        "markedsberetninger": "borsen.dk/rss/markedsberetninger",
        "opinion": "borsen.dk/rss/opinion",
        "pleasure": "borsen.dk/rss/pleasure",
        "politik": "borsen.dk/rss/politik",
        "tech": "borsen.dk/rss/tech",
        "udland": "borsen.dk/rss/udland",
        "virksomheder": "borsen.dk/rss/virksomheder",
        "okonomi": "borsen.dk/rss/okonomi",
    }
}


class PooledConnection:
    _id_counter = itertools.count(1)

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str
    ) -> None:
        self.id = next(self._id_counter)
        self.reader = reader
        self.writer = writer
        self.host = host
        self.in_use = False
        logger.info(f"Created connection {self.id} for {host}")

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class ConnectionPool:
    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.pools: Dict[str, Queue[PooledConnection]] = defaultdict(
            lambda: Queue(maxsize=pool_size)
        )
        self.ssl_context = ssl.create_default_context()

    async def _create_connection(self, host: str) -> PooledConnection:
        reader, writer = await asyncio.open_connection(host, 443, ssl=self.ssl_context)
        return PooledConnection(reader, writer, host)

    @asynccontextmanager
    async def get_connection(self, host: str):
        pool = self.pools[host]
        conn = None

        try:
            conn = await self.get_or_create_connection(pool, host)
            conn.in_use = True
            logger.info(f"Using connection {conn.id} for {host}")
            yield conn
        finally:
            if conn:
                conn.in_use = False
                try:
                    pool.put_nowait(conn)
                    logger.info(f"Returned connection {conn.id} to pool for {host}")
                except QueueFull:
                    await conn.close()

    async def get_or_create_connection(
        self, pool: Queue, host: str
    ) -> PooledConnection:
        try:
            return pool.get_nowait()
        except QueueEmpty:
            if pool.qsize() < self.pool_size:
                return await self._create_connection(host)
            return await pool.get()


class HTTPClient:
    def __init__(self, connection_pool: ConnectionPool) -> None:
        self.connection_pool = connection_pool

    async def _read_chunked_body(self, reader: asyncio.StreamReader) -> bytes:
        buffer = BytesIO()
        while True:
            chunk_size_line = await reader.readuntil(b"\r\n")
            chunk_size = int(chunk_size_line.strip(), 16)

            if chunk_size == 0:
                await reader.readexactly(2)
                break

            chunk = await reader.readexactly(chunk_size)
            buffer.write(chunk)
            await reader.readexactly(2)

        return buffer.getvalue()

    async def request(
        self, method: str, url: str, request_headers: Dict[str, str] | None = None
    ) -> Tuple[HTTPHeaders, bytes]:
        host, path = url.split("/", 1)
        path = f"/{path}"

        headers = request_headers.copy() if request_headers else {}
        headers.update(
            {
                "Host": host,
                "Accept": "*/*",
                "Accept-Encoding": "gzip",
                "User-Agent": " Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
            }
        )

        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"{chr(10).join(f'{k}: {v}' for k, v in headers.items())}\r\n\r\n"
        )

        async with self.connection_pool.get_connection(host) as conn:
            conn.writer.write(request.encode())
            await conn.writer.drain()

            header_data = await conn.reader.readuntil(b"\r\n\r\n")
            response_headers = HTTPHeaders.from_bytes(header_data)
            body = await self._read_chunked_body(conn.reader)

            return response_headers, body


class NewsClient:
    def __init__(self):
        self.connection_pool = ConnectionPool(pool_size=3)
        self.http_client = HTTPClient(self.connection_pool)

    async def fetch_headlines(self, rss_feed: str) -> List[ArticleContent]:
        """Fetches headlines from RSS feeds"""
        headers, body = await self.http_client.request("GET", rss_feed)

        xml_string = gzip.decompress(body).decode("utf-8", errors="replace")
        tree = ET.fromstring(xml_string)

        return [
            ArticleContent(
                title=html.unescape(title_elem.text),
                pubDate=pubdate_elem.text,
                source=rss_feed.split(".")[0],
            )
            for item in tree.findall(".//item")
            if (title_elem := item.find("title")) is not None
            and title_elem.text is not None
            and (pubdate_elem := item.find("pubDate")) is not None
            and pubdate_elem.text is not None
        ]


async def api_exception_handler(
    request: Request,
    exc: Any,
) -> JSONResponse:
    """Handler for API exceptions"""
    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": exc.status_code,
        "error_code": exc.error_code,
        "message": exc.detail,
        "path": request.url.path,
    }

    if exc.additional_info:
        error_response["additional_info"] = exc.additional_info

    return JSONResponse(status_code=exc.status_code, content=error_response)


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handler for unexpected exceptions"""
    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": 500,
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occured",
        "path": request.url.path,
        "type": exc.__class__.__name__,
    }

    return JSONResponse(status_code=500, content=error_response)


news_client = NewsClient()
app = FastAPI()
app.add_exception_handler(BaseAPIException, api_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


def format_articles(articles: List[ArticleContent]) -> List[Article]:
    articles_by_pub_date = sorted(
        articles,
        key=lambda x: datetime.strptime(x.pubDate, "%a, %d %b %Y %H:%M:%S %z"),
        reverse=True,
    )

    seen = set()
    unique_articles = []
    for article in articles_by_pub_date:
        if article.title not in seen:
            seen.add(article.title)
            unique_articles.append(article)
    return [
        Article(
            title=article.title,
            pubDate=article.pubDate,
            source=article.source,
            formatted_time=article.formatted_date,
        )
        for article in unique_articles[:20]
    ]


@app.get("/articles/latest", response_model=List[Article])
async def get_latest_articles(
    params: ArticleQueryParameters = Depends(),
) -> List[Article]:
    try:
        articles = []
        for source, categories in RSS_FEEDS.items():
            article_tasks = [
                news_client.fetch_headlines(feed_url)
                for category, feed_url in categories.items()
            ]
            try:
                category_articles = await asyncio.gather(*article_tasks)
                for category, fetched_articles in zip(
                    categories.keys(), category_articles
                ):
                    articles.extend(fetched_articles)
                    logger.info(f"Fetched articles from {source}/{category}")
            except Exception as e:
                logger.error(f"Error fetching articles from {source}: {str(e)}")
                raise RSSFeedError(
                    detail=f"Failed to fetch articles from {source}",
                    source=source,
                )

        if params.start_date is None and params.end_date is None:
            return format_articles(articles)

        filtered_articles = []
        for article in articles:
            try:
                article_date = datetime.strptime(
                    article.pubDate, "%a, %d %b %Y %H:%M:%S %z"
                ).date()
                start_condition = (
                    True
                    if params.start_date is None
                    else article_date >= params.start_date
                )
                end_condition = (
                    True if params.end_date is None else article_date <= params.end_date
                )

                if start_condition and end_condition:
                    filtered_articles.append(article)
            except ValueError as e:
                logger.error(
                    f"Date parsing error for article: {article.title[:30]}... Error: {e}"
                )
                raise DateParsingError(
                    detail="Failed to parse article date", date_string=article.pubDate
                )
        return format_articles(filtered_articles)
    except (RSSFeedError, DateParsingError):
        raise
    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)}", exc_info=True)
        raise HTTPClientError(detail="Unexpected error while fetching articles")


@app.get("/sources/{source}/categories/{category}", response_model=List[Article])
async def get_category_articles(params: CategoryParams = Depends()) -> List[Article]:
    try:
        if params.source not in RSS_FEEDS:
            raise InvalidSourceError(params.source)

        if params.category not in RSS_FEEDS[params.source]:
            raise InvalidCategoryError(params.source, params.category)

        articles = await news_client.fetch_headlines(
            RSS_FEEDS[params.source][params.category]
        )
        return format_articles(articles)

    except Exception as e:
        logger.error(
            f"Error fetching articles for {params.source}/{params.category}: {str(e)}",
            exc_info=True,
        )
        raise RSSFeedError(
            detail="Failed to fetch articles",
            source=params.source,
            category=params.category,
        )


@app.get("/categories")
async def get_categories() -> Dict[str, List[str]]:
    try:
        return {source: list(cats.keys()) for source, cats in RSS_FEEDS.items()}
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching categories")


@app.get("/sources")
async def get_sources() -> Dict[str, List[str]]:
    try:
        return {"sources": list(RSS_FEEDS.keys())}
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching sources")
