"""Compatibility stream helpers for legacy web tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any


class LogQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()

    def put(self, message: str, loop: asyncio.AbstractEventLoop) -> None:
        loop.call_soon_threadsafe(self._queue.put_nowait, message)

    def done(self, loop: asyncio.AbstractEventLoop) -> None:
        loop.call_soon_threadsafe(self._queue.put_nowait, None)

    async def get(self) -> str | None:
        return await self._queue.get()


class _CaptureConsole:
    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def print(self, *args: Any, **kwargs: Any) -> None:
        sep = str(kwargs.get("sep", " "))
        self._callback(sep.join(str(arg) for arg in args))


class RichCapture:
    def __init__(self, modules: Iterable[Any], callback: Callable[[str], None]) -> None:
        self._modules = list(modules)
        self._callback = callback
        self._originals: list[tuple[Any, Any]] = []

    def __enter__(self) -> RichCapture:
        capture = _CaptureConsole(self._callback)
        for module in self._modules:
            self._originals.append((module, getattr(module, "console", None)))
            module.console = capture
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        for module, original in self._originals:
            module.console = original
        self._originals.clear()
