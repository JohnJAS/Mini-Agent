#!/usr/bin/env python
"""Mini-Agent WebSocket Client CLI for OpenClaw integration.

A command-line tool that connects to a running Mini-Agent WebSocket server,
sends tasks, and returns results. Designed for integration with OpenClaw skills.

Usage:
    mini-agent-exec "Your task here"
    mini-agent-exec --workspace /path/to/dir "Create a file"
    mini-agent-exec --url ws://localhost:8765 "Your task"
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Fix Windows console encoding for UTF-8 support
if sys.platform == "win32":
    import os
    # Set environment variables for UTF-8
    os.environ["PYTHONIOENCODING"] = "utf-8"
    # Reconfigure stdout/stderr for UTF-8
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

from .client import MiniAgentClient, AgentResponse

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def print_response(response: AgentResponse, verbose: bool = False) -> None:
    """Print the agent response.

    Args:
        response: The agent response
        verbose: Whether to print detailed information
    """
    if verbose:
        # Print thinking if available
        if response.thinking:
            print("\n=== Thinking ===")
            print(response.thinking)
            print("=== End Thinking ===\n")

        # Print tool calls if any
        if response.tool_calls:
            print("\n=== Tool Calls ===")
            for tc in response.tool_calls:
                print(f"  {tc.tool_name}({json.dumps(tc.arguments, indent=2)})")
            print("=== End Tool Calls ===\n")

        if response.tool_results:
            print("\n=== Tool Results ===")
            for tr in response.tool_results:
                status = "✓" if tr.success else "✗"
                print(f"  {status} {tr.tool_name}")
                if tr.error:
                    print(f"    Error: {tr.error}")
            print("=== End Tool Results ===\n")

    # Always print the main content
    print(response.content)

    if verbose:
        print(f"\n[Stop reason: {response.stop_reason}]")


async def execute_task(
    task: str,
    url: str = "ws://localhost:8765",
    workspace: Optional[str] = None,
    stream: bool = False,
    verbose: bool = False,
    timeout: float = 300.0,
) -> int:
    """Execute a task via Mini-Agent WebSocket server.

    Args:
        task: The task to execute
        url: WebSocket server URL
        workspace: Optional workspace directory
        stream: Whether to stream output
        verbose: Whether to print verbose output
        timeout: Timeout in seconds

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    try:
        async with MiniAgentClient(url, workspace) as client:
            if verbose:
                print(f"Connected to {url}")
                if workspace:
                    print(f"Workspace: {workspace}")
                print(f"Session: {client.session_id}")
                print()

            if stream:
                # Stream mode with real-time output
                async for event in client.send_message_stream(task):
                    event_type = event.get("type")

                    if event_type == "thinking":
                        if verbose:
                            print(f"\n[Thinking] {event['content'][:200]}...")

                    elif event_type == "message_chunk":
                        print(event["content"], end="", flush=True)

                    elif event_type == "tool_call":
                        if verbose:
                            print(f"\n[Tool] {event['tool_name']}")

                    elif event_type == "tool_result":
                        if verbose:
                            status = "✓" if event["success"] else "✗"
                            print(f"[Result] {status} {event['tool_name']}")

                    elif event_type == "completed":
                        print()  # Newline after streaming
                        if verbose:
                            print(f"\n[Completed: {event['stop_reason']}]")

                    elif event_type == "error":
                        print(f"\nError: {event['message']}", file=sys.stderr)
                        return 1
            else:
                # Complete mode - wait for full response
                response = await asyncio.wait_for(
                    client.send_message(task, stream=False),
                    timeout=timeout
                )
                print_response(response, verbose)

            return 0

    except asyncio.TimeoutError:
        print(f"Error: Timeout after {timeout} seconds", file=sys.stderr)
        return 1

    except ConnectionRefusedError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        print("Make sure Mini-Agent server is running:", file=sys.stderr)
        print("  mini-agent-server", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> None:
    """Main entry point for mini-agent-exec CLI."""
    parser = argparse.ArgumentParser(
        description="Execute tasks via Mini-Agent WebSocket server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mini-agent-exec "Create a hello.txt file with greeting"
  mini-agent-exec --workspace ./myproject "Refactor the main.py file"
  mini-agent-exec --stream "Write a Python script to fetch weather data"
  mini-agent-exec --url ws://remote:8765 "Your task"

Prerequisites:
  Mini-Agent WebSocket server must be running:
    mini-agent-server
        """,
    )

    parser.add_argument(
        "task",
        type=str,
        help="The task to execute",
    )

    parser.add_argument(
        "--url",
        type=str,
        default="ws://localhost:8765",
        help="WebSocket server URL (default: ws://localhost:8765)",
    )

    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=None,
        help="Workspace directory path",
    )

    parser.add_argument(
        "--stream",
        "-s",
        action="store_true",
        help="Stream output in real-time",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose output including thinking and tool calls",
    )

    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=300.0,
        help="Timeout in seconds (default: 300)",
    )

    args = parser.parse_args()

    # Validate workspace if provided
    if args.workspace:
        workspace_path = Path(args.workspace).expanduser().resolve()
        if not workspace_path.exists():
            print(f"Error: Workspace does not exist: {workspace_path}", file=sys.stderr)
            sys.exit(1)
        args.workspace = str(workspace_path)

    # Run the async function
    exit_code = asyncio.run(
        execute_task(
            task=args.task,
            url=args.url,
            workspace=args.workspace,
            stream=args.stream,
            verbose=args.verbose,
            timeout=args.timeout,
        )
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()