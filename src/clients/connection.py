import asyncio
import ssl
import logging
import itertools
from collections import defaultdict
from typing import Dict
from contextlib import asynccontextmanager
from asyncio import Queue, QueueFull, QueueEmpty
from src.core.config import settings

logger = logging.getLogger(__name__)


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
        logger.debug(f"Created connection {self.id} for {host}")

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class ConnectionPool:
    def __init__(self, pool_size: int = settings.POOL_SIZE):
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
            logger.debug(f"Using connection {conn.id} for {host}")
            yield conn
        finally:
            if conn:
                conn.in_use = False
                try:
                    pool.put_nowait(conn)
                    logger.debug(f"Returned connection {conn.id} to pool for {host}")
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
