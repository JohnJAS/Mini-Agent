"""Tests for WebSocket server module."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from mini_agent.server.message_types import (
    parse_client_message,
    CreateSessionRequest,
    PromptRequest,
    CancelRequest,
    CloseSessionRequest,
    SessionCreatedResponse,
    ThinkingEvent,
    MessageChunkEvent,
    MessageEvent,
    ToolCallEvent,
    ToolResultEvent,
    CompletedEvent,
    ErrorEvent,
)
from mini_agent.server.session_manager import SessionManager, SessionState


class TestMessageTypes:
    """Tests for message type parsing."""

    def test_parse_create_session(self):
        """Test parsing create_session request."""
        data = {"type": "create_session", "workspace": "/tmp/test"}
        req = parse_client_message(data)
        assert isinstance(req, CreateSessionRequest)
        assert req.workspace == "/tmp/test"

    def test_parse_create_session_no_workspace(self):
        """Test parsing create_session request without workspace."""
        data = {"type": "create_session"}
        req = parse_client_message(data)
        assert isinstance(req, CreateSessionRequest)
        assert req.workspace is None

    def test_parse_prompt_streaming(self):
        """Test parsing prompt request with streaming."""
        data = {
            "type": "prompt",
            "session_id": "sess-123",
            "content": "Hello",
            "stream": True,
        }
        req = parse_client_message(data)
        assert isinstance(req, PromptRequest)
        assert req.session_id == "sess-123"
        assert req.content == "Hello"
        assert req.stream is True

    def test_parse_prompt_complete(self):
        """Test parsing prompt request for complete mode."""
        data = {
            "type": "prompt",
            "session_id": "sess-456",
            "content": "Write a poem",
        }
        req = parse_client_message(data)
        assert isinstance(req, PromptRequest)
        assert req.stream is True  # Default value

    def test_parse_cancel(self):
        """Test parsing cancel request."""
        data = {"type": "cancel", "session_id": "sess-123"}
        req = parse_client_message(data)
        assert isinstance(req, CancelRequest)
        assert req.session_id == "sess-123"

    def test_parse_close_session(self):
        """Test parsing close_session request."""
        data = {"type": "close_session", "session_id": "sess-123"}
        req = parse_client_message(data)
        assert isinstance(req, CloseSessionRequest)
        assert req.session_id == "sess-123"

    def test_parse_unknown_type(self):
        """Test parsing unknown message type returns None."""
        data = {"type": "unknown", "data": "test"}
        req = parse_client_message(data)
        assert req is None

    def test_response_serialization(self):
        """Test that response types serialize correctly to JSON."""
        # SessionCreatedResponse
        resp = SessionCreatedResponse(session_id="sess-123", workspace="/tmp")
        data = resp.model_dump()
        assert data["type"] == "session_created"
        assert data["session_id"] == "sess-123"

        # ThinkingEvent
        event = ThinkingEvent(session_id="sess-123", content="thinking...")
        data = event.model_dump()
        assert data["type"] == "thinking"

        # MessageChunkEvent
        event = MessageChunkEvent(session_id="sess-123", content="Hello")
        data = event.model_dump()
        assert data["type"] == "message_chunk"

        # CompletedEvent
        event = CompletedEvent(session_id="sess-123", stop_reason="end_turn")
        data = event.model_dump()
        assert data["type"] == "completed"
        assert data["stop_reason"] == "end_turn"

        # ErrorEvent
        event = ErrorEvent(session_id="sess-123", message="Error occurred", code="test_error")
        data = event.model_dump()
        assert data["type"] == "error"
        assert data["code"] == "test_error"


class TestSessionManager:
    """Tests for session manager."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = MagicMock()
        config.agent.workspace_dir = "./workspace"
        config.agent.max_steps = 10
        config.tools.enable_bash = True
        config.tools.enable_file_tools = True
        config.tools.enable_note = True
        return config

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        return MagicMock()

    @pytest.fixture
    def session_manager(self, mock_config, mock_llm, tmp_path):
        """Create session manager instance."""
        return SessionManager(
            config=mock_config,
            llm_client=mock_llm,
            base_tools=[],
            system_prompt="Test prompt",
        )

    @pytest.mark.asyncio
    async def test_create_session(self, session_manager, tmp_path):
        """Test creating a session."""
        with patch.object(session_manager, '_add_workspace_tools'):
            state = await session_manager.create_session(workspace=str(tmp_path))

        assert state.session_id.startswith("sess-")
        assert state.workspace == tmp_path
        assert state.agent is not None
        assert not state.cancelled

        # Check session is stored
        retrieved = await session_manager.get_session(state.session_id)
        assert retrieved is state

    @pytest.mark.asyncio
    async def test_close_session(self, session_manager, tmp_path):
        """Test closing a session."""
        with patch.object(session_manager, '_add_workspace_tools'):
            state = await session_manager.create_session(workspace=str(tmp_path))

        # Close the session
        result = await session_manager.close_session(state.session_id)
        assert result is True

        # Session should no longer exist
        retrieved = await session_manager.get_session(state.session_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self, session_manager):
        """Test closing a session that doesn't exist."""
        result = await session_manager.close_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_session(self, session_manager, tmp_path):
        """Test cancelling a session."""
        with patch.object(session_manager, '_add_workspace_tools'):
            state = await session_manager.create_session(workspace=str(tmp_path))

        # Cancel the session
        result = await session_manager.cancel_session(state.session_id)
        assert result is True
        assert state.cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session(self, session_manager):
        """Test cancelling a session that doesn't exist."""
        result = await session_manager.cancel_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_session_count(self, session_manager, tmp_path):
        """Test session count tracking."""
        assert session_manager.session_count == 0

        with patch.object(session_manager, '_add_workspace_tools'):
            state1 = await session_manager.create_session(workspace=str(tmp_path))
            assert session_manager.session_count == 1

            state2 = await session_manager.create_session(workspace=str(tmp_path))
            assert session_manager.session_count == 2

        await session_manager.close_session(state1.session_id)
        assert session_manager.session_count == 1


class TestStreamingAgent:
    """Tests for streaming agent wrapper."""

    @pytest.fixture
    def mock_agent(self):
        """Create mock agent."""
        agent = MagicMock()
        agent.max_steps = 5
        agent.messages = []
        agent.tools = {}
        agent.api_total_tokens = 0
        agent.cancel_event = None
        agent.add_user_message = MagicMock()
        agent._summarize_messages = AsyncMock()
        return agent

    @pytest.mark.asyncio
    async def test_run_complete_basic(self, mock_agent):
        """Test running agent in complete mode."""
        from mini_agent.server.streaming_agent import StreamingAgent
        from mini_agent.schema import LLMResponse

        # Mock LLM response
        mock_response = LLMResponse(
            content="Hello, how can I help?",
            thinking="User greeted me",
            tool_calls=None,
            finish_reason="end_turn",
        )
        mock_agent.llm = MagicMock()
        mock_agent.llm.generate = AsyncMock(return_value=mock_response)

        streaming_agent = StreamingAgent(
            agent=mock_agent,
            session_id="test-session",
        )

        content, thinking, stop_reason = await streaming_agent.run_complete("Hi")

        assert content == "Hello, how can I help?"
        assert thinking == "User greeted me"
        assert stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_run_streaming_callbacks(self, mock_agent):
        """Test running agent with streaming callbacks."""
        from mini_agent.server.streaming_agent import StreamingAgent
        from mini_agent.schema import LLMResponse

        # Track callback invocations
        thinking_calls = []
        message_chunk_calls = []

        async def on_thinking(content):
            thinking_calls.append(content)

        async def on_message_chunk(content):
            message_chunk_calls.append(content)

        # Mock LLM response
        mock_response = LLMResponse(
            content="Response text",
            thinking="I'm thinking",
            tool_calls=None,
            finish_reason="end_turn",
        )
        mock_agent.llm = MagicMock()
        mock_agent.llm.generate = AsyncMock(return_value=mock_response)

        streaming_agent = StreamingAgent(
            agent=mock_agent,
            session_id="test-session",
            on_thinking=on_thinking,
            on_message_chunk=on_message_chunk,
        )

        result = await streaming_agent.run_streaming("Test")

        assert len(thinking_calls) == 1
        assert thinking_calls[0] == "I'm thinking"
        assert len(message_chunk_calls) == 1
        assert message_chunk_calls[0] == "Response text"