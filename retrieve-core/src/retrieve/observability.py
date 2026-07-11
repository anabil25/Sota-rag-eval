"""Unified operation observability for CLI and web jobs.

Provides:
- Operation and step context tracking via contextvars
- Structured JSONL event sink
- In-process event bus for SSE streaming (web UI subscribes, core modules publish)
- Logging bridge handler so std logging records are captured with operation context
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import datetime as dt
import json
import logging
import threading
import time
import traceback
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CTX: contextvars.ContextVar[OperationContext | None] = contextvars.ContextVar(
    "retrieve_operation", default=None
)


@dataclass
class OperationContext:
    operation_id: str
    name: str
    source: str
    started_at_monotonic: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)


class JsonlEventSink:
    """Thread-safe JSONL sink."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


# ── Event bus ─────────────────────────────────────────────────────────
# Subscribers register per operation_id. Events are delivered to asyncio
# queues so FastAPI SSE endpoints can await them.  Thread-safe: core
# modules call emit_* from worker threads; the bus pushes into the
# asyncio queue via run_coroutine_threadsafe.

_DONE_SENTINEL = None  # pushed when operation ends


class EventBus:
    """In-process pub/sub for operation events → SSE consumers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # operation_id → list of (asyncio.Queue, asyncio event loop)
        self._subs: dict[str, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = defaultdict(
            list
        )

    def subscribe(self, operation_id: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Create a new subscription queue for an operation. Call from async context."""
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs[operation_id].append((q, loop))
        return q

    def unsubscribe(self, operation_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(operation_id, [])
            self._subs[operation_id] = [(sq, sl) for sq, sl in subs if sq is not q]
            if not self._subs[operation_id]:
                del self._subs[operation_id]

    def publish(self, operation_id: str, event: dict[str, Any]) -> None:
        """Publish an event (thread-safe, called from any thread)."""
        with self._lock:
            subs = list(self._subs.get(operation_id, []))
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:
                pass  # loop closed

    def end(self, operation_id: str) -> None:
        """Signal that the operation is done."""
        with self._lock:
            subs = list(self._subs.get(operation_id, []))
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, _DONE_SENTINEL)
            except RuntimeError:
                pass


_bus = EventBus()
_sink: JsonlEventSink | None = None
_event_journal: Callable[[dict[str, Any]], int] | None = None


def get_event_bus() -> EventBus:
    return _bus


def configure_event_journal(
    journal: Callable[[dict[str, Any]], int] | None,
) -> None:
    """Configure durable event persistence; pass ``None`` to disable it."""
    global _event_journal
    _event_journal = journal


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def get_default_log_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d")
    return Path("logs") / f"retrieve-{stamp}.jsonl"


def configure_observability(
    verbose: bool = False,
    log_path: Path | None = None,
    azure_sdk_logging: bool = False,
    otel_endpoint: str | None = None,
) -> Path:
    """Initialize root logging and JSONL sink once.

    If otel_endpoint is provided (e.g. "http://localhost:4318"), configures
    OpenTelemetry trace export to that OTLP HTTP endpoint. Requires the
    opentelemetry-sdk and opentelemetry-exporter-otlp-proto-http packages.
    """
    global _sink

    if _sink is None:
        _sink = JsonlEventSink(log_path or get_default_log_path())

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")

    # Suppress Azure SDK HTTP request/response noise unless explicitly enabled
    if not azure_sdk_logging:
        for name in ("azure", "azure.core", "azure.identity", "azure.search", "azure.storage"):
            logging.getLogger(name).setLevel(logging.WARNING)

    # OpenTelemetry setup (opt-in)
    if otel_endpoint:
        _configure_otel(otel_endpoint)

    return _sink.path


def _configure_otel(endpoint: str) -> None:
    """Configure OpenTelemetry trace export to an OTLP HTTP endpoint."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "retrieve", "service.version": "0.1.0"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        logging.getLogger(__name__).info("OpenTelemetry configured → %s", endpoint)
    except ImportError:
        logging.getLogger(__name__).warning(
            "OpenTelemetry packages not installed. "
            "Install with: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )


def current_operation_id() -> str | None:
    ctx = _CTX.get()
    return ctx.operation_id if ctx else None


def emit_event(
    event_type: str,
    message: str,
    *,
    level: str = "INFO",
    **fields: Any,
) -> None:
    if _sink is None:
        configure_observability()

    ctx = _CTX.get()
    event: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _utc_now_iso(),
        "event_type": event_type,
        "level": level,
        "message": message,
    }
    if ctx:
        event.update(
            {
                "operation_id": ctx.operation_id,
                "operation_name": ctx.name,
                "operation_source": ctx.source,
                "operation_elapsed_ms": int((time.monotonic() - ctx.started_at_monotonic) * 1000),
                "operation_metadata": ctx.metadata,
            }
        )
    if fields:
        event.update(fields)

    if ctx and _event_journal is not None:
        event["event_sequence"] = _event_journal(dict(event))

    assert _sink is not None
    _sink.write(event)

    # Publish to event bus for SSE subscribers
    op_id = ctx.operation_id if ctx else None
    if op_id:
        _bus.publish(op_id, event)


def emit_progress(message: str, **fields: Any) -> None:
    fields.setdefault("stage", "general")
    emit_event("progress", message, level="INFO", **fields)


def emit_error(message: str, exc: BaseException | None = None, **fields: Any) -> None:
    fields.setdefault("stage", "general")
    if exc is not None:
        fields = {
            **fields,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
    emit_event("error", message, level="ERROR", **fields)


@contextlib.contextmanager
def operation(
    name: str,
    *,
    source: str,
    metadata: dict[str, Any] | None = None,
    operation_id: str | None = None,
) -> Iterator[OperationContext]:
    op = OperationContext(
        operation_id=operation_id or str(uuid.uuid4()),
        name=name,
        source=source,
        metadata=metadata or {},
    )
    token = _CTX.set(op)
    emit_event("operation_start", f"Operation started: {name}")
    try:
        yield op
        emit_event("operation_end", f"Operation completed: {name}", status="success")
    except Exception as exc:
        emit_error(f"Operation failed: {name}", exc)
        emit_event("operation_end", f"Operation completed: {name}", status="failed")
        raise
    finally:
        _bus.end(op.operation_id)
        _CTX.reset(token)


@contextlib.contextmanager
def step(name: str, **fields: Any) -> Iterator[None]:
    started = time.monotonic()
    emit_event("step_start", f"Step started: {name}", step_name=name, **fields)
    try:
        yield
        emit_event(
            "step_end",
            f"Step completed: {name}",
            step_name=name,
            duration_ms=int((time.monotonic() - started) * 1000),
            status="success",
            **fields,
        )
    except Exception as exc:
        emit_error(f"Step failed: {name}", exc, step_name=name, **fields)
        emit_event(
            "step_end",
            f"Step completed: {name}",
            step_name=name,
            duration_ms=int((time.monotonic() - started) * 1000),
            status="failed",
            **fields,
        )
        raise


@contextlib.contextmanager
def capture_module_consoles(modules: list) -> Iterator[None]:
    """No-op kept for backward compatibility with existing CLI call sites."""
    yield


def _format_sse_event(event: dict[str, Any]) -> str:
    message = str(event.get("message", ""))
    safe_message = message.replace("\n", " ").replace("\r", "")
    payload = {
        "message": safe_message,
        "event_type": event.get("event_type", ""),
        "stage": event.get("stage", ""),
        "timestamp": event.get("timestamp", ""),
    }
    sequence = int(event.get("event_sequence") or 0)
    prefix = f"id: {sequence}\n" if sequence else ""
    return f"{prefix}data: {json.dumps(payload)}\n\n"


async def sse_event_stream(
    operation_id: str,
    *,
    event_loader: Callable[[str, int], list[dict[str, Any]]] | None = None,
    after_sequence: int = 0,
    done: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE-formatted events for an operation.

    Subscribe to the event bus for *operation_id* and yield each event
    as an SSE `data:` line.  Returns when the operation ends.
    """
    loop = asyncio.get_running_loop()
    q = _bus.subscribe(operation_id, loop)
    last_sequence = after_sequence
    try:
        if event_loader is not None:
            for event in event_loader(operation_id, after_sequence):
                sequence = int(event.get("event_sequence") or 0)
                if sequence > last_sequence:
                    last_sequence = sequence
                    yield _format_sse_event(event)
        if done:
            yield "event: done\ndata: \n\n"
            return
        while True:
            event = await q.get()
            if event is _DONE_SENTINEL:
                yield "event: done\ndata: \n\n"
                return
            sequence = int(event.get("event_sequence") or 0)
            if sequence and sequence <= last_sequence:
                continue
            last_sequence = max(last_sequence, sequence)
            yield _format_sse_event(event)
    finally:
        _bus.unsubscribe(operation_id, q)
