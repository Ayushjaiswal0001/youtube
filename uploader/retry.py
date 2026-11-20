from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from .errors import ApiError

T = TypeVar("T")


def retry_call(
    function: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last_error: ApiError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except ApiError as exc:
            last_error = exc
            if not exc.retryable or attempt >= attempts:
                raise
            delay = exc.retry_after
            if delay is None:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_call exhausted without a result")
