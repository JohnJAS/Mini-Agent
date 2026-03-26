"""WebSocket server implementation for Mini-Agent API.

Provides a WebSocket-based API for interacting with Mini-Agent.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed

from mini_agent.cli import initialize_base_tools
from mini_agent.config import Config
from mini_agent.llm import LLMClient
from mini_agent.retry import RetryConfig as RetryConfigBase
from mini_agent.schema import LLMProvider

from .message_types import (
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
from .session_manager import SessionManager, SessionState
from .streaming_agent import StreamingAgent

logger = logging.getLogger(__name__)


class MiniAgentWebSocketServer:
    """WebSocket server for Mini-Agent API."""

    def __init__(self, config: Config, host: str = "localhost", port: int = 8765):
        """Initialize WebSocket server.

        Args:
            config: Configuration object
            host: Host to bind to
            port: Port to listen on
        """
        self._config = config
        self._host = host
        self._port = port
        self._session_manager: SessionManager | None = None
        self._llm_client: LLMClient | None = None
        self._base_tools: list = []
        self._system_prompt: str = ""

    async def initialize(self) -> None:
        """Initialize server components."""
        # Initialize retry config
        retry_config = RetryConfigBase(
            enabled=self._config.llm.retry.enabled,
            max_retries=self._config.llm.retry.max_retries,
            initial_delay=self._config.llm.retry.initial_delay,
            max_delay=self._config.llm.retry.max_delay,
            exponential_base=self._config.llm.retry.exponential_base,
            retryable_exceptions=(Exception,),
        )

        # Create LLM client
        provider = (
            LLMProvider.ANTHROPIC
            if self._config.llm.provider.lower() == "anthropic"
            else LLMProvider.OPENAI
        )

        self._llm_client = LLMClient(
            api_key=self._config.llm.api_key,
            provider=provider,
            api_base=self._config.llm.api_base,
            model=self._config.llm.model,
            retry_config=retry_config if self._config.llm.retry.enabled else None,
        )

        # Initialize base tools
        self._base_tools, skill_loader = await initialize_base_tools(self._config)

        # Load system prompt
        prompt_path = Config.find_config_file(self._config.agent.system_prompt_path)
        if prompt_path and prompt_path.exists():
            self._system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self._system_prompt = "You are a helpful AI assistant."

        # Inject skills metadata if available
        if skill_loader:
            meta = skill_loader.get_skills_metadata_prompt()
            if meta:
                self._system_prompt = f"{self._system_prompt.rstrip()}\n\n{meta}"

        # Create session manager
        self._session_manager = SessionManager(
            config=self._config,
            llm_client=self._llm_client,
            base_tools=self._base_tools,
            system_prompt=self._system_prompt,
        )

        logger.info(f"Server initialized with {len(self._base_tools)} base tools")

    async def handle_connection(self, websocket: ServerConnection) -> None:
        """Handle a WebSocket connection.

        Args:
            websocket: WebSocket connection
        """
        client_addr = websocket.remote_address
        logger.info(f"Client connected: {client_addr}")

        # Session associated with this connection
        current_session: SessionState | None = None
        disconnected_normally = False

        async def send_message(data: dict[str, Any]) -> None:
            """Send a message to the client."""
            try:
                await websocket.send(json.dumps(data))
            except ConnectionClosed as e:
                # Normal close (1000) or going away (1001) should not be errors
                if e.code in (1000, 1001):
                    logger.debug(f"Connection closed normally while sending: {e}")
                else:
                    logger.warning(f"Connection closed unexpectedly while sending: {e}")
            except Exception as e:
                logger.error(f"Error sending message: {e}")

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    logger.debug(f"Received: {data}")

                    # Parse the message
                    request = parse_client_message(data)

                    if request is None:
                        await send_message(ErrorEvent(
                            session_id=current_session.session_id if current_session else None,
                            message=f"Unknown message type: {data.get('type')}",
                            code="unknown_type"
                        ).model_dump())
                        continue

                    # Handle different request types
                    if isinstance(request, CreateSessionRequest):
                        current_session = await self._handle_create_session(
                            request, send_message
                        )

                    elif isinstance(request, PromptRequest):
                        if current_session is None or current_session.session_id != request.session_id:
                            # Try to get the session
                            current_session = await self._session_manager.get_session(request.session_id)
                            if current_session is None:
                                await send_message(ErrorEvent(
                                    session_id=request.session_id,
                                    message="Session not found",
                                    code="session_not_found"
                                ).model_dump())
                                continue

                        await self._handle_prompt(request, current_session, send_message)

                    elif isinstance(request, CancelRequest):
                        await self._handle_cancel(request, send_message)

                    elif isinstance(request, CloseSessionRequest):
                        await self._handle_close_session(request, send_message)
                        current_session = None

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    await send_message(ErrorEvent(
                        message=f"Invalid JSON: {e}",
                        code="invalid_json"
                    ).model_dump())

                except Exception as e:
                    logger.exception(f"Error handling message: {e}")
                    await send_message(ErrorEvent(
                        session_id=current_session.session_id if current_session else None,
                        message=f"Internal error: {e}",
                        code="internal_error"
                    ).model_dump())

        except ConnectionClosed as e:
            # Normal close (1000) or going away (1001) are expected
            disconnected_normally = True
            if e.code in (1000, 1001):
                logger.info(f"Client disconnected normally: {client_addr}")
            else:
                logger.warning(f"Connection closed unexpectedly: {client_addr}, code={e.code}, reason={e.reason}")

        except Exception as e:
            logger.exception(f"Connection error: {e}")

        finally:
            if not disconnected_normally:
                logger.info(f"Client disconnected: {client_addr}")
            # Clean up session if needed
            if current_session:
                # Optionally keep session alive for reconnection
                pass

    async def _handle_create_session(
        self,
        request: CreateSessionRequest,
        send_message: Any,
    ) -> SessionState:
        """Handle create_session request."""
        state = await self._session_manager.create_session(
            workspace=request.workspace,
            send_callback=send_message,
        )

        await send_message(SessionCreatedResponse(
            session_id=state.session_id,
            workspace=str(state.workspace),
        ).model_dump())

        return state

    async def _handle_prompt(
        self,
        request: PromptRequest,
        session: SessionState,
        send_message: Any,
    ) -> None:
        """Handle prompt request."""
        session.cancelled = False

        # Create cancel event
        cancel_event = asyncio.Event()
        session.agent.cancel_event = cancel_event

        try:
            if request.stream:
                # Streaming mode
                await self._run_streaming(request, session, send_message)
            else:
                # Complete mode
                await self._run_complete(request, session, send_message)

        except asyncio.CancelledError:
            await send_message(CompletedEvent(
                session_id=session.session_id,
                stop_reason="cancelled"
            ).model_dump())

        except Exception as e:
            logger.exception(f"Error running agent: {e}")
            await send_message(ErrorEvent(
                session_id=session.session_id,
                message=f"Error running agent: {e}",
                code="agent_error"
            ).model_dump())

        finally:
            session.agent.cancel_event = None

    async def _run_streaming(
        self,
        request: PromptRequest,
        session: SessionState,
        send_message: Any,
    ) -> None:
        """Run agent in streaming mode."""
        stop_reason = "end_turn"

        async def on_thinking(content: str) -> None:
            await send_message(ThinkingEvent(
                session_id=session.session_id,
                content=content,
            ).model_dump())

        async def on_message_chunk(content: str) -> None:
            await send_message(MessageChunkEvent(
                session_id=session.session_id,
                content=content,
            ).model_dump())

        async def on_message(content: str) -> None:
            await send_message(MessageEvent(
                session_id=session.session_id,
                content=content,
            ).model_dump())

        async def on_tool_call(tool_name: str, tool_call_id: str, args: dict) -> None:
            await send_message(ToolCallEvent(
                session_id=session.session_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=args,
            ).model_dump())

        async def on_tool_result(
            tool_call_id: str,
            tool_name: str,
            success: bool,
            content: str,
            error: str | None
        ) -> None:
            await send_message(ToolResultEvent(
                session_id=session.session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                success=success,
                content=content,
                error=error,
            ).model_dump())

        # Create streaming agent wrapper
        streaming_agent = StreamingAgent(
            agent=session.agent,
            session_id=session.session_id,
            on_thinking=on_thinking,
            on_message_chunk=on_message_chunk,
            on_message=on_message,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )

        # Run streaming
        try:
            final_content = await streaming_agent.run_streaming(request.content)

            # Check if cancelled
            if session.cancelled or (session.agent.cancel_event and session.agent.cancel_event.is_set()):
                stop_reason = "cancelled"

            await send_message(CompletedEvent(
                session_id=session.session_id,
                stop_reason=stop_reason,
            ).model_dump())

        except asyncio.CancelledError:
            await send_message(CompletedEvent(
                session_id=session.session_id,
                stop_reason="cancelled"
            ).model_dump())
            raise

    async def _run_complete(
        self,
        request: PromptRequest,
        session: SessionState,
        send_message: Any,
    ) -> None:
        """Run agent in complete mode."""
        stop_reason = "end_turn"

        # Create streaming agent wrapper (no callbacks for complete mode)
        streaming_agent = StreamingAgent(
            agent=session.agent,
            session_id=session.session_id,
        )

        # Run and get complete response
        try:
            content, thinking, stop_reason = await streaming_agent.run_complete(request.content)

            # Send thinking if any
            if thinking:
                await send_message(ThinkingEvent(
                    session_id=session.session_id,
                    content=thinking,
                ).model_dump())

            # Send complete message
            await send_message(MessageEvent(
                session_id=session.session_id,
                content=content,
            ).model_dump())

            # Check if cancelled
            if session.cancelled or (session.agent.cancel_event and session.agent.cancel_event.is_set()):
                stop_reason = "cancelled"

            await send_message(CompletedEvent(
                session_id=session.session_id,
                stop_reason=stop_reason,
            ).model_dump())

        except asyncio.CancelledError:
            await send_message(CompletedEvent(
                session_id=session.session_id,
                stop_reason="cancelled"
            ).model_dump())
            raise

    async def _handle_cancel(
        self,
        request: CancelRequest,
        send_message: Any,
    ) -> None:
        """Handle cancel request."""
        success = await self._session_manager.cancel_session(request.session_id)

        if not success:
            await send_message(ErrorEvent(
                session_id=request.session_id,
                message="Session not found",
                code="session_not_found"
            ).model_dump())

    async def _handle_close_session(
        self,
        request: CloseSessionRequest,
        send_message: Any,
    ) -> None:
        """Handle close_session request."""
        success = await self._session_manager.close_session(request.session_id)

        if not success:
            await send_message(ErrorEvent(
                session_id=request.session_id,
                message="Session not found",
                code="session_not_found"
            ).model_dump())

    async def run(self) -> None:
        """Run the WebSocket server."""
        await self.initialize()

        logger.info(f"Starting WebSocket server on {self._host}:{self._port}")

        async with serve(
            self.handle_connection,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        ):
            logger.info(f"Server listening on ws://{self._host}:{self._port}")
            await asyncio.Future()  # Run forever


async def run_server(host: str = "localhost", port: int = 8765) -> None:
    """Run the WebSocket server.

    Args:
        host: Host to bind to
        port: Port to listen on
    """
    # Load configuration
    config_path = Config.get_default_config_path()

    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = Config.from_yaml(config_path)

    # Create and run server
    server = MiniAgentWebSocketServer(config, host, port)
    await server.run()


def main() -> None:
    """Main entry point for the WebSocket server."""
    parser = argparse.ArgumentParser(
        description="Mini-Agent WebSocket Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mini-agent-server                          # Start server on default port 8765
  mini-agent-server --port 9000              # Start server on port 9000
  mini-agent-server --host 0.0.0.0 --port 8765  # Bind to all interfaces
        """,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to bind to (default: localhost)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        raise SystemExit(1)


__all__ = ["MiniAgentWebSocketServer", "run_server", "main"]