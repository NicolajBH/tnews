import asyncio
import os
import ssl
import logging
import time
import itertools
from collections import defaultdict
import threading
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


class ReusableConnection:
    def __init__(self, host, port=443):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.id = next(PooledConnection._id_counter)
        self.in_use = False
        self.last_used = time.time()
        self.expiry = 60

    async def ensure_connected(self):
        current_loop = asyncio.get_running_loop()
        current_time = time.time()

        if current_time - self.last_used > self.expiry:
            logger.debug(f"Connection {self.id} for {self.host} expired, will recreate")
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
                self.writer = None

        if (
            self.writer is None
            or self.writer.is_closing()
            or hasattr(self.writer, "_loop")
            and self.writer._loop is not current_loop
        ):
            if self.writer is not None:
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                except Exception:
                    pass

            ssl_context = ssl.create_default_context()
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port, ssl=ssl_context
            )
            logger.debug(
                f"Created/recreated connection {self.id} for {self.host} in loop {id(current_loop)}"
            )
        self.last_used = current_time
        return self

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            self.reader = None


class ConnectionPool:
    _instances = {}
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        process_id = os.getpid()

        with cls._lock:
            if process_id not in cls._instances:
                cls._instances[process_id] = super(ConnectionPool, cls).__new__(cls)
                cls._instances[process_id]._initialized = False

        return cls._instances[process_id]

    def __init__(
        self,
        pool_size: int = settings.POOL_SIZE,
        max_concurrent_requests: int = settings.MAX_CONCURRENT_REQUEST,
    ):
        if not hasattr(self, "_initialized") or not self._initialized:
            self.pool_size = pool_size
            self.pools = defaultdict(lambda: asyncio.Queue(maxsize=pool_size))
            self.host_semaphores = defaultdict(
                lambda: asyncio.Semaphore(max_concurrent_requests)
            )
            self.ssl_context = ssl.create_default_context()
            self._initialized = True
            logger.info(
                f"Initialized ConnectionPool with ID {id(self)} in process {os.getpid()}"
            )

    @asynccontextmanager
    async def get_connection(self, host: str):
        pool = self.pools[host]
        semaphore = self.host_semaphores[host]
        conn = None

        async with semaphore:
            try:
                conn = await self.get_or_create_connection(pool, host)
                conn.in_use = True
                logger.debug(f"Using connection {conn.id} for {host}")
                yield conn
            finally:
                if conn:
                    conn.in_use = False
                    try:
                        if conn.writer and not conn.writer.is_closing():
                            pool.put_nowait(conn)
                            logger.debug(
                                f"Returned connection {conn.id} to pool for {host}"
                            )
                        else:
                            logger.debug(
                                f"Connection {conn.id} closed, not returning to pool"
                            )
                            await conn.close()
                    except QueueFull:
                        logger.debug(
                            f"Pool for {host} full, closing connection {conn.id}"
                        )

    async def get_or_create_connection(
        self, pool: Queue, host: str
    ) -> ReusableConnection:
        try:
            logger.debug(
                f"Attempting to get existing connection for {host}, pool size: {pool.qsize()}/{self.pool_size}"
            )
            conn = pool.get_nowait()
            await conn.ensure_connected()
            return conn
        except QueueEmpty:
            logger.debug(
                f"No available connections for {host}, creating new one. Pool size: {pool.qsize()}/{self.pool_size}"
            )
            conn = ReusableConnection(host)
            await conn.ensure_connected()
            return conn
