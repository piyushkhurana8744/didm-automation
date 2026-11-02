"""Shared security helpers: client address, rate limiting and keeping secrets out of the logs."""
import logging
import re
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def client_ip(request: Request, trust_proxy: bool) -> str:
    """The caller's address. Behind a proxy that appends to X-Forwarded-For (Render does), the last
    entry is the one the proxy saw; entries before it can be forged by the caller."""
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


class RateLimiter:
    """Sliding-window counter kept in memory.

    Fine for the single-worker deployment this app requires. With several instances it must move to a
    shared store such as Redis, otherwise each instance counts separately.
    """

    def __init__(self, clock=time.monotonic):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Counts one attempt. Returns False when the key is over its limit."""
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def over(self, key: str, limit: int, window_seconds: int) -> bool:
        """True when the key already reached its limit. Does not count an attempt."""
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            return len(q) >= limit

    def check(self, key: str, limit: int, window_seconds: int):
        if not self.hit(key, limit, window_seconds):
            raise HTTPException(status_code=429, detail="Too many attempts. Please wait and try again.",
                                headers={"Retry-After": str(window_seconds)})

    def reset(self):
        with self._lock:
            self._hits.clear()


_SECRET_PATTERNS = [
    (re.compile(r"(/webhooks/[a-z_-]+/)[^/?\s\"]+"), r"\1***"),
    (re.compile(r"((?:^|[?&])(?:token|password)=)[^&\s\"]+", re.I), r"\1***"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactSecretsFilter(logging.Filter):
    """Removes webhook secrets and ?token= values from access-log lines before they are written."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            # Non-text arguments (e.g. an httpx URL object) are redacted through their text form
            record.args = tuple(a if isinstance(a, (int, float)) or a is None else redact(str(a))
                                for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install_log_redaction():
    f = RedactSecretsFilter()
    for name in ("uvicorn.access", "uvicorn.error", "didm", "httpx", "httpx2"):
        logger = logging.getLogger(name)
        if not any(isinstance(x, RedactSecretsFilter) for x in logger.filters):
            logger.addFilter(f)
