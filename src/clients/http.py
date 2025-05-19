import asyncio
import random
import re
import time
from typing import Dict, Tuple, Any, Callable, Awaitable, TypeVar, Optional
from io import BytesIO
from urllib.parse import urlparse

from src.core.logging import LogContext
from src.models.http import HTTPHeaders
from src.clients.connection import ConnectionPool
from src.constants import DEFAULT_HEADERS, DEFAULT_USER_AGENT
from src.core.exceptions import HTTPClientError, ServiceUnavailableError

logger = LogContext(__name__)

T = TypeVar("T")


class CaptchaError(Exception):
    """Raised when a CAPTCHA is detected"""

    pass


class CircuitState:
    """Circuit states for breaker pattern"""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 2,
        reset_timeout: float = 15 * 60,
        backoff_multiplier: float = 2.0,
        max_timeout: float = 4 * 60 * 60,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.backoff_multiplier = backoff_multiplier
        self.max_timeout = max_timeout

        # state tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.current_timeout = reset_timeout

        # cache for fallback data
        self.cache = {}

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        cache_key: str | None = None,
        *args,
        **kwargs,
    ) -> T:
        """Execute function with circuit breaker pattern"""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time < self.current_timeout:
                if cache_key in self.cache:
                    logger.info(
                        "Circuit OPEN - using cached data",
                        extra={"circuit_name": self.name, "cache_key": cache_key},
                    )
                    return self.cache[cache_key]
                raise HTTPClientError(detail=f"Circuit {self.name} is OPEN")

            logger.info(
                "Circuit switching to HALF_OPEN",
                extra={"circuit_name": self.name, "cache_key": cache_key},
            )
            self.state = CircuitState.HALF_OPEN

        try:
            result = await func(*args, **kwargs)

            if self.state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit recovery successful - CLOSED",
                    extra={"circuit_name": self.name},
                )

            if cache_key is not None:
                self.cache[cache_key] = result

            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if (
                self.state == CircuitState.CLOSED
                and self.failure_count >= self.failure_threshold
            ):
                self.state = CircuitState.OPEN
                logger.warning(
                    "Circuit OPEN - threshold reached",
                    extra={
                        "error": str(e),
                        "circuit_name": self.name,
                        "state": self.state,
                        "failure_count": self.failure_count,
                        "last_failure_time": self.last_failure_time,
                        "error_type": e.__class__.__name__,
                    },
                )

            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.current_timeout = min(
                    self.current_timeout * self.backoff_multiplier, self.max_timeout
                )
                logger.warning(
                    "Circuit OPEN - test failed",
                    extra={
                        "error": str(e),
                        "circuit_name": self.name,
                        "state": self.state,
                        "failure_count": self.failure_count,
                        "last_failure_time": self.last_failure_time,
                        "error_type": e.__class__.__name__,
                    },
                )

            raise

    def _reset(self):
        """reset circuit to closed state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.current_timeout = self.reset_timeout

    def get_state(self):
        """get current circuit state info"""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "current_timeout": self.current_timeout,
        }


class HTTPClient:
    def __init__(self, connection_pool: ConnectionPool, health_service=None) -> None:
        self.connection_pool = connection_pool
        self.health_service = health_service
        self._cookies: Dict[str, Dict[str, str]] = {}
        self._user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ]
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Special domains configuration
        self._special_domains = {
            "www.bloomberg.com": {
                "rotate_user_agent": True,
                "browser_headers": True,
                "preserve_cookies": True,
                "use_curl": True,
                "curl_endpoints": ["lineup-next/api"],
                "curl_headers": [
                    "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                    "Referer: https://www.bloomberg.com/",
                    "Accept: */*",
                ],
                "captcha_detection": ["Are you a robot", "unusual activity"],
                "circuit_breaker": {
                    "failure_threshold": 2,
                    "reset_timeout": 15 * 60,  # 15 minutes
                    "backoff_multiplier": 2.0,
                    "max_timeout": 4 * 60 * 60,  # 4 hours
                },
            },
            "tradingeconomics.com": {
                "rotate_user_agent": True,
                "browser_headers": True,
                "preserve_cookies": True,
                "use_curl": True,
                "curl_endpoints": ["ws/stream.ashx"],
                "curl_headers": [
                    "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                    "Referer: https://tradingeconomics.com/",
                    "Accept: */*",
                ],
                "captcha_detection": ["bot", "automated", "captcha"],
                "circuit_breaker": {
                    "failure_threshold": 2,
                    "reset_timeout": 15 * 60,  # 15 minutes
                    "backoff_multiplier": 2.0,
                    "max_timeout": 4 * 60 * 60,  # 4 hours
                },
            },
        }

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

    async def _read_body(
        self, reader: asyncio.StreamReader, content_length: int
    ) -> bytes:
        buffer = BytesIO()
        while len(buffer.getvalue()) < content_length:
            body = await reader.read(4096)
            buffer.write(body)
        return buffer.getvalue()

    def _get_domain_config(self, host: str) -> Dict[str, Any]:
        if host in self._special_domains:
            return self._special_domains[host]

        for domain, config in self._special_domains.items():
            pattern = domain.replace(".", r"\.")
            if re.match(f".*{pattern}.*", host):
                return config
        return {}

    def _prepare_headers(self, host: str, headers: Dict[str, str]) -> Dict[str, str]:
        """prepare request headers with domain specific customizations"""
        result_headers = headers.copy()
        config = self._get_domain_config(host)

        if config.get("rotate_user_agent", False):
            result_headers["User-Agent"] = random.choice(self._user_agents)
        else:
            result_headers["User-Agent"] = DEFAULT_USER_AGENT

        if config.get("browser_headers", False):
            browser_headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"https://{host}/",
                "Origin": f"https://{host}",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "DNT": "1",
                "Connection": "keep-alive",
            }
            for k, v in browser_headers.items():
                if k not in result_headers:
                    result_headers[k] = v

        result_headers.update(DEFAULT_HEADERS)
        result_headers["Host"] = host

        return result_headers

    def _extract_cookies(self, host: str, response_headers: HTTPHeaders) -> None:
        """extract cookies from response headers"""
        config = self._get_domain_config(host)
        if not config.get("preserve_cookies", False):
            return

        if host not in self._cookies:
            self._cookies[host] = {}

        set_cookie = response_headers.headers.get("Set-Cookie")
        if set_cookie:
            cookies = [set_cookie]
            for cookie in cookies:
                if "=" in cookie:
                    name, value = cookie.split("=", 1)
                    if ";" in value:
                        value = value.split(";")[0]
                    self._cookies[host][name.strip()] = value.strip()

    def _check_for_captcha(self, host: str, body: bytes) -> bool:
        """check if response has captcha challenge"""
        config = self._get_domain_config(host)
        captcha_phrases = config.get("captcha_detection", [])

        if not captcha_phrases:
            return False

        try:
            body_text = body.decode("utf-8", errors="replace")
            for phrase in captcha_phrases:
                if phrase in body_text:
                    logger.warning(
                        "CAPTCHA detected", extra={"host": host, "phrase": phrase}
                    )
                    return True
        except:
            pass

        return False

    def _get_circuit_breaker(self, host: str) -> Optional[CircuitBreaker]:
        """get or create domain-specific circuit breaker"""
        if host in self._circuit_breakers:
            return self._circuit_breakers[host]

        config = self._get_domain_config(host)
        cb_config = config.get("circuit_breaker")

        if not cb_config:
            return None

        if self.health_service:
            breaker = self.health_service.get_circuit_breaker(
                name=f"http_{host}", **cb_config
            )
        else:
            breaker = CircuitBreaker(name=host, **cb_config)

        self._circuit_breakers[host] = breaker
        return breaker

    def _should_use_curl(self, host: str, url: str) -> bool:
        """Determine if curl should be used for this domain and endpoint"""
        config = self._get_domain_config(host)

        if not config.get("use_curl", False):
            return False

        curl_endpoints = config.get("curl_endpoints", [])
        if not curl_endpoints:
            return True  # Use curl for all endpoints if no specific ones listed

        # Check if any of the endpoints are in the URL
        return any(endpoint in url for endpoint in curl_endpoints)

    async def _fetch_with_curl(self, url: str, host: str) -> Tuple[HTTPHeaders, bytes]:
        """Fetch content using curl with domain-specific configurations"""
        config = self._get_domain_config(host)

        # Base curl command
        cmd = ["curl", "-s", url]

        # Add headers from config
        curl_headers = config.get("curl_headers", [])
        for header in curl_headers:
            cmd.extend(["-H", header])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if stderr:
                logger.warning(
                    "Curl reported errors",
                    extra={
                        "stderr": stderr.decode("utf-8", errors="replace"),
                        "host": host,
                        "url": url,
                    },
                )

            # Create default headers
            response_headers = HTTPHeaders.from_bytes(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
            )
            return response_headers, stdout
        except Exception as e:
            logger.error(
                "Error executing curl",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "command": " ".join(cmd),
                    "host": host,
                    "url": url,
                },
            )
            raise HTTPClientError(detail=f"Error fetching with curl: {str(e)}")

    async def request(
        self, method: str, url: str, request_headers: Dict[str, str] | None = None
    ) -> Tuple[HTTPHeaders, bytes]:
        parsed_url = urlparse(url)
        host = parsed_url.netloc
        path = parsed_url.path if parsed_url.path else "/"
        if parsed_url.query:
            path += "?" + parsed_url.query

        circuit_breaker = self._get_circuit_breaker(host)

        # Check if we should use curl for this domain/endpoint
        if self._should_use_curl(host, url):
            return await self._fetch_with_curl(url, host)

        async def make_request():
            headers = self._prepare_headers(host, request_headers or {})

            request = (
                f"{method} {path} HTTP/1.1\r\n"
                f"{chr(10).join(f'{k}: {v}' for k, v in headers.items())}\r\n\r\n"
            )

            try:
                async with self.connection_pool.get_connection(host) as conn:
                    conn.writer.write(request.encode())
                    await conn.writer.drain()
                    header_data = await conn.reader.readuntil(b"\r\n\r\n")
                    response_headers = HTTPHeaders.from_bytes(header_data)

                    self._extract_cookies(host, response_headers)

                    transfer_encoding = response_headers.headers.get(
                        "Transfer-Encoding", None
                    )
                    if not transfer_encoding:
                        transfer_encoding = response_headers.headers.get(
                            "transfer-encoding", None
                        )
                    if transfer_encoding:
                        body = await self._read_chunked_body(conn.reader)
                    else:
                        content_length = response_headers.headers.get(
                            "Content-Length", "0"
                        )
                        content_length = int(content_length)
                        body = await self._read_body(conn.reader, content_length)

                    if self._check_for_captcha(host, body):
                        if self.health_service:
                            self.health_service.update_service_health(
                                f"http_{host}",
                                state="degraded",
                                failure_count=1,
                                last_failure_time=time.time(),
                                last_error=f"CAPTCHA challenge detected on {host}",
                            )
                        raise CaptchaError(f"CAPTCHA challenge detected on {host}")

                    if self.health_service:
                        self.health_service.update_service_health(
                            f"https_{host}",
                            state="operational",
                            last_success_time=time.time(),
                        )

                    return response_headers, body

            except Exception as e:
                logger.error(
                    "HTTP Request error",
                    extra={
                        "error": str(e),
                        "url": url,
                        "error_type": e.__class__.__name__,
                    },
                )

                if self.health_service:
                    self.health_service.update_service_health(
                        f"https_{host}",
                        state="degraded",
                        failure_count=1,
                        last_failure_time=time.time(),
                        last_error=str(e),
                    )

                raise HTTPClientError(
                    detail=f"Failed to make HTTP request: {str(e)}", host=host
                )

        async def request_fallback():
            logger.info("Using fallback for HTTP request", extra={"host": host})

            # Try curl fallback for any special domain
            config = self._get_domain_config(host)
            if config:
                try:
                    return await self._fetch_with_curl(url, host)
                except Exception as e:
                    logger.error(
                        "Fallback to curl also failed",
                        extra={
                            "error": str(e),
                            "host": host,
                            "url": url,
                            "error_type": e.__class__.__name__,
                        },
                    )

            raise ServiceUnavailableError(
                service=f"https_{host}",
                detail=f"Service {host} is temporarily unavailable",
                retry_after=60,
            )

        if circuit_breaker:
            cache_key = f"{host}_{path}"
            try:
                return await circuit_breaker.execute(
                    make_request,
                    cache_key=cache_key,
                )
            except CaptchaError as e:
                # If we get a captcha, try the fallback
                logger.warning(
                    "CAPTCHA detected, trying fallback",
                    extra={"host": host, "url": url},
                )
                try:
                    return await request_fallback()
                except Exception:
                    raise HTTPClientError(detail=str(e), host=host)
            except Exception:
                # For other errors, try the fallback
                return await request_fallback()
        else:
            try:
                return await make_request()
            except Exception:
                return await request_fallback()

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """get status of all circuit breakers"""
        return {
            host: breaker.get_state()
            for host, breaker in self._circuit_breakers.items()
        }
