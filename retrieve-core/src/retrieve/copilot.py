"""Copilot SDK client manager — shared module for all LLM interactions.

All LLM calls in Retrieve go through the GitHub Copilot SDK.
BYOK (Azure OpenAI, Ollama, etc.) is handled via the SDK's provider config.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from copilot import CopilotClient, PermissionHandler, SubprocessConfig, define_tool
from pydantic import BaseModel, Field

from retrieve.config import CopilotConfig
from retrieve.observability import emit_event, emit_progress

log = logging.getLogger(__name__)

# Singleton client
_client: CopilotClient | None = None
_started = False

# Streaming event handlers — registered by consumers (eval generate, web UI, etc.)
_stream_handlers: list[Callable[[str, dict[str, Any]], None]] = []


def register_stream_handler(handler: Callable[[str, dict[str, Any]], None]) -> None:
    """Register a handler that receives all Copilot SDK streaming events.

    Handler signature: handler(event_type: str, data: dict)
    Event types: message_delta, tool_execution_start, tool_execution_complete, session_idle
    """
    _stream_handlers.append(handler)


def unregister_stream_handler(handler: Callable[[str, dict[str, Any]], None]) -> None:
    """Remove a previously registered stream handler."""
    try:
        _stream_handlers.remove(handler)
    except ValueError:
        pass


def _dispatch_stream_event(event_type: str, data: dict[str, Any]) -> None:
    """Dispatch a streaming event to all registered handlers and observability."""
    emit_event(
        f"copilot.{event_type}",
        data.get("content", data.get("message", event_type)),
        level="DEBUG",
        sdk_event_type=event_type,
        **{k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))},
    )
    for handler in _stream_handlers:
        try:
            handler(event_type, data)
        except Exception:
            log.debug("Stream handler error for %s", event_type, exc_info=True)


async def get_client(cfg: CopilotConfig | None = None) -> CopilotClient:
    """Get or create the singleton CopilotClient, starting it if needed.

    Auth flow (handled by the Copilot SDK automatically):
    - Default: uses the signed-in Copilot CLI user (`copilot` command must be installed
      and user must have run `copilot auth login` or be signed into GitHub Copilot in VS Code)
    - If cfg.github_token is set: uses that PAT instead (sets use_logged_in_user=False)
    - If cfg.provider is set: BYOK mode — routes through Azure OpenAI / Ollama / etc.
      via the SDK's provider config (no Copilot subscription needed)
    - If headless mode is active: uses ExternalServerConfig to connect to the
      managed headless CLI process
    """
    global _client, _started
    if _client is None:
        kwargs: dict[str, Any] = {}
        if cfg and cfg.github_token:
            kwargs["github_token"] = cfg.github_token

        # Use headless server if available
        if _headless_process is not None and _headless_port is not None:
            try:
                from copilot import ExternalServerConfig
                server_config = ExternalServerConfig(
                    host="127.0.0.1",
                    port=_headless_port,
                )
                _client = CopilotClient(server_config)
                log.info("Using headless CLI server on port %d", _headless_port)
            except ImportError:
                log.warning("ExternalServerConfig not available, falling back to subprocess mode")
                _client = CopilotClient(SubprocessConfig(**kwargs) if kwargs else None)
        else:
            _client = CopilotClient(SubprocessConfig(**kwargs) if kwargs else None)
    if not _started:
        try:
            await _client.start()
        except FileNotFoundError:
            raise RuntimeError(
                "GitHub Copilot CLI not found. Install it:\n"
                "  winget install GitHub.CopilotCLI    (Windows)\n"
                "  brew install copilot-cli             (macOS)\n"
                "Then sign in: copilot login"
            )
        except Exception as e:
            if "auth" in str(e).lower() or "token" in str(e).lower():
                raise RuntimeError(
                    f"Copilot CLI auth failed: {e}\n"
                    "Sign in: copilot login\n"
                    "Or set copilot.github_token in retrieve.yaml\n"
                    "Or configure copilot.provider for BYOK (Azure OpenAI / Ollama)"
                )
            raise
        _started = True
    return _client


async def stop_client():
    """Gracefully shut down the Copilot CLI process."""
    global _client, _started
    if _client and _started:
        await _client.stop()
        _started = False
        _client = None


# ── Headless CLI server management ────────────────────────────────────

import subprocess
import shutil

_headless_process: subprocess.Popen | None = None
_headless_port: int | None = None


def start_headless_server(port: int = 19742) -> int:
    """Start the Copilot CLI in headless mode as a managed subprocess.

    Returns the port the headless server is listening on.
    The server remains running until stop_headless_server() is called
    or the process exits.
    """
    global _headless_process, _headless_port

    if _headless_process is not None and _headless_process.poll() is None:
        log.info("Headless server already running on port %d", _headless_port)
        return _headless_port or port

    copilot_path = shutil.which("copilot")
    if not copilot_path:
        raise RuntimeError(
            "GitHub Copilot CLI not found. Install it:\n"
            "  winget install GitHub.CopilotCLI    (Windows)\n"
            "  brew install copilot-cli             (macOS)"
        )

    _headless_port = port
    _headless_process = subprocess.Popen(
        [copilot_path, "--headless", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    log.info("Started headless Copilot CLI on port %d (PID %d)", port, _headless_process.pid)

    # Reset client so next get_client() picks up the headless server
    global _client, _started
    if _client:
        run_sync(stop_client())

    return port


def stop_headless_server() -> None:
    """Stop the managed headless CLI process."""
    global _headless_process, _headless_port
    if _headless_process is not None:
        _headless_process.terminate()
        try:
            _headless_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _headless_process.kill()
        log.info("Stopped headless Copilot CLI (PID %d)", _headless_process.pid)
        _headless_process = None
        _headless_port = None


def is_headless_running() -> bool:
    """Check if the headless CLI server is still running."""
    return _headless_process is not None and _headless_process.poll() is None


def _session_config(
    cfg: CopilotConfig,
    system_message: str | None = None,
    tools: list | None = None,
) -> dict[str, Any]:
    """Build the session config dict for create_session()."""
    sc: dict[str, Any] = {
        "model": cfg.model,
        "on_permission_request": PermissionHandler.approve_all,
    }
    if cfg.provider:
        sc["provider"] = cfg.provider.to_sdk_dict()
    if system_message:
        sc["system_message"] = {"content": system_message}
    if tools:
        sc["tools"] = tools

    # Attach hooks for tool call auditing and session metrics
    sc["on_pre_tool_use"] = _on_pre_tool_use
    sc["on_post_tool_use"] = _on_post_tool_use

    return sc


# ── Hooks ─────────────────────────────────────────────────────────────

import time as _time

_tool_timings: dict[str, float] = {}


def _on_pre_tool_use(tool_name: str, args: Any = None, **kwargs: Any) -> None:
    """Hook: log tool call to observability before execution."""
    _tool_timings[tool_name] = _time.monotonic()
    emit_event(
        "copilot.tool_call_start",
        f"Tool call: {tool_name}",
        level="DEBUG",
        tool_name=tool_name,
    )


def _on_post_tool_use(tool_name: str, result: Any = None, **kwargs: Any) -> None:
    """Hook: capture tool execution timing after completion."""
    started = _tool_timings.pop(tool_name, None)
    duration_ms = int((_time.monotonic() - started) * 1000) if started else 0
    emit_event(
        "copilot.tool_call_end",
        f"Tool complete: {tool_name} ({duration_ms}ms)",
        level="DEBUG",
        tool_name=tool_name,
        duration_ms=duration_ms,
    )


async def send_and_wait(
    cfg: CopilotConfig,
    prompt: str,
    *,
    system_message: str | None = None,
    tools: list | None = None,
    timeout: float | None = None,
    stream: bool = False,
) -> str:
    """Create a one-shot session, send a prompt, and return the assistant response.

    When ``stream=True``, subscribes to session events and dispatches them
    to registered stream handlers for real-time progress.
    """
    client = await get_client(cfg)
    sc = _session_config(cfg, system_message=system_message, tools=tools)

    async with await client.create_session(**sc) as session:
        if stream:
            _attach_stream_handlers(session)
        response = await session.send_and_wait(
            prompt, timeout=timeout or cfg.timeout
        )
        if response and response.data:
            return response.data.content or ""
    return ""


async def send_and_wait_session(
    cfg: CopilotConfig,
    messages: list[str],
    *,
    system_message: str | None = None,
    tools: list | None = None,
    timeout: float | None = None,
    stream: bool = False,
) -> list[str]:
    """Multi-turn session: send each message sequentially, collect responses."""
    client = await get_client(cfg)
    sc = _session_config(cfg, system_message=system_message, tools=tools)
    replies: list[str] = []

    async with await client.create_session(**sc) as session:
        if stream:
            _attach_stream_handlers(session)
        for msg in messages:
            response = await session.send_and_wait(
                msg, timeout=timeout or cfg.timeout
            )
            content = ""
            if response and response.data:
                content = response.data.content or ""
            replies.append(content)

    return replies


def _attach_stream_handlers(session: Any) -> None:
    """Subscribe to session streaming events and route to dispatch.

    Uses session.on() to listen for message_delta, tool execution,
    and session idle events from the Copilot SDK.
    """
    try:
        if hasattr(session, "on"):
            def on_message_delta(event: Any) -> None:
                content = ""
                if hasattr(event, "data") and hasattr(event.data, "content"):
                    content = event.data.content or ""
                elif hasattr(event, "content"):
                    content = event.content or ""
                _dispatch_stream_event("message_delta", {"content": content})

            def on_tool_start(event: Any) -> None:
                tool_name = getattr(event, "name", "unknown") if hasattr(event, "name") else "unknown"
                _dispatch_stream_event("tool_execution_start", {"tool_name": tool_name})

            def on_tool_complete(event: Any) -> None:
                tool_name = getattr(event, "name", "unknown") if hasattr(event, "name") else "unknown"
                _dispatch_stream_event("tool_execution_complete", {"tool_name": tool_name})

            def on_idle(event: Any) -> None:
                _dispatch_stream_event("session_idle", {"message": "Session idle"})

            session.on("assistant.message_delta", on_message_delta)
            session.on("tool.execution_start", on_tool_start)
            session.on("tool.execution_complete", on_tool_complete)
            session.on("session.idle", on_idle)
    except Exception:
        log.debug("Failed to attach stream handlers", exc_info=True)


def run_sync(coro):
    """Run an async coroutine synchronously — for use in CLI commands."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context — create a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)

