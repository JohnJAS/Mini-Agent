"""WebSocket client for Mini-Agent API.

Provides a simple client for interacting with Mini-Agent WebSocket server.
"""

import asyncio
import json
import logging
from typing import Callable, Any, AsyncIterator
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


@dataclass
class ToolCallInfo:
    """Information about a tool call."""

    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any]


@dataclass
class ToolResultInfo:
    """Information about a tool result."""

    tool_call_id: str
    tool_name: str
    success: bool
    content: str
    error: str | None = None


@dataclass
class AgentResponse:
    """Complete response from agent execution."""

    content: str
    thinking: str | None = None
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    tool_results: list[ToolResultInfo] = field(default_factory=list)
    stop_reason: str = "end_turn"


class MiniAgentClient:
    """WebSocket client for Mini-Agent API.

    Example usage:
        ```python
        async with MiniAgentClient("ws://localhost:8765") as client:
            # Create session
            await client.create_session()

            # Send message and get complete response
            response = await client.send_message("Hello", stream=False)
            print(response.content)

            # Stream message
            async for event in client.send_message_stream("Tell me a story"):
                if event["type"] == "message_chunk":
                    print(event["content"], end="")
        ```
    """

    def __init__(
        self,
        url: str = "ws://localhost:8765",
        workspace: str | None = None,
    ):
        """Initialize the client.

        Args:
            url: WebSocket server URL
            workspace: Optional workspace directory path
        """
        self._url = url
        self._workspace = workspace
        self._ws: ClientConnection | None = None
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        """Get current session ID."""
        return self._session_id

    @property
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self._ws is not None

    async def __aenter__(self) -> "MiniAgentClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Connect to the WebSocket server."""
        if self._ws is not None:
            return

        self._ws = await websockets.connect(self._url)
        logger.info(f"Connected to {self._url}")

    async def close(self) -> None:
        """Close the connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
            self._session_id = None
            logger.info("Connection closed")

    async def create_session(self, workspace: str | None = None) -> str:
        """Create a new agent session.

        Args:
            workspace: Optional workspace directory (overrides instance workspace)

        Returns:
            Session ID
        """
        if self._ws is None:
            raise RuntimeError("Not connected. Call connect() first.")

        workspace = workspace or self._workspace
        await self._ws.send(json.dumps({
            "type": "create_session",
            "workspace": workspace,
        }))

        response = json.loads(await self._ws.recv())
        if response.get("type") != "session_created":
            raise RuntimeError(f"Failed to create session: {response}")

        self._session_id = response["session_id"]
        logger.info(f"Created session: {self._session_id}")
        return self._session_id

    async def _ensure_session(self) -> str:
        """Ensure a session exists, creating one if needed."""
        if self._session_id is None:
            await self.create_session()
        return self._session_id

    async def send_message(
        self,
        content: str,
        stream: bool = False,
        on_thinking: Callable[[str], Any] | None = None,
        on_tool_call: Callable[[ToolCallInfo], Any] | None = None,
        on_tool_result: Callable[[ToolResultInfo], Any] | None = None,
    ) -> AgentResponse:
        """Send a message and wait for complete response.

        Args:
            content: User message content
            stream: Whether to stream response (callbacks will be called)
            on_thinking: Callback for thinking content
            on_tool_call: Callback for tool calls
            on_tool_result: Callback for tool results

        Returns:
            Complete agent response
        """
        session_id = await self._ensure_session()

        if self._ws is None:
            raise RuntimeError("Not connected")

        await self._ws.send(json.dumps({
            "type": "prompt",
            "session_id": session_id,
            "content": content,
            "stream": stream,
        }))

        response = AgentResponse(content="")

        while True:
            msg = json.loads(await self._ws.recv())
            msg_type = msg.get("type")

            if msg_type == "thinking":
                response.thinking = msg["content"]
                if on_thinking:
                    on_thinking(msg["content"])

            elif msg_type == "message_chunk":
                response.content += msg["content"]

            elif msg_type == "message":
                response.content = msg["content"]

            elif msg_type == "tool_call":
                tool_info = ToolCallInfo(
                    tool_name=msg["tool_name"],
                    tool_call_id=msg["tool_call_id"],
                    arguments=msg.get("arguments", {}),
                )
                response.tool_calls.append(tool_info)
                if on_tool_call:
                    on_tool_call(tool_info)

            elif msg_type == "tool_result":
                result_info = ToolResultInfo(
                    tool_call_id=msg["tool_call_id"],
                    tool_name=msg["tool_name"],
                    success=msg["success"],
                    content=msg["content"],
                    error=msg.get("error"),
                )
                response.tool_results.append(result_info)
                if on_tool_result:
                    on_tool_result(result_info)

            elif msg_type == "completed":
                response.stop_reason = msg["stop_reason"]
                break

            elif msg_type == "error":
                raise RuntimeError(f"Agent error: {msg['message']}")

        return response

    async def send_message_stream(
        self,
        content: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a message and stream events.

        Args:
            content: User message content

        Yields:
            Event dictionaries with type and data
        """
        session_id = await self._ensure_session()

        if self._ws is None:
            raise RuntimeError("Not connected")

        await self._ws.send(json.dumps({
            "type": "prompt",
            "session_id": session_id,
            "content": content,
            "stream": True,
        }))

        while True:
            msg = json.loads(await self._ws.recv())
            yield msg

            if msg.get("type") in ("completed", "error"):
                break

    async def cancel(self) -> bool:
        """Cancel current execution.

        Returns:
            True if cancellation was requested
        """
        if self._ws is None or self._session_id is None:
            return False

        await self._ws.send(json.dumps({
            "type": "cancel",
            "session_id": self._session_id,
        }))
        return True

    async def close_session(self) -> bool:
        """Close the current session.

        Returns:
            True if session was closed
        """
        if self._ws is None or self._session_id is None:
            return False

        await self._ws.send(json.dumps({
            "type": "close_session",
            "session_id": self._session_id,
        }))
        self._session_id = None
        return True


# Convenience functions for simple usage

async def chat(
    message: str,
    url: str = "ws://localhost:8765",
    workspace: str | None = None,
) -> str:
    """Send a single message and get the response.

    Simple one-shot chat function.

    Args:
        message: User message
        url: WebSocket server URL
        workspace: Optional workspace directory

    Returns:
        Agent response content
    """
    async with MiniAgentClient(url, workspace) as client:
        response = await client.send_message(message, stream=False)
        return response.content


async def chat_stream(
    message: str,
    url: str = "ws://localhost:8765",
    workspace: str | None = None,
    on_thinking: Callable[[str], Any] | None = None,
    on_tool_call: Callable[[ToolCallInfo], Any] | None = None,
) -> str:
    """Send a message and stream the response.

    Args:
        message: User message
        url: WebSocket server URL
        workspace: Optional workspace directory
        on_thinking: Callback for thinking content
        on_tool_call: Callback for tool calls

    Returns:
        Complete response content
    """
    async with MiniAgentClient(url, workspace) as client:
        response = await client.send_message(
            message,
            stream=True,
            on_thinking=on_thinking,
            on_tool_call=on_tool_call,
        )
        return response.content


__all__ = [
    "MiniAgentClient",
    "AgentResponse",
    "ToolCallInfo",
    "ToolResultInfo",
    "chat",
    "chat_stream",
]