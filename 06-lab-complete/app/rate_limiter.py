"""
Rate limiting (tiêu chí 7).

Yêu cầu:
  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429, nên kèm header Retry-After
  • State lưu trong Redis để mọi worker / instance dùng chung và vẫn còn sau khi
    restart agent (script chấm sẽ restart agent để kiểm tra)
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Không lưu API key gốc trong Redis — chỉ lưu hash.
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    limit = settings.rate_limit_per_minute
    try:
        # Sliding window bằng sorted set: score = thời điểm request.
        pipe = r.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)  # xoá request ngoài cửa sổ
        pipe.zcard(bucket)                                       # đếm request trong 60s qua
        pipe.zrange(bucket, 0, 0, withscores=True)               # request cũ nhất (tính Retry-After)
        _, count, oldest = pipe.execute()

        if count >= limit:
            retry = WINDOW_SECONDS - (now - oldest[0][1]) if oldest else WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests / {WINDOW_SECONDS}s",
                headers={"Retry-After": str(max(1, math.ceil(retry)))},
            )

        pipe = r.pipeline()
        pipe.zadd(bucket, {f"{now}-{uuid.uuid4().hex[:8]}": now})
        pipe.expire(bucket, WINDOW_SECONDS + 5)
        pipe.execute()
    except redis.RedisError:
        # Không có Redis thì không biết đã gọi bao nhiêu lần → từ chối an toàn (fail closed).
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
