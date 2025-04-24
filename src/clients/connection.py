import asyncio
import os
import ssl
import itertools
from collections import defaultdict
import time
import threading
from contextlib import asynccontextmanager
from asyncio import Queue, QueueFull, QueueEmpty
from src.core.config import settings
from src.core.logging import LogContext, PerformanceLogger

logger = LogContext(__name__)


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
        self.created_at = time.time()
        self.last_used_at = time.time()
        self.use_count = 0

        logger.debug(
            "Connection created", extra={"connection_id": self.id, "host": host}
        )

    async def close(self):
        try:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=1.0)
                logger.debug(
                    "Connection closed",
                    extra={
                        "connection_id": self.id,
                        "host": self.host,
                        "lifetime_s": round(time.time() - self.created_at, 2),
                        "use_count": self.use_count,
                    },
                )
            except asyncio.TimeoutError as e:
                logger.warning(
                    "Timeout waiting for connection to close",
                    extra={
                        "error": str(e),
                        "id": self.id,
                        "error_type": e.__class__.__name__,
                    },
                )
        except Exception as e:
            logger.warning(
                "Error closing connection",
                extra={
                    "error": str(e),
                    "id": self.id,
                    "error_type": e.__class__.__name__,
                },
            )


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
            self.connection_stats = defaultdict(
                lambda: {"created_at": 0, "reused": 0, "errors": 0}
            )
            logger.info(
                "Initialized ConnectionPool",
                extra={
                    "ID": id(self),
                    "process_id": os.getpid(),
                    "pool_size": pool_size,
                    "max_concurrent_requests": max_concurrent_requests,
                },
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
            conn = PooledConnection(reader, writer, host)
            self.connection_stats[host]["created"] += 1
            return conn
        except Exception as e:
            self.connection_stats[host]["errors"] += 1
            logger.error(
                "Error creating connection",
                extra={
                    "error": str(e),
                    "host": host,
                    "error_type": e.__class__.__name__,
                },
            )
            raise

    @asynccontextmanager
    async def get_connection(self, host: str):
        pool = self.pools[host]
        semaphore = self.host_semaphores[host]
        conn = None

        if pool.qsize() <= self.pool_size * 0.2:
            logger.debug(
                "Connection pool utilization high",
                extra={
                    "host": host,
                    "available": pool.qsize(),
                    "capacity": self.pool_size,
                    "utilization_pct": round(
                        (self.pool_size - pool.qsize()) / self.pool_size * 100
                    ),
                },
            )
        async with semaphore:
            start_time = time.time()
            try:
                conn = await self.get_or_create_connection(pool, host)
                conn.in_use = True
                conn.last_used_at = time.time()
                conn.use_count += 1

                acquisition_time = (time.time() - start_time) * 1000
                if acquisition_time > 100:
                    logger.warning(
                        "Slow connection acquisition",
                        extra={
                            "host": host,
                            "connection_id": conn.id,
                            "acquisition_ms": round(acquisition_time, 2),
                        },
                    )
                yield conn
            finally:
                if conn:
                    conn.in_use = False
                    try:
                        if not conn.writer.is_closing():
                            pool.put_nowait(conn)
                            logger.debug(
                                "Connection returned to pool",
                                extra={
                                    "connection_id": conn.id,
                                    "host": host,
                                    "usage_ms": round(
                                        (time.time() - conn.last_used_at) * 1000, 2
                                    ),
                                    "use_count": conn.use_count,
                                },
                            )
                        else:
                            try:
                                await asyncio.wait_for(conn.close(), timeout=0.5)
                            except asyncio.TimeoutError as e:
                                logger.warning(
                                    "Timeout closing connection",
                                    extra={
                                        "error": str(e),
                                        "connection_id": conn.id,
                                        "error_type": e.__class__.__name__,
                                    },
                                )
                            except Exception as e:
                                logger.warning(
                                    "Error closing connection",
                                    extra={
                                        "error": str(e),
                                        "connection_id": conn.id,
                                        "error_type": e.__class__.__name__,
                                    },
                                )

                    except QueueFull:
                        logger.debug(
                            "Pool full. Closing connection",
                            extra={"host": host, "connection_id": conn.id},
                        )
                        await conn.close()

    async def get_or_create_connection(
        self, pool: Queue, host: str
    ) -> PooledConnection:
        try:
            conn = pool.get_nowait()
            self.connection_stats[host]["reused"] += 1

            if conn.writer.is_closing():
                try:
                    await asyncio.wait_for(conn.close(), timeout=0.5)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(
                        "Error closing old connection",
                        extra={
                            "error": str(e),
                            "connection_id": conn.id,
                            "error_type": e.__class__.__name__,
                        },
                    )
                return await self._create_connection(host)
            idle_time = time.time() - conn.last_used_at
            if idle_time > 60:
                logger.debug(
                    "Reusing idle connection",
                    extra={
                        "connection_id": conn.id,
                        "host": host,
                        "idle_time_ms": round(idle_time, 2),
                        "use_count": conn.use_count,
                    },
                )
            return conn
        except QueueEmpty:
            if pool.qsize() < self.pool_size:
                return await self._create_connection(host)
            return await pool.get()

    async def async_reset_pools(self):
        with PerformanceLogger(logger, "reset_pools"):
            close_tasks = []
            for host, pool in self.pools.items():
                connection_count = 0
                while not pool.empty():
                    try:
                        conn = pool.get_nowait()
                        connection_count += 1
                        close_tasks.append(asyncio.wait_for(conn.close(), timeout=0.5))
                    except QueueEmpty:
                        break
                    except Exception as e:
                        logger.warning(
                            "Error getting connection from pool",
                            extra={
                                "error": str(e),
                                "host": host,
                                "pool": pool,
                                "error_type": e.__class__.__name__,
                            },
                        )
                logger.info(
                    "Closing connection pool",
                    extra={
                        "host": host,
                        "connections_closed": connection_count,
                        "total_created": self.connection_stats[host]["created"],
                        "total_resused": self.connection_stats[host]["reused"],
                        "total_errors": self.connection_stats[host]["errors"],
                    },
                )

            if close_tasks:
                try:
                    await asyncio.gather(*close_tasks, return_exceptions=True)
                except Exception as e:
                    logger.warning(
                        "Error during connection pool cleanup",
                        extra={
                            "error": str(e),
                            "tasks": close_tasks,
                            "error_type": e.__class__.__name__,
                        },
                    )

            self.pools = defaultdict(lambda: asyncio.Queue(maxsize=self.pool_size))
            self.connection_stats = defaultdict(
                lambda: {"created": 0, "reused": 0, "errors": 0}
            )

    def reset_pools(self):
        for host, stats in self.connection_stats.items():
            logger.info(
                "Connection pool stats before reset",
                extra={
                    "host": host,
                    "total_created": stats["created"],
                    "total_resused": stats["reused"],
                    "total_errors": stats["errors"],
                },
            )
        self.pools = defaultdict(lambda: asyncio.Queue(maxsize=self.pool_size))
        self.connection_stats = defaultdict(
            lambda: {"created": 0, "reused": 0, "errors": 0}
        )
