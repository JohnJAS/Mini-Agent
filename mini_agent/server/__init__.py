"""WebSocket server module for Mini-Agent API.

This module provides a WebSocket-based API for interacting with Mini-Agent,
supporting multiple sessions with both streaming and complete response modes.
"""

from .websocket_server import run_server, main
from .client import (
    MiniAgentClient,
    AgentResponse,
    ToolCallInfo,
    ToolResultInfo,
    chat,
    chat_stream,
)
from .message_types import (
    # Request types
    CreateSessionRequest,
    PromptRequest,
    CancelRequest,
    CloseSessionRequest,
    # Response types
    SessionCreatedResponse,
    ThinkingEvent,
    MessageChunkEvent,
    MessageEvent,
    ToolCallEvent,
    ToolResultEvent,
    CompletedEvent,
    ErrorEvent,
)

__all__ = [
    # Server
    "run_server",
    "main",
    # Client
    "MiniAgentClient",
    "AgentResponse",
    "ToolCallInfo",
    "ToolResultInfo",
    "chat",
    "chat_stream",
    # Request types
    "CreateSessionRequest",
    "PromptRequest",
    "CancelRequest",
    "CloseSessionRequest",
    # Response types
    "SessionCreatedResponse",
    "ThinkingEvent",
    "MessageChunkEvent",
    "MessageEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "CompletedEvent",
    "ErrorEvent",
]