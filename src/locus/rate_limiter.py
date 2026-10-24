import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from fastapi import Request


class LoginRateLimiter:
    """Sliding-window in-memory rate limiter for login attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300, block_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._attempts: Dict[str, List[float]] = defaultdict(list)
        self._blocks: Dict[str, float] = {}

    def _cleanup(self, now: float) -> None:
        """Prune expired attempts and unblocked records to prevent memory leak."""
        expired_blocks = [k for k, unblock in self._blocks.items() if now >= unblock]
        for k in expired_blocks:
            del self._blocks[k]

        expired_attempts = []
        for k, attempts in self._attempts.items():
            valid = [t for t in attempts if now - t < self.window_seconds]
            if valid:
                self._attempts[k] = valid
            elif k not in self._blocks:
                expired_attempts.append(k)

        for k in expired_attempts:
            del self._attempts[k]

    def is_blocked(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        if len(self._attempts) > 100 or len(self._blocks) > 100:
            self._cleanup(now)

        unblock_time = self._blocks.get(key)
        if unblock_time:
            if now < unblock_time:
                remaining = int(unblock_time - now) + 1
                return True, remaining
            else:
                self._blocks.pop(key, None)
                self._attempts.pop(key, None)
        return False, 0

    def record_failure(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        if len(self._attempts) > 100 or len(self._blocks) > 100:
            self._cleanup(now)

        attempts = [t for t in self._attempts[key] if now - t < self.window_seconds]
        attempts.append(now)
        self._attempts[key] = attempts

        if len(attempts) >= self.max_attempts:
            self._blocks[key] = now + self.block_seconds
            return True, self.block_seconds
        return False, 0

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._blocks.pop(key, None)

    def reset(self) -> None:
        self._attempts.clear()
        self._blocks.clear()


login_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300, block_seconds=300)


def get_client_ip(request: Request) -> str:
    """Extract client IP, inspecting X-Forwarded-For only when behind local/trusted proxies."""
    raw_ip = request.client.host if request.client else "127.0.0.1"
    if raw_ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return raw_ip


def _make_key(ip: str, username: str) -> str:
    cleaned_username = username.strip().lower() if username else ""
    return f"pair:{ip}:{cleaned_username}" if cleaned_username else f"ip:{ip}"


def check_login_rate_limit(request: Request, username: str) -> Tuple[bool, int]:
    """Check if (IP, username) pair is currently rate-limited."""
    ip = get_client_ip(request)
    key = _make_key(ip, username)
    return login_limiter.is_blocked(key)


def record_login_failure(request: Request, username: str) -> Tuple[bool, int]:
    """Record a failed login attempt for the (IP, username) pair."""
    ip = get_client_ip(request)
    key = _make_key(ip, username)
    return login_limiter.record_failure(key)


def record_login_success(request: Request, username: str) -> None:
    """Clear rate-limiting attempts on successful login for the (IP, username) pair."""
    ip = get_client_ip(request)
    key = _make_key(ip, username)
    login_limiter.record_success(key)


def format_rate_limit_message(remaining_seconds: int) -> str:
    """Format human-readable rate limit message with correct Russian plurals."""
    minutes = max(1, (remaining_seconds + 59) // 60)
    rem10 = minutes % 10
    rem100 = minutes % 100
    if 11 <= rem100 <= 14:
        time_text = f"{minutes} минут"
    elif rem10 == 1:
        time_text = f"{minutes} минуту"
    elif 2 <= rem10 <= 4:
        time_text = f"{minutes} минуты"
    else:
        time_text = f"{minutes} минут"
    return f"Слишком много неудачных попыток входа. Попробуйте через {time_text}."
