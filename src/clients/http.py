import asyncio
import logging
from typing import Dict, Tuple
from io import BytesIO
from src.models.http import HTTPHeaders
from src.clients.connection import ConnectionPool
from src.constants import DEFAULT_HEADERS, DEFAULT_USER_AGENT
from src.core.exceptions import HTTPClientError

logger = logging.getLogger(__name__)


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
        headers.update(DEFAULT_HEADERS)
        headers.update({"Host": host, "User-Agent": DEFAULT_USER_AGENT})

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
                body = await self._read_chunked_body(conn.reader)

                return response_headers, body
        except Exception as e:
            logger.error(f"HTTP request error for {url}: {str(e)}")
            raise HTTPClientError(
                detail="Failed to make HTTP request: {str(e)}", host=host
            )
