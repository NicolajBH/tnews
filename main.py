from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import socket
import ssl
import logging
import gzip
import html
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple

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

    class Config:
        from_attributes = True


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


class NewsClient:
    def __init__(self) -> None:
        self.port = 443
        self.context = ssl.create_default_context()

    def resolve_rss_feed(self, rss_feed: str) -> Tuple[str, str]:
        """Return host and path from rss feed"""
        host = rss_feed.split("/", 1)[0]
        path = "/" + rss_feed.split("/", 1)[1]
        return host, path

    def fetch_headlines(self, rss_feed: str) -> List[Dict[str, str]]:
        """Fetches headlines from the Borsen RSS feed"""
        host, path = self.resolve_rss_feed(rss_feed)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with self.context.wrap_socket(s, server_hostname=host) as ssl_sock:
                ssl_sock.settimeout(10)
                ssl_sock.connect((host, self.port))
                headers = {
                    "Host": host,
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip",
                    "User-Agent": " Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
                }
                headers_str = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
                request = f"GET {path} HTTP/1.1\r\n{headers_str}\r\n\r\n"
                request = request.encode()
                ssl_sock.sendall(request)
                buffer = BytesIO()
                header_buffer = BytesIO()
                while True:
                    chunk_received = ssl_sock.recv(4096)
                    if b"\r\n\r\n" not in chunk_received:
                        header_buffer.write(chunk_received)
                    else:
                        header_chunk, remaining = chunk_received.split(b"\r\n\r\n", 1)
                        header_buffer.write(header_chunk)
                        break
                status_line, *headers_raw = header_buffer.getvalue().split(b"\r\n", 1)
                headers = {}
                headers["status_line"] = status_line.decode()
                for i in headers_raw:
                    decoded_headers = i.decode()
                    for i in decoded_headers.split("\r\n"):
                        key, value = i.split(": ", 1)
                        headers[key] = value
                #                 status_code = headers["status_line"].split(" ", 1)[1]
                while True:
                    # check if stream end is in chunk
                    def check_end_chunk():
                        if b"0\r\n\r\n" in remaining:
                            remaining_part, terminator = remaining.split(
                                b"0\r\n\r\n", 1
                            )
                            buffer.write(remaining_part)
                            return True
                        return False

                    if check_end_chunk():
                        break

                    while b"\r\n" not in remaining:
                        remaining += ssl_sock.recv(4096)
                        if check_end_chunk():
                            break

                    if b"0\r\n\r\n" in remaining:
                        continue

                    chunk_size, remaining = remaining.split(b"\r\n", 1)
                    chunk_size = int(chunk_size, 16)
                    # check if whole chunk has been received
                    needed = chunk_size + 2
                    total_received = len(remaining)
                    while total_received < needed:
                        new_data = ssl_sock.recv(4096)
                        if not new_data:
                            break
                        remaining += new_data
                        total_received = len(remaining)

                    chunk, remaining = (
                        remaining[:chunk_size],
                        remaining[chunk_size + 2 :],
                    )
                    buffer.write(chunk)

                body = buffer.getvalue()
                xml_string = gzip.decompress(body).decode("utf-8", errors="replace")
                tree = ET.fromstring(xml_string)
                items: List = tree.findall(".//item")
                articles = []
                for item in items:
                    title = html.unescape(item.find("title").text)
                    pub_date = item.find("pubDate").text
                    articles.append(
                        {
                            "title": title,
                            "pubDate": pub_date,
                            "source": host.split(".")[-2],
                        }
                    )
                return articles


news_client = NewsClient()
app = FastAPI()


def format_articles(articles):
    date_format = "%a, %d %b %Y %H:%M:%S %z"
    articles_by_pub_date = sorted(
        articles,
        key=lambda x: datetime.strptime(x["pubDate"], date_format),
        reverse=True,
    )
    articles_by_pub_date = list({d["title"]: d for d in articles_by_pub_date}.values())
    result = []
    for article in articles_by_pub_date[:20]:
        dt = datetime.strptime(article["pubDate"], date_format)
        article["formatted_time"] = datetime.strftime(dt, "%H:%M")
        result.append(article)
    return result[:20]


@app.get("/articles/latest", response_model=List[Article])
async def get_latest_articles():
    """Get the latest articles across all categories"""
    try:
        articles = []
        for source, categories in RSS_FEEDS.items():
            for category, feed_url in categories.items():
                articles.extend(news_client.fetch_headlines(feed_url))
                logger.info(f"Fetched articles from {source}/{category}")

            return format_articles(articles)
    except Exception as e:
        logging.error(f"Error fetching articles: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching articles")


@app.get("/sources/{source}/categories/{category}", response_model=List[Article])
async def get_category_articles(source: str, category: str):
    """Get articles for a specific category from a specific source"""
    try:
        if source not in RSS_FEEDS:
            raise HTTPException(status_code=404, detail="Source not found")
        if category not in RSS_FEEDS[source]:
            raise HTTPException(status_code=404, detail="Category not found")
        articles = news_client.fetch_headlines(RSS_FEEDS[source][category])
        return format_articles(articles)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching articles for {source}/{category}: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Error fetching articles")


@app.get("/categories")
async def get_categories():
    """Get list of all available categories"""
    try:
        categories = {source: list(cats.keys()) for source, cats in RSS_FEEDS.items()}
        return categories
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching categories")


@app.get("/sources")
async def get_sources():
    """Get list of all sources for RSS feed"""
    try:
        return {"sources": list(RSS_FEEDS.keys())}
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching sources")
