"""Session manager for WebSocket server.

Manages multiple agent sessions with thread-safe operations.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any
from uuid import uuid4

from mini_agent.agent import Agent
from mini_agent.config import Config
from mini_agent.llm import LLMClient
from mini_agent.schema import Message
from mini_agent.retry import RetryConfig as RetryConfigBase

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """State for a single agent session."""

    session_id: str
    agent: Agent
    workspace: Path
    cancelled: bool = False
    current_task: asyncio.Task | None = None
    send_callback: Callable[[dict[str, Any]], Any] | None = None

    # Accumulated message content for complete mode
    accumulated_content: str = ""
    accumulated_thinking: str = ""


class SessionManager:
    """Manages multiple agent sessions."""

    def __init__(self, config: Config, llm_client: LLMClient, base_tools: list, system_prompt: str):
        """Initialize session manager.

        Args:
            config: Configuration object
            llm_client: LLM client instance
            base_tools: Base tools list (workspace-independent)
            system_prompt: System prompt for agents
        """
        self._config = config
        self._llm = llm_client
        self._base_tools = base_tools
        self._system_prompt = system_prompt
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        workspace: str | None = None,
        send_callback: Callable[[dict[str, Any]], Any] | None = None,
    ) -> SessionState:
        """Create a new agent session.

        Args:
            workspace: Optional workspace directory path
            send_callback: Optional callback for sending messages

        Returns:
            Created session state
        """
        # Generate unique session ID
        session_id = f"sess-{uuid4().hex[:8]}"

        # Determine workspace
        if workspace:
            workspace_path = Path(workspace).expanduser().resolve()
        else:
            workspace_path = Path(self._config.agent.workspace_dir).expanduser().resolve()

        workspace_path.mkdir(parents=True, exist_ok=True)

        # Create tools for this session
        tools = list(self._base_tools)
        self._add_workspace_tools(tools, workspace_path)

        # Create agent
        agent = Agent(
            llm_client=self._llm,
            system_prompt=self._system_prompt,
            tools=tools,
            max_steps=self._config.agent.max_steps,
            workspace_dir=str(workspace_path),
        )

        # Create session state
        state = SessionState(
            session_id=session_id,
            agent=agent,
            workspace=workspace_path,
            send_callback=send_callback,
        )

        async with self._lock:
            self._sessions[session_id] = state

        logger.info(f"Created session {session_id} with workspace {workspace_path}")
        return state

    async def get_session(self, session_id: str) -> SessionState | None:
        """Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session state or None if not found
        """
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> bool:
        """Close and remove a session.

        Args:
            session_id: Session ID

        Returns:
            True if session was closed, False if not found
        """
        async with self._lock:
            state = self._sessions.pop(session_id, None)
            if state:
                # Cancel any running task
                if state.current_task and not state.current_task.done():
                    state.current_task.cancel()
                logger.info(f"Closed session {session_id}")
                return True
            return False

    async def cancel_session(self, session_id: str) -> bool:
        """Request cancellation of current execution in a session.

        Args:
            session_id: Session ID

        Returns:
            True if cancellation was requested, False if session not found
        """
        state = await self.get_session(session_id)
        if state:
            state.cancelled = True
            if state.agent.cancel_event:
                state.agent.cancel_event.set()
            logger.info(f"Requested cancellation for session {session_id}")
            return True
        return False

    def _add_workspace_tools(self, tools: list, workspace_dir: Path) -> None:
        """Add workspace-dependent tools.

        Args:
            tools: Tools list to add to
            workspace_dir: Workspace directory path
        """
        from mini_agent.tools.bash_tool import BashTool
        from mini_agent.tools.file_tools import ReadTool, WriteTool, EditTool
        from mini_agent.tools.note_tool import SessionNoteTool

        # Bash tool
        if self._config.tools.enable_bash:
            tools.append(BashTool(workspace_dir=str(workspace_dir)))

        # File tools
        if self._config.tools.enable_file_tools:
            tools.extend([
                ReadTool(workspace_dir=str(workspace_dir)),
                WriteTool(workspace_dir=str(workspace_dir)),
                EditTool(workspace_dir=str(workspace_dir)),
            ])

        # Session note tool
        if self._config.tools.enable_note:
            tools.append(SessionNoteTool(memory_file=str(workspace_dir / ".agent_memory.json")))

    @property
    def session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all sessions.

        Args:
            message: Message to broadcast
        """
        async with self._lock:
            for state in self._sessions.values():
                if state.send_callback:
                    try:
                        await state.send_callback(message)
                    except Exception as e:
                        logger.error(f"Error broadcasting to session {state.session_id}: {e}")