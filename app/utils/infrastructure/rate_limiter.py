import logging
import time
from functools import wraps
from typing import Callable, Optional

from fastapi import HTTPException, Request, Response
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.core.config import settings
from app.utils.infrastructure.redis_pool import get_redis

log = logging.getLogger(__name__)


async def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
) -> tuple[bool, int, int]:
    r = await get_redis()
    now = time.time()
    window_start = now - window_seconds
    
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 1)
    
    results = await pipe.execute()
    request_count = results[2]
    
    if request_count > max_requests:
        oldest = await r.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_time = oldest[0][1]
            retry_after = int(oldest_time + window_seconds - now) + 1
        else:
            retry_after = window_seconds
        
        remaining = 0
        return False, remaining, max(1, retry_after)
    
    remaining = max_requests - request_count
    return True, remaining, 0


def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_prefix: str = "ratelimit",
    key_func: Optional[Callable[[Request], str]] = None,
):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not getattr(settings, 'RATE_LIMIT_ENABLED', True):
                return await func(*args, **kwargs)
            
            request: Optional[Request] = kwargs.get('request')
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                log.warning("rate_limit decorator: no Request object found")
                return await func(*args, **kwargs)
            
            if key_func:
                user_key = key_func(request)
            else:
                client_ip = request.client.host if request.client else "unknown"
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    client_ip = forwarded.split(",")[0].strip()
                user_key = client_ip
            
            redis_key = f"{key_prefix}:{user_key}"
            
            try:
                allowed, remaining, retry_after = await check_rate_limit(
                    redis_key, max_requests, window_seconds
                )
            except Exception as e:
                log.error("Rate limit check failed: %s", e, exc_info=True)
                return await func(*args, **kwargs)
            
            if not allowed:
                log.warning(
                    "Rate limit exceeded: key=%s, limit=%d/%ds",
                    redis_key, max_requests, window_seconds
                )
                raise HTTPException(
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "ok": False,
                        "error": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        "details": {
                            "retry_after": retry_after,
                            "limit": max_requests,
                            "window": window_seconds,
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            
            response = await func(*args, **kwargs)
            
            if isinstance(response, Response):
                response.headers["X-RateLimit-Limit"] = str(max_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(int(time.time()) + window_seconds)
            
            return response
        
        return wrapper
    return decorator


def get_user_key(request: Request) -> str:
    user = getattr(request.state, 'user', None)
    if user and hasattr(user, 'id'):
        return f"user:{user.id}"
    
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return f"ip:{client_ip}"
