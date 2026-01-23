import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import HTTPException

from app.core.config import settings

log = logging.getLogger(__name__)

_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


LOCK_PREFIX = "lock"


class AdvisoryLock:
    
    def __init__(
        self,
        name: str,
        timeout: int = 30,
        retry_count: int = 3,
        retry_delay: float = 0.5,
    ):
        self.name = f"{LOCK_PREFIX}:{name}"
        self.timeout = timeout
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.token: Optional[str] = None
        self.redis: Optional[redis.Redis] = None
    
    async def acquire(self) -> bool:
        import uuid
        self.token = str(uuid.uuid4())
        self.redis = await get_redis()
        
        for attempt in range(self.retry_count):
            acquired = await self.redis.set(
                self.name,
                self.token,
                nx=True,
                ex=self.timeout,
            )
            if acquired:
                log.debug("Lock acquired: %s", self.name)
                return True
            
            if attempt < self.retry_count - 1:
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        
        log.warning("Failed to acquire lock after %d attempts: %s", self.retry_count, self.name)
        return False
    
    async def release(self):
        if not self.redis or not self.token:
            return
        
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            await self.redis.eval(lua_script, 1, self.name, self.token)
            log.debug("Lock released: %s", self.name)
        except Exception as e:
            log.error("Failed to release lock %s: %s", self.name, e)
    
    async def extend(self, additional_seconds: int = 30) -> bool:
        if not self.redis or not self.token:
            return False
        
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = await self.redis.eval(
                lua_script, 1, self.name, self.token, str(additional_seconds)
            )
            return result == 1
        except Exception as e:
            log.error("Failed to extend lock %s: %s", self.name, e)
            return False


@asynccontextmanager
async def advisory_lock(
    name: str,
    timeout: int = 30,
    retry_count: int = 3,
    retry_delay: float = 0.5,
    raise_on_fail: bool = True,
):
    lock = AdvisoryLock(name, timeout, retry_count, retry_delay)
    
    try:
        acquired = await lock.acquire()
        if not acquired:
            if raise_on_fail:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "ok": False,
                        "error": "Operation in progress. Please wait and retry.",
                        "details": None,
                    }
                )
            yield False
            return
        yield True
    finally:
        await lock.release()


async def with_lock(
    name: str,
    func,
    *args,
    timeout: int = 30,
    **kwargs,
):
    async with advisory_lock(name, timeout=timeout):
        return await func(*args, **kwargs)
