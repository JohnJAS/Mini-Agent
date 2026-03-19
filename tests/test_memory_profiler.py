"""Tests for memory profiling utilities."""

import gc
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from mini_agent.utils.memory_profiler import (
    MemoryProfiler,
    MemorySnapshot,
    ResourceTracker,
    get_resource_tracker,
    profile_agent_memory,
)


class TestMemorySnapshot:
    """Tests for MemorySnapshot dataclass."""

    def test_create_snapshot(self):
        """Test creating a memory snapshot."""
        snapshot = MemorySnapshot(
            timestamp=time.time(),
            rss_mb=100.0,
            vms_mb=200.0,
            python_objects=10000,
            total_alloc_mb=50.0,
        )
        assert snapshot.rss_mb == 100.0
        assert snapshot.vms_mb == 200.0
        assert snapshot.python_objects == 10000


class TestMemoryProfiler:
    """Tests for MemoryProfiler class."""

    def test_singleton(self):
        """Test singleton pattern."""
        profiler1 = MemoryProfiler.get_instance()
        profiler2 = MemoryProfiler.get_instance()
        assert profiler1 is profiler2

    def test_take_snapshot(self):
        """Test taking a memory snapshot."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        snapshot = profiler.take_snapshot()

        assert snapshot.rss_mb > 0
        assert snapshot.vms_mb > 0
        assert snapshot.python_objects > 0

    def test_set_baseline(self):
        """Test setting baseline."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        baseline = profiler.set_baseline()

        assert baseline is not None
        assert profiler._baseline is baseline

    def test_compare_to_baseline(self):
        """Test comparison to baseline."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.set_baseline()

        # Create some objects
        _ = [list(range(1000)) for _ in range(10)]

        comparison = profiler.compare_to_baseline()
        assert "rss_delta_mb" in comparison
        assert "potential_leak" in comparison

    def test_callback_on_snapshot(self):
        """Test callback is called on snapshot."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        callback_called = []

        def callback(snapshot):
            callback_called.append(snapshot)

        profiler.add_callback(callback)
        profiler.take_snapshot()

        assert len(callback_called) == 1

    def test_get_object_summary(self):
        """Test getting object summary."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        summary = profiler.get_object_summary()

        assert isinstance(summary, dict)
        assert len(summary) > 0

    def test_find_leaking_objects(self):
        """Test finding leaking objects."""
        profiler = MemoryProfiler(enable_tracemalloc=False)

        # Create some large objects
        large_list = [0] * 10000
        large_dict = {i: i for i in range(10000)}

        leaking = profiler.find_leaking_objects(min_size=100)

        assert isinstance(leaking, list)
        # Should find at least some objects
        assert len(leaking) > 0

        # Clean up
        del large_list
        del large_dict
        gc.collect()

    def test_force_gc(self):
        """Test forced garbage collection."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        stats = profiler.force_gc()

        assert "objects_before" in stats
        assert "objects_after" in stats
        assert "gc_collected" in stats

    def test_get_report(self):
        """Test getting memory report."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.set_baseline()
        report = profiler.get_report()

        assert "MEMORY REPORT" in report
        assert "RSS Memory:" in report

    def test_monitoring_thread(self):
        """Test starting and stopping monitoring."""
        profiler = MemoryProfiler(
            enable_tracemalloc=False,
            snapshot_interval=0.1,
        )

        profiler.start_monitoring()
        assert profiler._monitor_thread is not None
        assert profiler._monitor_thread.is_alive()

        time.sleep(0.3)  # Let it take a snapshot

        profiler.stop_monitoring()
        # Thread is set to None after stopping
        assert profiler._monitor_thread is None


class TestResourceTracker:
    """Tests for ResourceTracker class."""

    def test_register_unregister(self):
        """Test registering and unregistering resources."""
        tracker = ResourceTracker()

        tracker.register("test_type", "test_id", {"key": "value"})
        assert len(tracker.get_active("test_type")) == 1

        tracker.unregister("test_type", "test_id")
        assert len(tracker.get_active("test_type")) == 0

    def test_get_active(self):
        """Test getting active resources."""
        tracker = ResourceTracker()

        tracker.register("type1", "id1")
        tracker.register("type1", "id2")
        tracker.register("type2", "id3")

        active_type1 = tracker.get_active("type1")
        assert len(active_type1) == 2

        all_active = tracker.get_active()
        assert "type1" in all_active
        assert "type2" in all_active

    def test_get_leaks_report(self):
        """Test detecting potential leaks."""
        tracker = ResourceTracker()

        # Register an old resource
        tracker.register("old_type", "old_id")
        # Manually set old timestamp
        import datetime
        tracker._resources["old_type"]["old_id"]["registered_at"] = datetime.datetime.now() - datetime.timedelta(hours=2)

        # Register a new resource
        tracker.register("new_type", "new_id")

        # Find leaks (resources older than 1 hour)
        leaks = tracker.get_leaks_report(max_age_seconds=3600)

        assert len(leaks) == 1
        assert leaks[0]["id"] == "old_id"


class TestProfileAgentMemory:
    """Tests for agent memory profiling."""

    def test_profile_agent_memory(self):
        """Test profiling agent memory."""
        # Create a mock agent
        mock_agent = MagicMock()
        mock_agent.messages = []
        mock_agent.tools = {}

        # Add some messages
        from mini_agent.schema import Message

        mock_agent.messages.append(Message(role="system", content="System prompt"))
        mock_agent.messages.append(Message(role="user", content="Hello" * 1000))
        mock_agent.messages.append(Message(role="assistant", content="Hi there!" * 500))

        profile = profile_agent_memory(mock_agent)

        assert profile["message_count"] == 3
        assert profile["tools_count"] == 0
        assert profile["total_message_size"] > 0
        assert len(profile["message_sizes"]) == 3


class TestIntegration:
    """Integration tests for memory profiling."""

    def test_full_profiling_workflow(self):
        """Test full profiling workflow."""
        profiler = MemoryProfiler(enable_tracemalloc=False)
        tracker = get_resource_tracker()

        # Set baseline
        profiler.set_baseline()

        # Simulate agent activity
        messages = []
        for i in range(100):
            messages.append({"role": "user", "content": f"Message {i}" * 100})

        # Track a resource
        tracker.register("test_connection", "conn_1", {"url": "test://localhost"})

        # Take snapshot
        snapshot = profiler.take_snapshot()
        assert snapshot.python_objects > 0

        # Check for leaks
        comparison = profiler.compare_to_baseline()
        assert isinstance(comparison["rss_delta_mb"], float)

        # Clean up
        tracker.unregister("test_connection", "conn_1")
        del messages
        gc.collect()

        # Force GC
        profiler.force_gc()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])