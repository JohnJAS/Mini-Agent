"""Message type definitions for WebSocket API.

Defines request and response message types using Pydantic for validation.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field


# =============================================================================
# Base Message Types
# =============================================================================

class WebSocketMessage(BaseModel):
    """Base class for all WebSocket messages."""

    type: str
    session_id: str | None = None


# =============================================================================
# Request Types (Client -> Server)
# =============================================================================

class CreateSessionRequest(BaseModel):
    """Request to create a new agent session."""

    type: Literal["create_session"] = "create_session"
    workspace: str | None = None  # Optional workspace directory path


class PromptRequest(BaseModel):
    """Request to send a prompt to an agent session."""

    type: Literal["prompt"] = "prompt"
    session_id: str
    content: str
    stream: bool = True  # Default to streaming mode


class CancelRequest(BaseModel):
    """Request to cancel current execution in a session."""

    type: Literal["cancel"] = "cancel"
    session_id: str


class CloseSessionRequest(BaseModel):
    """Request to close an agent session."""

    type: Literal["close_session"] = "close_session"
    session_id: str


# Union type for all requests
ClientRequest = CreateSessionRequest | PromptRequest | CancelRequest | CloseSessionRequest


# =============================================================================
# Response Types (Server -> Client)
# =============================================================================

class SessionCreatedResponse(BaseModel):
    """Response when a session is successfully created."""

    type: Literal["session_created"] = "session_created"
    session_id: str
    workspace: str


class ThinkingEvent(BaseModel):
    """Event for agent thinking content (streaming mode)."""

    type: Literal["thinking"] = "thinking"
    session_id: str
    content: str


class MessageChunkEvent(BaseModel):
    """Event for message content chunks (streaming mode)."""

    type: Literal["message_chunk"] = "message_chunk"
    session_id: str
    content: str


class MessageEvent(BaseModel):
    """Event for complete message (complete mode or final message)."""

    type: Literal["message"] = "message"
    session_id: str
    content: str


class ToolCallEvent(BaseModel):
    """Event when a tool is called."""

    type: Literal["tool_call"] = "tool_call"
    session_id: str
    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(BaseModel):
    """Event when a tool execution completes."""

    type: Literal["tool_result"] = "tool_result"
    session_id: str
    tool_call_id: str
    tool_name: str
    success: bool
    content: str
    error: str | None = None


class CompletedEvent(BaseModel):
    """Event when agent execution completes."""

    type: Literal["completed"] = "completed"
    session_id: str
    stop_reason: str = "end_turn"  # "end_turn", "cancelled", "max_turn_requests", "refusal"


class ErrorEvent(BaseModel):
    """Error event."""

    type: Literal["error"] = "error"
    session_id: str | None = None
    message: str
    code: str | None = None  # Error code for programmatic handling


# =============================================================================
# Helper Functions
# =============================================================================

def parse_client_message(data: dict[str, Any]) -> ClientRequest | None:
    """Parse a client message from raw dict.

    Args:
        data: Raw dictionary from JSON

    Returns:
        Parsed request object or None if type is unknown
    """
    msg_type = data.get("type")

    if msg_type == "create_session":
        return CreateSessionRequest(**data)
    elif msg_type == "prompt":
        return PromptRequest(**data)
    elif msg_type == "cancel":
        return CancelRequest(**data)
    elif msg_type == "close_session":
        return CloseSessionRequest(**data)

    return None