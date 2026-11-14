"""进程内轻量频率限制（滑动窗口）。

用途：限制「连通性检查」等会真实触发模型调用（产生费用）的接口被频繁点击。
说明：基于内存字典 + 线程锁，仅在**单进程** uvicorn 下准确；多副本/多 worker
部署时应替换为共享存储（Redis）。当前部署为单容器单进程，够用。
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, status


class InMemoryLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[float]] = {}

    def hit(self, key: str, *, limit: int, window: float) -> float:
        """记录一次命中；返回需等待的秒数（0.0=放行，>0=超限并给出 Retry-After）。"""
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            arr = [t for t in (self._events.get(key) or []) if t > cutoff]
            if len(arr) >= limit:
                self._events[key] = arr
                # 最早一次命中滑出窗口即可再试
                return max(0.0, arr[0] + window - now)
            arr.append(now)
            self._events[key] = arr
            return 0.0


_limiter = InMemoryLimiter()


def enforce(key: str, *, limit: int, window: float, message: str = "操作过于频繁") -> None:
    """超过频率限制时抛 429（带 Retry-After 头），否则静默通过。"""
    wait = _limiter.hit(key, limit=limit, window=window)
    if wait > 0:
        retry = max(1, int(wait + 0.999))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{message}，请 {retry} 秒后再试",
            headers={"Retry-After": str(retry)},
        )


__all__ = ["InMemoryLimiter", "enforce"]
