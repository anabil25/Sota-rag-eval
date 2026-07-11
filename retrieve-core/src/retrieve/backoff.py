from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class BackoffPolicy:
    max_attempts: int = 6
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    jitter_ratio: float = 0.2
    retryable_status_codes: frozenset[int] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_STATUS_CODES
    )

    @classmethod
    def from_env(cls, prefix: str, **defaults: Any) -> BackoffPolicy:
        def value(name: str, fallback: Any, cast: Callable[[str], Any]) -> Any:
            raw = os.environ.get(f"{prefix}_{name}")
            if raw is None or raw == "":
                return fallback
            try:
                return cast(raw)
            except ValueError:
                return fallback

        status_default = defaults.get("retryable_status_codes", DEFAULT_RETRYABLE_STATUS_CODES)
        status_raw = os.environ.get(f"{prefix}_RETRYABLE_STATUS_CODES", "")
        if status_raw:
            retryable_status_codes = frozenset(
                int(part.strip()) for part in status_raw.split(",") if part.strip()
            )
        else:
            retryable_status_codes = frozenset(status_default)

        return cls(
            max_attempts=max(1, value("MAX_ATTEMPTS", defaults.get("max_attempts", 6), int)),
            base_delay_seconds=max(
                0.0,
                value("BASE_DELAY_SECONDS", defaults.get("base_delay_seconds", 2.0), float),
            ),
            max_delay_seconds=max(
                0.0,
                value("MAX_DELAY_SECONDS", defaults.get("max_delay_seconds", 60.0), float),
            ),
            jitter_ratio=max(0.0, value("JITTER_RATIO", defaults.get("jitter_ratio", 0.2), float)),
            retryable_status_codes=retryable_status_codes,
        )


def retry_after_seconds(headers: Any, max_delay_seconds: float) -> float | None:
    if not headers:
        return None
    for name in ("retry-after-ms", "x-ms-retry-after-ms"):
        value = _header_value(headers, name)
        if value:
            try:
                return min(float(value) / 1000.0, max_delay_seconds)
            except ValueError:
                pass

    value = _header_value(headers, "retry-after")
    if not value:
        return None
    try:
        return min(float(value), max_delay_seconds)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return min(max(0.0, retry_at.timestamp() - time.time()), max_delay_seconds)
        except (TypeError, ValueError, OverflowError):
            return None


def retry_delay(policy: BackoffPolicy, attempt_number: int, headers: Any = None) -> float:
    explicit_delay = retry_after_seconds(headers, policy.max_delay_seconds)
    if explicit_delay is not None:
        return explicit_delay
    delay = min(
        policy.base_delay_seconds * (2 ** max(0, attempt_number - 1)),
        policy.max_delay_seconds,
    )
    if policy.jitter_ratio:
        jitter = delay * policy.jitter_ratio
        delay = random.uniform(max(0.0, delay - jitter), delay + jitter)
    return min(delay, policy.max_delay_seconds)


def is_retryable_http_response(response: Any, policy: BackoffPolicy) -> bool:
    status_code = getattr(response, "status_code", None)
    return isinstance(status_code, int) and status_code in policy.retryable_status_codes


def call_with_backoff(
    func: Callable[[], T],
    *,
    policy: BackoffPolicy,
    operation: str,
    logger: logging.Logger,
    retry_exceptions: tuple[type[BaseException], ...] = (),
    should_retry_result: Callable[[T, BackoffPolicy], bool] | None = None,
) -> T:
    last_exception: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = func()
        except retry_exceptions as exc:
            last_exception = exc
            if attempt >= policy.max_attempts:
                raise
            delay = retry_delay(policy, attempt)
            logger.warning(
                "%s failed with %s; retrying in %.1fs (%s/%s)",
                operation,
                type(exc).__name__,
                delay,
                attempt,
                policy.max_attempts,
            )
            time.sleep(delay)
            continue

        if should_retry_result and should_retry_result(result, policy):
            if attempt >= policy.max_attempts:
                return result
            delay = retry_delay(policy, attempt, getattr(result, "headers", None))
            logger.warning(
                "%s returned retryable status %s; retrying in %.1fs (%s/%s)",
                operation,
                getattr(result, "status_code", "unknown"),
                delay,
                attempt,
                policy.max_attempts,
            )
            time.sleep(delay)
            continue
        return result

    if last_exception:
        raise last_exception
    raise RuntimeError(f"{operation} failed after {policy.max_attempts} attempts")


async def async_call_with_backoff(
    func: Callable[[], T | Awaitable[T]],
    *,
    policy: BackoffPolicy,
    operation: str,
    logger: logging.Logger,
    retry_exceptions: tuple[type[BaseException], ...] = (),
    should_retry_result: Callable[[T, BackoffPolicy], bool] | None = None,
) -> T:
    last_exception: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            maybe_result = func()
            result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        except retry_exceptions as exc:
            last_exception = exc
            if attempt >= policy.max_attempts:
                raise
            delay = retry_delay(policy, attempt)
            logger.warning(
                "%s failed with %s; retrying in %.1fs (%s/%s)",
                operation,
                type(exc).__name__,
                delay,
                attempt,
                policy.max_attempts,
            )
            await asyncio.sleep(delay)
            continue

        if should_retry_result and should_retry_result(result, policy):
            if attempt >= policy.max_attempts:
                return result
            delay = retry_delay(policy, attempt, getattr(result, "headers", None))
            logger.warning(
                "%s returned retryable status %s; retrying in %.1fs (%s/%s)",
                operation,
                getattr(result, "status_code", "unknown"),
                delay,
                attempt,
                policy.max_attempts,
            )
            await asyncio.sleep(delay)
            continue
        return result

    if last_exception:
        raise last_exception
    raise RuntimeError(f"{operation} failed after {policy.max_attempts} attempts")


def _header_value(headers: Any, name: str) -> str:
    try:
        value = headers.get(name) or headers.get(name.title())
    except AttributeError:
        return ""
    return str(value or "").strip()