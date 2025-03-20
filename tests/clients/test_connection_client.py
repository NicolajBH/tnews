import pytest
import asyncio
from unittest.mock import MagicMock, patch
from src.clients.connection import ConnectionPool


@pytest.fixture
async def reset_connection_pool():
    """
    Reset the connection pool singleton between tests
    """
    ConnectionPool._reset_for_testing()
    yield
    pool = ConnectionPool()
    await pool.async_reset_pools()
    ConnectionPool._reset_for_testing()


@pytest.mark.asyncio
async def test_pool_initialization(reset_connection_pool):
    """Test that the connection pool initialized with the correct settings"""
    connection_pool = ConnectionPool(pool_size=5, max_concurrent_requests=8)
    assert connection_pool._initialized
    assert connection_pool.pool_size == 5
    test_host = "example.com"
    assert connection_pool.host_semaphores[test_host]._value == 8


@pytest.mark.asyncio
async def test_concurrent_connection_limits(reset_connection_pool):
    """Test that the connection pool respects concurrency limits"""
    pool = ConnectionPool(pool_size=10, max_concurrent_requests=2)
    host = "example.com"
    active_connections = 0
    max_active = 0
    lock = asyncio.Lock()

    async def use_connection(i):
        nonlocal active_connections, max_active
        with patch("asyncio.open_connection") as mock_open:
            mock_reader = MagicMock(spec=asyncio.StreamReader)
            mock_writer = MagicMock(spec=asyncio.StreamWriter)
            mock_writer.is_closing.return_value = False
            mock_open.return_value = (mock_reader, mock_writer)

            async with pool.get_connection(host):
                async with lock:
                    active_connections += 1
                    max_active = max(max_active, active_connections)

                await asyncio.sleep(0.1)

                async with lock:
                    active_connections -= 1

            return i

    results = await asyncio.gather(*[use_connection(i) for i in range(5)])

    assert set(results) == {0, 1, 2, 3, 4}
    assert max_active <= 2


@pytest.mark.asyncio
@patch("asyncio.open_connection")
async def test_connection_creation_and_reuse(
    mock_open_connection, reset_connection_pool
):
    """Test that connections are created and reused properly"""
    mock_reader = MagicMock(spec=asyncio.StreamReader)
    mock_writer = MagicMock(spec=asyncio.StreamWriter)
    mock_writer.is_closing.return_value = False
    mock_open_connection.return_value = (mock_reader, mock_writer)

    pool = ConnectionPool(pool_size=2, max_concurrent_requests=3)
    host = "example.com"

    async with pool.get_connection(host) as conn:
        assert conn.reader == mock_reader
        assert conn.writer == mock_writer
        assert conn.host == host
        assert conn.in_use
        first_conn_id = conn.id

        mock_open_connection.assert_called_once_with(host, 443, ssl=pool.ssl_context)

    mock_open_connection.reset_mock()

    async with pool.get_connection(host) as conn2:
        assert conn2.reader == mock_reader
        assert conn2.writer == mock_writer
        assert conn2.id == first_conn_id
        assert conn2.in_use

        mock_open_connection.assert_not_called()


@pytest.mark.asyncio
@patch("asyncio.open_connection")
async def test_connection_pool_exhaustion(mock_open_connection, reset_connection_pool):
    """Test that the connection pool respects pool size limit"""

    def create_mock_connection(*args, **kwargs):
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.is_closing.return_value = False
        return reader, writer

    mock_open_connection.side_effect = create_mock_connection

    pool = ConnectionPool(pool_size=2, max_concurrent_requests=5)
    host = "example.com"

    async def get_connections(count):
        managers = []
        connections = []
        connection_ids = []

        for _ in range(count):
            cm = pool.get_connection(host)
            managers.append(cm)
            conn = await cm.__aenter__()
            connections.append(conn)
            connection_ids.append(conn.id)

        return managers, connections, connection_ids

    async def release_connections(managers):
        for cm in managers:
            await cm.__aexit__(None, None, None)

    number_connections = 3
    managers1, _, conn_ids1 = await get_connections(number_connections)
    assert len(set(conn_ids1)) == number_connections
    await release_connections(managers1)

    managers2, _, conn_ids2 = await get_connections(number_connections)
    assert len(set(conn_ids2)) == number_connections
    await release_connections(managers2)

    assert conn_ids2[:2] == conn_ids1[:2]  # reuse first 2 connections(pool size 2)
    assert conn_ids2[-1] not in conn_ids1  # 3rd connection is new
    assert mock_open_connection.call_count == 4  # initial 3 connections and 1 new
