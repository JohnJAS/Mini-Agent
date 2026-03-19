"""
Example: Memory Profiling for Mini-Agent

This example demonstrates how to use the memory profiling tools
to detect and diagnose memory leaks in Mini-Agent applications.
"""

import asyncio
from pathlib import Path

from mini_agent import LLMClient
from mini_agent.agent import Agent
from mini_agent.tools.bash_tool import BashTool, BackgroundShellManager
from mini_agent.tools.mcp_loader import get_mcp_connections_stats


async def agent_loop_memory_tracking():
    """Demonstrate fine-grained memory tracking for an agent loop."""
    from mini_agent.utils.memory_profiler import AgentLoopMemoryTracker

    tracker = AgentLoopMemoryTracker(enable_tracemalloc=True)

    llm_client = LLMClient(
        api_key="your-api-key",
        model="MiniMax-M2.5",
    )

    agent = Agent(
        llm_client=llm_client,
        system_prompt="You are a helpful assistant.",
        tools=[BashTool()],
        memory_tracker=tracker,
    )

    agent.add_user_message("List files in current directory")

    result = await agent.run()
    print(f"\nAgent result: result...")


async def manual_memory_tracking():
    """Demonstrate manual memory tracking for custom workflows."""
    from mini_agent.utils.memory_profiler import AgentLoopMemoryTracker

    tracker = AgentLoopMemoryTracker(enable_tracemalloc=True)

    tracker.start_loop()

    for step in range(3):
        tracker.record_step_start(step)

        tracker.record_llm_before(step)
        await asyncio.sleep(0.1)
        tracker.record_llm_after(step)

        tracker.record_tool_before(step, "bash")
        await asyncio.sleep(0.05)
        tracker.record_tool_after(step, "bash")

        tracker.record_step_end(step)

    tracker.end_loop()

    report = tracker.generate_report()
    tracker.print_report(report)

    output_path = Path("./workspace/memory_report.json")
    tracker.save_report(str(output_path), report)
    print(f"\nReport saved to: {output_path}")


async def memory_profiling_example():
    """Demonstrate memory profiling capabilities."""

    # Import memory profiler
    from mini_agent.utils.memory_profiler import (
        MemoryProfiler,
        get_resource_tracker,
        profile_agent_memory,
    )

    # Initialize memory profiler
    profiler = MemoryProfiler(
        enable_tracemalloc=True,
        snapshot_interval=10.0,
    )

    # Set baseline
    print("Setting memory baseline...")
    baseline = profiler.set_baseline()
    print(f"Baseline RSS: {baseline.rss_mb:.2f} MB")
    print(f"Baseline Python Objects: {baseline.python_objects}")

    # Start continuous monitoring (runs in background thread)
    profiler.start_monitoring()

    # Create a simple agent
    llm_client = LLMClient(
        api_key="your-api-key",
        model="MiniMax-M2.5",
    )

    agent = Agent(
        llm_client=llm_client,
        system_prompt="You are a helpful assistant.",
        tools=[BashTool()],
    )

    # Simulate some work
    print("\nSimulating agent activity...")
    for i in range(5):
        agent.add_user_message(
            f"Task {i + 1}: This is a test message with some content."
        )
        # Simulate assistant response
        from mini_agent.schema import Message

        agent.messages.append(
            Message(
                role="assistant",
                content="This is a simulated response that could be quite long...",
            )
        )

    # Profile the agent
    print("\nProfiling agent memory...")
    profile = profile_agent_memory(agent)
    print(f"Message count: {profile['message_count']}")
    print(f"Total message size: {profile['total_message_size'] / 1024:.2f} KB")
    print(f"Average message size: {profile['avg_message_size']:.2f} bytes")

    if profile["potential_issues"]:
        print("\nPotential issues detected:")
        for issue in profile["potential_issues"]:
            print(f"  - {issue}")

    # Get resource tracker stats
    tracker = get_resource_tracker()
    leaks = tracker.get_leaks_report(max_age_seconds=60)
    if leaks:
        print("\nPotential resource leaks:")
        for leak in leaks:
            print(f"  - {leak['type']}: {leak['id']} (age: {leak['age_seconds']:.1f}s)")

    # Compare to baseline
    print("\nComparing to baseline...")
    comparison = profiler.compare_to_baseline()
    print(f"RSS Delta: {comparison['rss_delta_mb']:.2f} MB")
    print(f"Objects Delta: {comparison['objects_delta']}")
    print(f"Potential Leak: {comparison['potential_leak']}")

    # Force garbage collection
    print("\nForcing garbage collection...")
    gc_stats = profiler.force_gc()
    print(f"Objects collected: {gc_stats['objects_collected']}")

    # Generate full report
    print("\n" + profiler.get_report())

    # Stop monitoring
    profiler.stop_monitoring()


def demo_background_shell_memory():
    """Demonstrate background shell memory management."""
    print("\n=== Background Shell Memory Demo ===")

    # Check background shell stats
    stats = BackgroundShellManager.get_memory_stats()
    print(f"Total shells: {stats['total_shells']}")
    print(f"Running shells: {stats['running_shells']}")
    print(f"Completed shells: {stats['completed_shells']}")
    print(f"Total output lines: {stats['total_output_lines']}")

    # Clean up all shells
    cleaned = BackgroundShellManager.cleanup_all()
    print(f"Cleaned up {cleaned} shells")


def demo_mcp_memory():
    """Demonstrate MCP connection memory tracking."""
    print("\n=== MCP Connection Memory Demo ===")

    stats = get_mcp_connections_stats()
    print(f"Total connections: {stats['total_connections']}")

    for conn in stats["connections"]:
        print(
            f"  - {conn['name']}: {conn['tools_count']} tools, session={conn['has_session']}"
        )


if __name__ == "__main__":
    print("Mini-Agent Memory Profiling Demo")
    print("=" * 50)

    print("\n=== Agent Loop Memory Tracking Demo ===")
    asyncio.run(manual_memory_tracking())

    print("\n=== Memory Profiling Example ===")
    asyncio.run(memory_profiling_example())

    demo_background_shell_memory()
    demo_mcp_memory()

    print("\nDemo completed!")
