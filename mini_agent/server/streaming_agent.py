"""Streaming agent wrapper for WebSocket API.

Wraps the base Agent class to support streaming responses via callbacks.
"""

import asyncio
import logging
from typing import Callable, Any, Awaitable

from mini_agent.agent import Agent
from mini_agent.schema import Message
from mini_agent.tools.base import ToolResult

logger = logging.getLogger(__name__)


class StreamingAgent:
    """Wrapper for Agent that supports streaming output via callbacks.

    This class wraps an existing Agent instance and provides methods to
    run the agent loop with streaming callbacks for thinking, message chunks,
    tool calls, and tool results.
    """

    def __init__(
        self,
        agent: Agent,
        session_id: str,
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_message_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_message: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call: Callable[[str, str, dict], Awaitable[None]] | None = None,
        on_tool_result: Callable[[str, str, bool, str, str | None], Awaitable[None]] | None = None,
    ):
        """Initialize streaming agent wrapper.

        Args:
            agent: The base Agent instance
            session_id: Session ID for logging
            on_thinking: Callback for thinking content
            on_message_chunk: Callback for message content chunks
            on_message: Callback for complete message
            on_tool_call: Callback for tool call start (tool_name, tool_call_id, arguments)
            on_tool_result: Callback for tool result (tool_call_id, tool_name, success, content, error)
        """
        self._agent = agent
        self._session_id = session_id
        self._on_thinking = on_thinking
        self._on_message_chunk = on_message_chunk
        self._on_message = on_message
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result

    async def run_streaming(self, user_input: str) -> str:
        """Run agent with streaming output.

        Args:
            user_input: User's input message

        Returns:
            Final response content
        """
        # Add user message
        self._agent.add_user_message(user_input)

        # Create cancel event
        cancel_event = asyncio.Event()
        self._agent.cancel_event = cancel_event

        try:
            result = await self._run_turns_streaming()
            return result
        finally:
            self._agent.cancel_event = None

    async def run_complete(self, user_input: str) -> tuple[str, str, str]:
        """Run agent and return complete response.

        Args:
            user_input: User's input message

        Returns:
            Tuple of (final_content, thinking_content, stop_reason)
        """
        # Add user message
        self._agent.add_user_message(user_input)

        # Create cancel event
        cancel_event = asyncio.Event()
        self._agent.cancel_event = cancel_event

        accumulated_content = ""
        accumulated_thinking = ""

        try:
            for step in range(self._agent.max_steps):
                if cancel_event.is_set():
                    return accumulated_content, accumulated_thinking, "cancelled"

                # Check for summarization
                await self._agent._summarize_messages()

                # Get tool schemas
                tool_schemas = [tool.to_schema() for tool in self._agent.tools.values()]

                try:
                    response = await self._agent.llm.generate(
                        messages=self._agent.messages,
                        tools=tool_schemas
                    )
                except Exception as exc:
                    logger.exception("LLM error")
                    error_msg = f"Error: {exc}"
                    if self._on_message:
                        await self._on_message(error_msg)
                    return error_msg, accumulated_thinking, "refusal"

                # Update token usage
                if response.usage:
                    self._agent.api_total_tokens = response.usage.total_tokens

                # Accumulate thinking
                if response.thinking:
                    accumulated_thinking += response.thinking

                # Accumulate content
                if response.content:
                    accumulated_content += response.content

                # Add assistant message
                self._agent.messages.append(Message(
                    role="assistant",
                    content=response.content,
                    thinking=response.thinking,
                    tool_calls=response.tool_calls,
                ))

                # Check if done
                if not response.tool_calls:
                    return accumulated_content, accumulated_thinking, "end_turn"

                # Process tool calls
                for call in response.tool_calls:
                    if cancel_event.is_set():
                        return accumulated_content, accumulated_thinking, "cancelled"

                    tool_name = call.function.name
                    args = call.function.arguments

                    # Execute tool
                    tool = self._agent.tools.get(tool_name)
                    if not tool:
                        result = ToolResult(
                            success=False,
                            content="",
                            error=f"Unknown tool: {tool_name}"
                        )
                    else:
                        try:
                            result = await tool.execute(**args)
                        except Exception as exc:
                            result = ToolResult(
                                success=False,
                                content="",
                                error=f"Tool execution failed: {exc}"
                            )

                    # Add tool result message
                    tool_msg = Message(
                        role="tool",
                        content=result.content if result.success else f"Error: {result.error}",
                        tool_call_id=call.id,
                        name=tool_name,
                    )
                    self._agent.messages.append(tool_msg)

            return accumulated_content, accumulated_thinking, "max_turn_requests"

        finally:
            self._agent.cancel_event = None

    async def _run_turns_streaming(self) -> str:
        """Run agent turns with streaming callbacks."""
        final_content = ""

        for step in range(self._agent.max_steps):
            if self._agent.cancel_event and self._agent.cancel_event.is_set():
                return final_content

            # Check for summarization
            await self._agent._summarize_messages()

            # Get tool schemas
            tool_schemas = [tool.to_schema() for tool in self._agent.tools.values()]

            try:
                response = await self._agent.llm.generate(
                    messages=self._agent.messages,
                    tools=tool_schemas
                )
            except Exception as exc:
                logger.exception("LLM error")
                error_msg = f"Error: {exc}"
                if self._on_message:
                    await self._on_message(error_msg)
                return error_msg

            # Update token usage
            if response.usage:
                self._agent.api_total_tokens = response.usage.total_tokens

            # Stream thinking
            if response.thinking and self._on_thinking:
                await self._on_thinking(response.thinking)

            # Stream message content
            if response.content:
                final_content = response.content
                if self._on_message_chunk:
                    await self._on_message_chunk(response.content)

            # Add assistant message
            self._agent.messages.append(Message(
                role="assistant",
                content=response.content,
                thinking=response.thinking,
                tool_calls=response.tool_calls,
            ))

            # Check if done
            if not response.tool_calls:
                return final_content

            # Process tool calls
            for call in response.tool_calls:
                if self._agent.cancel_event and self._agent.cancel_event.is_set():
                    return final_content

                tool_name = call.function.name
                args = call.function.arguments

                # Notify tool call start
                if self._on_tool_call:
                    await self._on_tool_call(tool_name, call.id, args)

                # Execute tool
                tool = self._agent.tools.get(tool_name)
                if not tool:
                    result = ToolResult(
                        success=False,
                        content="",
                        error=f"Unknown tool: {tool_name}"
                    )
                else:
                    try:
                        result = await tool.execute(**args)
                    except Exception as exc:
                        result = ToolResult(
                            success=False,
                            content="",
                            error=f"Tool execution failed: {exc}"
                        )

                # Notify tool result
                if self._on_tool_result:
                    await self._on_tool_result(
                        call.id,
                        tool_name,
                        result.success,
                        result.content if result.success else "",
                        result.error if not result.success else None
                    )

                # Add tool result message
                tool_msg = Message(
                    role="tool",
                    content=result.content if result.success else f"Error: {result.error}",
                    tool_call_id=call.id,
                    name=tool_name,
                )
                self._agent.messages.append(tool_msg)

        return final_content