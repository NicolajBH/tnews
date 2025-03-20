import asyncio
import os
import ssl
import logging
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
        try:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for connection {self.id} to close")
        except Exception as e:
            logger.warning(f"Error closing connection {self.id}: {e}")


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

    @classmethod
    def _reset_for_testing(cls):
        with cls._lock:
            process_id = os.getpid()
            if process_id in cls._instances:
                del cls._instances[process_id]

    async def _create_connection(self, host: str) -> PooledConnection:
        try:
            reader, writer = await asyncio.open_connection(
                host, 443, ssl=self.ssl_context
            )
            return PooledConnection(reader, writer, host)
        except Exception as e:
            logger.error(f"Error creating connection to {host}: {str(e)}")
            raise

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
                        if not conn.writer.is_closing():
                            pool.put_nowait(conn)
                            logger.debug(
                                f"Returned connection {conn.id} to pool for {host}"
                            )
                        else:
                            logger.debug(
                                f"Connection {conn.id} closed, not returning to pool"
                            )
                            try:
                                await asyncio.wait_for(conn.close(), timeout=0.5)
                            except asyncio.TimeoutError:
                                logger.warning(f"Timeout closing connection {conn.id}")
                            except Exception as e:
                                logger.warning(
                                    f"Error closing connection {conn.id}: {e}"
                                )

                    except QueueFull:
                        logger.debug(
                            f"Pool for {host} full, closing connection {conn.id}"
                        )
                        await conn.close()

    async def get_or_create_connection(
        self, pool: Queue, host: str
    ) -> PooledConnection:
        try:
            logger.debug(
                f"Attempting to get existing connection for {host}, pool size: {pool.qsize()}/{self.pool_size}"
            )
            conn = pool.get_nowait()

            if conn.writer.is_closing():
                logger.debug(
                    f"Connection {conn.id} for {host} was closed, creating new one"
                )
                try:
                    await asyncio.wait_for(conn.close(), timeout=0.5)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Error closing old connection {conn.id}: {e}")
                return await self._create_connection(host)
            return conn
        except QueueEmpty:
            logger.debug(
                f"No available connections for {host}, creating new one. Pool size: {pool.qsize()}/{self.pool_size}"
            )
            if pool.qsize() < self.pool_size:
                return await self._create_connection(host)
            logger.debug(
                f"Pool is at capacity, waiting for connection to be returned for {host}"
            )
            return await pool.get()

    async def async_reset_pools(self):
        logger.info(f"Resetting connection pools for process: {os.getpid()}")

        close_tasks = []
        for host, pool in self.pools.items():
            while not pool.empty():
                try:
                    conn = pool.get_nowait()
                    close_tasks.append(asyncio.wait_for(conn.close(), timeout=0.5))
                except QueueEmpty:
                    break
                except Exception as e:
                    logger.warning(f"Error getting connection from pool: {e}")

        if close_tasks:
            try:
                await asyncio.gather(*close_tasks, return_exceptions=True)
            except Exception as e:
                logger.warning(f"Error during connection pool cleanup: {e}")

        self.pools = defaultdict(lambda: asyncio.Queue(maxsize=self.pool_size))

    def reset_pools(self):
        self.pools = defaultdict(lambda: asyncio.Queue(maxsize=self.pool_size))
