import socket
import ssl
import json
import logging
import time
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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
        self.ssl_context = ssl_context
        self.timeout = timeout
        self._socket: Optional[ssl.SSLSocket] = None
        self.last_used: float = 0
        self.is_busy: bool = False

    @property
    def socket(self) -> ssl.SSLSocket:
        if not self._socket:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            self._socket = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
            self._socket.connect((self.host, self.port))
            self.last_used = time.time()
        return self._socket

    def connect(self) -> None:
        _ = self.socket

    def close(self) -> None:
        if self._socket:
            try:
                self.socket.shutdown(socket.SHUT_RD)
            except (socket.error, OSError):
                pass
            self._socket.close()
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

    def _create_connection(self, host: str, port: int) -> Connection:
        conn = Connection(host, port, self.ssl_context, self.timeout)
        conn.connect()
        return conn

    @contextmanager
    def get_connection(self, host: str, port: int) -> Iterator[Connection]:
        key = (host, port)

        if key not in self.connections:
            self.connections[key] = []

        conn = None
        for existing_conn in self.connections[key]:
            if not existing_conn.is_busy:
                if existing_conn.is_expired:
                    existing_conn.close()
                    continue
                conn = existing_conn
                break

        if conn is None and len(self.connections[key]) < self.max_connections:
            conn = self._create_connection(host, port)
            self.connections[key].append(conn)

        if conn is None:
            raise RuntimeError("No available connections")

        try:
            conn.is_busy = True
            yield conn
        finally:
            conn.is_busy = False
            conn.last_used = time.time()


class NewsClient:
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
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Connection": "keep-alive",
                "Referer": "https://www.bloomberg.com/latest?utm_source=homepage&utm_medium=web&utm_campaign=latest",
                "Host": "https://www.bloomberg.com",
                "tracestate": "25300@nr=0-1-1982697-1103375443-a1d174eaa2327e59----1738870309759",
                "newrelic": "eyJ2IjpbMCwxXSwiZCI6eyJ0eSI6IkJyb3dzZXIiLCJhYyI6IjE5ODI2OTciLCJhcCI6IjExMDMzNzU0NDMiLCJpZCI6ImExZDE3NGVhYTIzMjdlNTkiLCJ0ciI6IjU4NjM0ZTM3OWQwZDRhNGM5NTVmNGIwYTJlZTY4YTFiIiwidGkiOjE3Mzg4NzAzMDk3NTksInRrIjoiMjUzMDAifX0=",
                "traceparent": "00-58634e379d0d4a4c955f4b0a2ee68a1b-a1d174eaa2327e59-01",
            }

    def resolve_host(self, url: str) -> Tuple[str, int, str]:
        """
        Resolve host from URL and return a tuple of (host, port, path)
        """
        try:
            if "://" in url:
                url = url.split("://")[1]

            host, *path_parts = url.split("/", 1)
            path = f"/{path_parts[0]}" if path_parts else "/"

            if ":" in host:
                host, port_str = host.split(":")
                port = int(port_str)
            else:
                port = 443

            return host, port, path
        except Exception as e:
            logger.error(f"Failed to resolve host from URL {url}: {e}")
            raise ValueError(f"Invalid URL format: {url}") from e

    def wrap_socket(self, sock: socket.socket, host: str) -> ssl.SSLSocket:
        """Wraps socket with SSL/TLS layer"""
        try:
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            ssl_sock = context.wrap_socket(sock, server_hostname=host)
            logger.info(f"SSL Version: {ssl_sock.version}")
            logger.info(f"Cipher: {ssl_sock.cipher()}")
            return ssl_sock
        except ssl.SSLError as e:
            logger.error(f"SSL Error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error wrapping socket: {e}")
            raise

    def _build_request_headers(
        self, host: str, extra_headers: Optional[Dict[str, str]] = None
    ) -> str:
        """Build HTTP request headers"""
        headers = self.config.headers.copy()
        headers["Host"] = host

        if extra_headers:
            headers.update(extra_headers)

        if self.config.cookies:
            headers["cookie"] = "; ".join(
                f"{k}={v}" for k, v in self.config.cookies.items()
            )
        return "\r\n".join(f"{k}: {v}" for k, v in headers.items())

    def send_request(
        self,
        sock: ssl.SSLSocket,
        host: str,
        path: str,
        method: str = "GET",
        params: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Send HTTP request
        """
        query_string = f"?{urlencode(params)}" if params else ""
        headers = self._build_request_headers(host, extra_headers)
        request = f"{method} {path}{query_string} HTTP/1.1\r\n{headers}\r\n\r\n"
        try:
            sock.sendall(request.encode())
        except Exception as e:
            logger.error(f"Failed to send request: {e}")
            raise

    def receive_response(self, sock: socket.socket) -> HTTPResponse:
        """
        Receive and parse HTTP response
        """
        logger.info("Receiving response")
        buffer = BytesIO()

        try:
            header_data = BytesIO()
            while True:
                chunk = sock.recv(self.config.chunk_size)
                if not chunk:
                    raise ConnectionError("Connection closed while reading headers")

                logger.info("Received chunk of size {len(chunk)}")
                header_data.write(chunk)

                header_str = header_data.getvalue().decode("latin1")
                if "\r\n" in header_str:
                    headers_raw, remaining = header_str.split("\r\n\r\n", 1)
                    buffer.write(remaining.encode("latin1"))
                    break
            logger.info("Headers received:\n{headers_raw}")
            headers = {}
            for line in headers_raw.split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            content_encoding = headers.get("content-encoding", "").lower()
            logger.info(
                f"Content-Length: {content_length}, Content-Encoding: {content_encoding}"
            )

            body_received = len(buffer.getvalue())
            while body_received < content_length:
                remaining = content_length - body_received
                to_read = min(self.config.chunk_size, remaining)
                logger.info(
                    f"Receiving {to_read} bytes... ({body_received}/{content_length})"
                )
                chunk = sock.recv(to_read)

                if not chunk:
                    logger.error(f"Connection closed after receiving {body_received}")
                    break

                buffer.write(chunk)
                body_received = len(buffer.getvalue())

            body = buffer.getvalue()
            logger.info(f"Total bytes received: {len(body)}")

            if content_encoding == "gzip":
                logger.info("Decompressing gzip response")
                try:
                    body = gzip.decompress(body)
                except Exception as e:
                    logger.error(f"Failed to decompress gzip response: {e}")
                    raise
            elif content_encoding == "deflate":
                logger.info("Decompresssing deflate response")
                try:
                    import zlib

                    body = zlib.decompress(body)
                except Exception as e:
                    logger.error(f"Failed to decompress deflate response: {e}")
                    raise

            try:
                body_str = body.decode("utf-8")
                logger.info("Successfully decoded response as UTF-8")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decode failed, falling back to latin1")
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
            if source == NewsSource.BLOOMBERG:
                url = "www.bloomberg.com/lineup-next/api/stories"
                params = {"limit": "25", "pageNumber": "1", "types": "ARTICLE"}
            else:
                raise ValueError("Unsupported news source: {source}")

            host, port, path = self.resolve_host(url)

            with self.connection_pool.get_connection(host, port) as conn:
                self.send_request(conn.socket, host, path, params=params)
                response = self.receive_response(conn.socket)

                if not response.is_success:
                    logging.error(
                        f"Error response from {source}: {response.status_code}"
                    )
                    logger.debug(f"Error body: {response.body}")
                    return None
                return self._parse_json_response(response.body)
        except Exception as e:
            logger.error(f"Error fetching headlines from {source}: {e}")
            return None

    def _parse_json_response(self, body: str) -> Optional[List[dict]]:
        """Parse JSON response body"""
        try:
            logger.debug("Response starts with: ", body[:100])
            logger.debug("Response ends with: ", body[-100:])

            json_start = -1
            if body.lstrip().startswith("["):
                json_start = body.find("[")
                json_end = body.rfind("]")
                logger.info("Found JSON array structure")
            else:
                json_start = body.find("{")
                json_end = body.rfind("}")
                logger.info("Found JSON object structure")

            if json_start >= 0 and json_end > json_start:
                logger.info(
                    f"Found JSON content from position {json_start} to {json_end}"
                )
                json_content = body[json_start : json_end + 1]

                if "\r" in json_content or "\n" in json_content:
                    logger.debug("JSON contains newlines or carriage returns")

                logger.debug(f"JSON structure starts with: {json_content[:100]}")
                logger.debug(f"JSON structure ends with: {json_content[-100:]}")

                try:
                    return json.loads(json_content)
                except json.JSONDecodeError as e:
                    error_pos = e.pos
                    context_start = max(0, error_pos - 50)
                    context_end = min(len(json_content), error_pos + 50)
                    error_context = json_content[context_start:context_end]

                    logger.error(f"JSON parse error at position: {error_pos}")
                    logger.error(f"Error context: {error_context}")
                    logger.error(f"Error message: {str(e)}")

                    if error_pos > 0:
                        char_at_error = json_content[error_pos : error_pos + 1]
                        logger.error(
                            f"Character at error posisition: {repr(char_at_error)}"
                        )

                    raise
            else:
                logger.error("No JSON content found (no matching braces)")
                logger.error(f"Full response: {body}")
                return None
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")


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
        logger.info("Successfully fetched headlines")
        logger.debug("Responses: %s", response)
        print("Latest Headlines:")
        print("=" * 50)
        for article in response:
            utc_time = datetime.strptime(
                article["publishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            local_time = utc_time.astimezone()
            published_time = datetime.strftime(local_time, "%H:%M")
            print(f"\n{published_time} BBG: {article['headline']}")
            print(f"Summary: {article['summary']}")

    else:
        logger.error("Failed to fetch headlines")
