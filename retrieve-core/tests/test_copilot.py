"""Tests for copilot.py — Copilot SDK client manager (mocked)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from retrieve.config import CopilotConfig, ProviderConfig
from retrieve.copilot import (
    _session_config,
    get_client,
    run_sync,
    send_and_wait,
    send_and_wait_session,
)


class TestSessionConfig:
    def test_basic_config(self):
        cfg = CopilotConfig(model="gpt-4.1")
        sc = _session_config(cfg)
        assert sc["model"] == "gpt-4.1"
        assert "on_permission_request" in sc
        assert "provider" not in sc
        assert "system_message" not in sc

    def test_with_system_message(self):
        cfg = CopilotConfig(model="gpt-4.1")
        sc = _session_config(cfg, system_message="You are helpful")
        assert sc["system_message"] == {"content": "You are helpful"}

    def test_with_tools(self):
        cfg = CopilotConfig(model="gpt-4.1")
        tools = [MagicMock(), MagicMock()]
        sc = _session_config(cfg, tools=tools)
        assert sc["tools"] == tools

    def test_with_byok_provider(self):
        cfg = CopilotConfig(
            model="gpt-4",
            provider=ProviderConfig(
                type="azure",
                base_url="https://test.openai.azure.com",
                api_key="test-key",
            ),
        )
        sc = _session_config(cfg)
        assert sc["provider"]["type"] == "azure"
        assert sc["provider"]["base_url"] == "https://test.openai.azure.com"
        assert sc["provider"]["api_key"] == "test-key"

    def test_ollama_provider(self):
        cfg = CopilotConfig(
            model="deepseek-coder",
            provider=ProviderConfig(
                type="openai",
                base_url="http://localhost:11434/v1",
            ),
        )
        sc = _session_config(cfg)
        assert sc["provider"]["type"] == "openai"
        assert sc["provider"]["base_url"] == "http://localhost:11434/v1"
        assert "api_key" not in sc["provider"]


class TestRunSync:
    def test_run_sync_basic(self):
        async def coro():
            return 42

        result = run_sync(coro())
        assert result == 42

    def test_run_sync_with_async_work(self):
        async def coro():
            await asyncio.sleep(0)
            return "done"

        result = run_sync(coro())
        assert result == "done"


class TestGetClient:
    @patch("retrieve.copilot.CopilotClient")
    async def test_get_client_creates_singleton(self, MockClient):
        import retrieve.copilot as mod

        mod._client = None
        mod._started = False

        mock_instance = MagicMock()
        mock_instance.start = AsyncMock()
        MockClient.return_value = mock_instance

        client = await get_client(CopilotConfig())
        assert client is mock_instance
        mock_instance.start.assert_awaited_once()

        # Second call returns same instance
        client2 = await get_client(CopilotConfig())
        assert client2 is mock_instance

        # Cleanup
        mod._client = None
        mod._started = False


class TestSendAndWait:
    @patch("retrieve.copilot.get_client")
    async def test_send_and_wait_returns_content(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data.content = "Hello from LLM"

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client.create_session = AsyncMock(return_value=mock_session)

        cfg = CopilotConfig(model="gpt-4.1")
        result = await send_and_wait(cfg, "test prompt")
        assert result == "Hello from LLM"

    @patch("retrieve.copilot.get_client")
    async def test_send_and_wait_empty_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_session = AsyncMock()
        mock_session.send_and_wait.return_value = None
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client.create_session = AsyncMock(return_value=mock_session)

        cfg = CopilotConfig(model="gpt-4.1")
        result = await send_and_wait(cfg, "test")
        assert result == ""


class TestSendAndWaitSession:
    @patch("retrieve.copilot.get_client")
    async def test_multi_turn(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        responses = []
        for content in ["reply1", "reply2"]:
            r = MagicMock()
            r.data.content = content
            responses.append(r)

        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(side_effect=responses)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client.create_session = AsyncMock(return_value=mock_session)

        cfg = CopilotConfig(model="gpt-4.1")
        replies = await send_and_wait_session(cfg, ["msg1", "msg2"])
        assert replies == ["reply1", "reply2"]
