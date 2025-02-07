import socket
import ssl
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from urllib.parse import urlencode
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List, Iterator
from enum import Enum
from http import HTTPStatus
from contextlib import contextmanager
from io import BytesIO
import gzip

# TODO Borsen latest
# TODO Borsen most read
# TODO Bloomberg most popular

file_handler = RotatingFileHandler(
    "news_client.log", maxBytes=1024 * 1024, backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)
console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logging.getLogger().handlers = []


class NewsSource(Enum):
    BLOOMBERG = "bloomberg"
    BORSEN = "borsen"


@dataclass
class HTTPResponse:
    status_code: int
    headers: dict
    body: str

    @property
    def is_success(self) -> bool:
        return self.status_code == HTTPStatus.OK


class NewsClientConfig:
    def __init__(
        self,
        timeout: int = 10,
        chunk_size: int = 4096,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.headers = headers or {}
        self.cookies = cookies or {}


class Connection:
    def __init__(
        self, host: str, port: int, ssl_context: ssl.SSLContext, timeout: float
    ) -> None:
        self.host = host
        self.port = port
        self._socket: Optional[ssl.SSLSocket] = None
        self.ssl_context = ssl_context
        self.timeout = timeout
        self.last_used: float = 0
        self.is_busy: bool = False

    @property
    def socket(self) -> ssl.SSLSocket:
        if not self._socket:
            self._create_socket()
        assert self._socket is not None
        return self._socket

    def _create_socket(self) -> None:
        """Create and connect a new SSL socket"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        self._socket = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        self._socket.connect((self.host, self.port))
        self.last_used = time.time()

    def close(self) -> None:
        """Close connection"""
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            except (socket.error, OSError):
                pass
            finally:
                self._socket = None

    @property
    def is_expired(self, max_idle_time: float = 300) -> bool:
        return time.time() - self.last_used > max_idle_time


class ConnectionPool:
    def __init__(self, max_connections: int = 10, timeout: float = 10) -> None:
        self.max_connections = max_connections
        self.timeout = timeout
        self.connections: Dict[Tuple[str, int], List[Connection]] = {}
        self.ssl_context = ssl.create_default_context()

    @contextmanager
    def get_connection(self, host: str, port: int) -> Iterator[Connection]:
        key = (host, port)

        if key not in self.connections:
            self.connections[key] = []

        conn = self._get_available_connection(key)

        if conn is None:
            conn = self._create_new_connection(key)

        if conn is None:
            raise RuntimeError("No connections available and pool is full")

        try:
            conn.is_busy = False
            yield conn
        finally:
            conn.is_busy = False
            conn.last_used = time.time()

    def _get_available_connection(self, key: Tuple[str, int]) -> Optional[Connection]:
        """Find an available connection, removing expired ones"""
        active_connections = []
        for conn in self.connections[key]:
            if conn.is_expired:
                conn.close()
                continue
            if not conn.is_busy:
                return conn
            active_connections.append(conn)

        self.connections[key] = active_connections
        return None

    def _create_new_connection(self, key: Tuple[str, int]) -> Optional[Connection]:
        """Create a new connection if pool isn't full"""
        if len(self.connections[key]) < self.max_connections:
            conn = Connection(key[0], key[1], self.ssl_context, self.timeout)
            self.connections[key].append(conn)
            return conn
        return None


class NewsClient:
    ENDPOINTS = {
        NewsSource.BLOOMBERG: {
            "host": "www.bloomberg.com",
            "path": "/lineup-next/api/stories",
            "params": {"limit": "25", "pageNumber": "1", "types": "ARTICLE"},
        }
    }

    def __init__(self, config: Optional[NewsClientConfig] = None) -> None:
        self.config = config or NewsClientConfig()
        self._setup_default_headers()
        self.connection_pool = ConnectionPool(
            max_connections=5, timeout=self.config.timeout
        )

    def _setup_default_headers(self) -> None:
        """Setup default headers if none provided"""
        if not self.config.headers:
            self.config.headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_2) AppleWebKit/601.3.9 (KHTML, like Gecko) Version/9.0.2 Safari/601.3.9",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Host": "www.bloomberg.com",
            }

    def resolve_host(self, url: str) -> Tuple[str, int, str]:
        """
        Resolve host from URL and return a tuple of (host, port, path)
        """
        url = url.removeprefix("https://").removeprefix("http://")

        parts = url.split("/", 1)
        host = parts[0]
        path = f"/{parts[1]}" if len(parts) > 1 else "/"
        return host, 443, path

    def _build_request(
        self,
        host: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> bytes:
        """Build HTTP request with headers"""
        query = f"?{urlencode(params)}" if params else ""

        headers = self.config.headers.copy()
        headers["Host"] = host
        if extra_headers:
            headers.update(extra_headers)
        if self.config.cookies:
            headers["cookie"] = "; ".join(
                f"{k}={v}" for k, v in self.config.cookies.items()
            )

        header_lines = [f"{method} {path}{query} HTTP/1.1"]
        header_lines.extend(f"{k}: {v}" for k, v in headers.items())

        return "\r\n".join([*header_lines, "", ""]).encode()

    def receive_response(self, sock: socket.socket) -> HTTPResponse:
        """
        Receive and parse HTTP response
        """
        buffer = BytesIO()

        try:
            header_data = BytesIO()
            while True:
                chunk = sock.recv(self.config.chunk_size)
                if not chunk:
                    raise ConnectionError("Connection closed while reading headers")

                header_data.write(chunk)
                header_str = header_data.getvalue().decode("latin1")
                if "\r\n" in header_str:
                    headers_raw, remaining = header_str.split("\r\n\r\n", 1)
                    buffer.write(remaining.encode("latin1"))
                    break

            headers = {}
            for line in headers_raw.split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body_received = len(buffer.getvalue())
            while body_received < content_length:
                remaining = content_length - body_received
                to_read = min(self.config.chunk_size, remaining)
                chunk = sock.recv(to_read)
                if not chunk:
                    raise ConnectionError(
                        f"Connection closed after receiving {body_received} of {content_length} bytes"
                    )
                buffer.write(chunk)
                body_received = len(buffer.getvalue())

            body = buffer.getvalue()
            content_encoding = headers.get("content-encoding", "").lower()

            if content_encoding == "gzip":
                try:
                    body = gzip.decompress(body)
                except Exception as e:
                    logger.error(f"Failed to decompress gzip response: {e}")
                    raise
            elif content_encoding == "deflate":
                try:
                    import zlib

                    body = zlib.decompress(body)
                except Exception as e:
                    logger.error(f"Failed to decompress deflate response: {e}")
                    raise

            try:
                body_str = body.decode("utf-8")
            except UnicodeDecodeError:
                body_str = body.decode("latin1")

            status_code = int(headers_raw.split("\n")[0].split()[1])

            return HTTPResponse(status_code, headers, body_str)

        except socket.timeout:
            logger.error("Socket timeout while receiving response")
            raise
        except Exception as e:
            logger.error(f"Error receiving response: {e}")
            raise

    def fetch_headlines(
        self, source: NewsSource = NewsSource.BLOOMBERG
    ) -> Optional[List[dict]]:
        """
        Fetch headlines and return parsed JSON response
        """
        try:
            endpoint = self.ENDPOINTS.get(source)
            if not endpoint:
                raise ValueError(f"Unsupported News Source: {source}")
            host, port, _ = self.resolve_host(endpoint["host"])
            with self.connection_pool.get_connection(host, port) as conn:
                request = self._build_request(
                    host=endpoint["host"],
                    path=endpoint["path"],
                    params=endpoint["params"],
                )
                conn.socket.sendall(request)
                response = self.receive_response(conn.socket)
                if not response.is_success:
                    logger.error(
                        f"Error response from {source}: {response.status_code}"
                    )
                    return None
            return self._parse_json_response(response.body)

        except Exception as e:
            logger.error(f"Error fetching headlines from {source}: {e}")

    def _parse_json_response(self, body: str) -> Optional[List[dict]]:
        """Parse JSON response body"""
        try:
            json_start = -1
            if body.lstrip().startswith("["):
                json_start = body.find("[")
                json_end = body.rfind("]")
            else:
                json_start = body.find("{")
                json_end = body.rfind("}")

            if json_start >= 0 and json_end > json_start:
                json_content = body[json_start : json_end + 1]
                return json.loads(json_content)
            else:
                logger.error("No valid JSON structure found in response")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON at position {e.pos}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return None


def utc_time_to_local(timestamp: str) -> str:
    utc_time = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    local_time = utc_time.astimezone()
    return datetime.strftime(local_time, "%H:%M")


if __name__ == "__main__":
    config = NewsClientConfig(
        timeout=10,
        cookies={
            "exp_pref": "EUR",
            "country_code": "DK",
            "_pxhd": "kd3Ssy7vbkSduzX6JYFnr5t7dVXiRTd5235rmVJh0wLA6l7q1Hs5G5kEy-vVQBU9Xa/UWSUZutFjV-Xyx4f-Fw==:SNlYZGutwozET1Z1SDcZrrhiQCCGCH8Y8hFHCWrDLBmOzGw9HDYwxo66BzJhMLNk8wNwT5INH8rCY157d-CR-7Jleew4PwgiDAqKqJ8xENI=",
        },
    )
    client = NewsClient(config)
    response = client.fetch_headlines(NewsSource.BLOOMBERG)
    if response:
        output = ["Latest Headlines", "=" * 50]
        for article in response:
            published_time = utc_time_to_local(article["publishedAt"])
            output.extend([f"{published_time} BBG: {article['headline']}"])
        print("\n".join(output))
    else:
        logger.error("Failed to fetch headlines")
