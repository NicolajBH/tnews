from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import itertools
import ssl
import logging
import gzip
import html
import asyncio
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple
from collections import defaultdict
from asyncio import Queue, QueueFull, QueueEmpty
from contextlib import asynccontextmanager

# TODO request validation
# TODO dependency injection
# TODO request/response middleware
# TODO background tasks
# TODO custom exception handlers
# TODO CORS configuration

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="api_log.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class Article(BaseModel):
    title: str
    pubDate: str
    source: str
    formatted_time: str


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


news_client = NewsClient()
app = FastAPI()


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
async def get_latest_articles() -> List[Article]:
    try:
        articles = []
        for source, categories in RSS_FEEDS.items():
            article_tasks = [
                news_client.fetch_headlines(feed_url)
                for category, feed_url in categories.items()
            ]
            category_articles = await asyncio.gather(*article_tasks)
            for category, fetched_articles in zip(categories.keys(), category_articles):
                articles.extend(fetched_articles)
                logger.info(f"Fetched articles from {source}/{category}")
        return format_articles(articles)
    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching articles")


@app.get("/sources/{source}/categories/{category}", response_model=List[Article])
async def get_category_articles(source: str, category: str) -> List[Article]:
    try:
        if source not in RSS_FEEDS:
            raise HTTPException(status_code=404, detail="Source not found")
        if category not in RSS_FEEDS[source]:
            raise HTTPException(status_code=404, detail="Category not found")

        articles = await news_client.fetch_headlines(RSS_FEEDS[source][category])
        return format_articles(articles)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching articles for {source}/{category}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Error fetching articles")


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
