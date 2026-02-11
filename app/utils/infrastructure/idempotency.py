import json
import logging
import hashlib
from functools import wraps
from typing import Callable, Optional, Any

import redis.asyncio as redis
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from app.core.config import settings
from app.utils.redis_pool import get_redis

log = logging.getLogger(__name__)


IDEMPOTENCY_HEADER = "X-Idempotency-Key"
IDEMPOTENCY_PREFIX = "idempotency"


class IdempotencyLock:
    
    def __init__(self, key: str, ttl: int = 86400):
        self.key = f"{IDEMPOTENCY_PREFIX}:{key}"
        self.lock_key = f"{self.key}:lock"
        self.ttl = ttl
        self.redis: Optional[redis.Redis] = None
        self.acquired = False
    
    async def __aenter__(self):
        self.redis = await get_redis()
        self.acquired = await self.redis.set(
            self.lock_key,
            "1",
            nx=True,
            ex=30,
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired and self.redis:
            await self.redis.delete(self.lock_key)
    
    async def get_cached_response(self) -> Optional[dict]:
        if self.redis is None:
            return None
        cached = await self.redis.get(self.key)
        if cached:
            return json.loads(cached)
        return None
    
    async def cache_response(self, response_data: dict, status_code: int = 200):
        if self.redis is None:
            return
        cache_data = {
            "status_code": status_code,
            "body": response_data,
        }
        await self.redis.setex(self.key, self.ttl, json.dumps(cache_data))


def idempotent(
    ttl: int = 86400,
    required: bool = False,
    key_prefix: str = "",
):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get('request')
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                return await func(*args, **kwargs)
            
            idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
            
            if not idempotency_key:
                if required:
                    raise HTTPException(
                        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "ok": False,
                            "error": f"Missing required header: {IDEMPOTENCY_HEADER}",
                            "details": None,
                        }
                    )
                return await func(*args, **kwargs)
            
            if len(idempotency_key) > 256 or not idempotency_key.replace("-", "").replace("_", "").isalnum():
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "ok": False,
                        "error": "Invalid idempotency key format",
                        "details": None,
                    }
                )
            
            user = getattr(request.state, 'user', None)
            user_id = user.id if user and hasattr(user, 'id') else "anon"
            
            full_key = f"{key_prefix}:{user_id}:{idempotency_key}" if key_prefix else f"{user_id}:{idempotency_key}"
            
            try:
                async with IdempotencyLock(full_key, ttl) as lock:
                    cached = await lock.get_cached_response()
                    if cached:
                        log.info("Returning cached idempotent response: key=%s", full_key)
                        return JSONResponse(
                            content=cached["body"],
                            status_code=cached["status_code"],
                            headers={"X-Idempotency-Replayed": "true"},
                        )
                    
                    if not lock.acquired:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "ok": False,
                                "error": "Duplicate request in progress. Please retry.",
                                "details": None,
                            }
                        )
                    
                    result = await func(*args, **kwargs)
                    
                    if isinstance(result, Response):
                        if hasattr(result, 'body'):
                            try:
                                body = json.loads(result.body)
                                await lock.cache_response(body, result.status_code)
                            except (json.JSONDecodeError, TypeError):
                                pass
                    elif isinstance(result, dict):
                        await lock.cache_response(result, 200)
                    
                    return result
                    
            except HTTPException:
                raise
            except Exception as e:
                log.error("Idempotency check failed: %s", e, exc_info=True)
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator
