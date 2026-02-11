"""
Redis Connection Pool Module
============================
Centralized async Redis connection pool with:
- Health checks to detect stale connections
- Socket timeouts to prevent hung operations
- Retry logic for transient failures
- Proper lifecycle management
"""

import logging
from typing import Optional

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import (
    BusyLoadingError,
    ConnectionError,
    TimeoutError,
)

from app.core.config import settings

log = logging.getLogger(__name__)

_redis_pool: Optional[redis.ConnectionPool] = None

# Pool configuration constants
POOL_MAX_CONNECTIONS = 50       # Max concurrent connections
SOCKET_TIMEOUT = 5.0            # Timeout for read/write operations (seconds)
SOCKET_CONNECT_TIMEOUT = 5.0    # Timeout for establishing connection (seconds)
HEALTH_CHECK_INTERVAL = 30      # Seconds between connection health checks
RETRY_ATTEMPTS = 3              # Number of retry attempts on transient errors


def _create_pool() -> redis.ConnectionPool:
    """
    Creates a configured Redis connection pool.
    
    Key configurations:
    - max_connections: Limits concurrent connections to avoid overwhelming Redis
    - socket_timeout: Prevents hung operations on network issues
    - socket_connect_timeout: Fails fast if Redis is unreachable
    - health_check_interval: Periodically verifies connection liveness, 
      automatically reconnects stale connections before use
    - decode_responses: Returns str instead of bytes for convenience
    """
    return redis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=POOL_MAX_CONNECTIONS,
        socket_timeout=SOCKET_TIMEOUT,
        socket_connect_timeout=SOCKET_CONNECT_TIMEOUT,
        health_check_interval=HEALTH_CHECK_INTERVAL,
        decode_responses=True,
    )


def _create_retry() -> Retry:
    """
    Creates a retry configuration for transient Redis errors.
    
    Uses exponential backoff (cap=0.5s) for these recoverable errors:
    - ConnectionError: Network blips, Redis restarts
    - TimeoutError: Temporary slowness
    - BusyLoadingError: Redis loading dataset after restart
    """
    return Retry(
        retries=RETRY_ATTEMPTS,
        backoff=ExponentialBackoff(cap=0.5, base=0.1),
        supported_errors=(ConnectionError, TimeoutError, BusyLoadingError),
    )


async def get_redis() -> redis.Redis:
    """
    Returns a Redis client backed by the shared connection pool.
    
    The pool is lazily initialized on first call. Each invocation returns
    a lightweight client object that borrows connections from the pool
    as needed—no new connections are created per call.
    
    The retry configuration automatically handles transient failures.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = _create_pool()
        log.info(
            "Redis connection pool initialized "
            f"(max_connections={POOL_MAX_CONNECTIONS}, "
            f"health_check_interval={HEALTH_CHECK_INTERVAL}s)"
        )
    
    return redis.Redis(
        connection_pool=_redis_pool,
        retry=_create_retry(),
        retry_on_error=[ConnectionError, TimeoutError, BusyLoadingError],
    )


async def close_redis():
    """
    Gracefully shuts down the connection pool.
    
    Call this during application shutdown (e.g., FastAPI lifespan event)
    to cleanly close all pooled connections.
    """
    global _redis_pool
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
        log.info("Redis connection pool closed")
