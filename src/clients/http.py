import asyncio
import subprocess
import logging
import random
import re
import time
from typing import Dict, Tuple, Any, Callable, Awaitable, TypeVar
from io import BytesIO
from urllib.parse import urlparse

from src.models.http import HTTPHeaders
from src.clients.connection import ConnectionPool
from src.constants import DEFAULT_HEADERS, DEFAULT_USER_AGENT
from src.core.exceptions import HTTPClientError, ServiceUnavailableError

logger = logging.getLogger(__name__)

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
                    logger.info(f"Circuit {self.name} OPEN - using cached data")
                    return self.cache[cache_key]
                raise HTTPClientError(detail=f"Circuit {self.name} is OPEN")

            logger.info(f"Circuit {self.name} switching to HALF_OPEN")
            self.state = CircuitState.HALF_OPEN

        try:
            result = await func(*args, **kwargs)

            if self.state == CircuitState.HALF_OPEN:
                logger.info(f"Circuit {self.name} recovery successful - CLOSED")
                self._reset()
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

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
                logger.warning(
                    f"Circuit {self.name} OPEN - threshold reached ({self.failure_count})"
                )
                self.state = CircuitState.OPEN

            elif self.state == CircuitState.HALF_OPEN:
                logger.warning(f"Circuit {self.name} OPEN - test failed")
                self.state = CircuitState.OPEN
                self.current_timeout = min(
                    self.current_timeout * self.backoff_multiplier, self.max_timeout
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
        self._special_domains = {
            "www.bloomberg.com": {
                "rotate_user_agent": True,
                "browser_headers": True,
                "preserve_cookies": True,
                "captcha_detection": ["Are you a robot", "unusual activity"],
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

        if host == "www.bloomberg.com":
            return {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
                "Referer": "https://www.bloomberg.com/",
                "Accept": "*/*",
                "Host": host,
            }

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
                    logger.warning(f"CAPTCHA detected in response from {host}")
                    return True
        except:
            pass

        return False

    def _get_circuit_breaker(self, host: str) -> CircuitBreaker | None:
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

    async def _fetch_with_curl(self) -> Tuple[HTTPHeaders, bytes]:
        """subprocess to curl to get around fingerprinting"""
        cmd = [
            "curl",
            "-s",
            "https://www.bloomberg.com/lineup-next/api/stories?limit=25&pageNumber=1&types=ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS",
            "-H",
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "-H",
            "Referer: https://www.bloomberg.com/",
            "-H",
            "Accept: */*",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            response_headers = HTTPHeaders.from_bytes(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
            )
            return response_headers, stdout
        except Exception as e:
            logger.error(f"Error executing curl: {str(e)}")
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

        if host == "www.bloomberg.com" and "lineup-next/api" in url:
            return await self._fetch_with_curl()

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
                            self.health_service.update_health_service(
                                f"http_{host}",
                                state="degraded",
                                failure_count=1,
                                last_failure_time=time.time(),
                                last_error=f"CAPTCHA challenge detected on {host}",
                            )
                        raise CaptchaError(f"CAPTCHA challenge detected on {host}")

                    if self.health_service:
                        self.health_service.update_health_service(
                            f"https_{host}",
                            state="operational",
                            last_success_time=time.time(),
                        )

                    return response_headers, body

            except Exception as e:
                logger.error(f"HTTP request error for {url}: {str(e)}")

                if self.health_service:
                    self.health_service.update_health_service(
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
            logger.info(f"Using fallback for HTTP request to {host}")
            if host == "www.bloomberg.com" and "lineup-next/api" not in url:
                try:
                    return await self._fetch_with_curl()
                except Exception as e:
                    logger.error(f"Fallback to curl also failed: {str(e)}")

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
                    fallback=request_fallback,
                )
            except CaptchaError as e:
                raise HTTPClientError(detail=str(e), host=host)

        else:
            return await make_request()

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """get status of all circuit breakers"""
        return {
            host: breaker.get_state()
            for host, breaker in self._circuit_breakers.items()
        }
