"""Memory profiling and monitoring utilities for Mini-Agent.

This module provides tools to detect and diagnose memory leaks:
- Memory snapshot comparison
- Object reference tracking
- Periodic memory monitoring
- Background resource cleanup detection
"""

import gc
import os
import sys
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class MemorySnapshot:
    """Memory usage snapshot."""

    timestamp: datetime
    rss_mb: float  # Resident Set Size in MB
    vms_mb: float  # Virtual Memory Size in MB
    python_objects: int  # Number of tracked Python objects
    total_alloc_mb: float  # Total allocated memory (tracemalloc)
    top_allocations: list[tuple[str, float]] = field(default_factory=list)  # (filename:lineno, size_mb)


class MemoryProfiler:
    """Memory profiler for detecting memory leaks in Mini-Agent."""

    _instance: Optional["MemoryProfiler"] = None

    def __init__(
        self,
        enable_tracemalloc: bool = True,
        snapshot_interval: float = 30.0,
        log_file: Optional[Path] = None,
    ):
        """Initialize memory profiler.

        Args:
            enable_tracemalloc: Enable Python's tracemalloc for detailed allocation tracking
            snapshot_interval: Interval in seconds for automatic snapshots
            log_file: Optional file path to write memory logs
        """
        self.enable_tracemalloc = enable_tracemalloc
        self.snapshot_interval = snapshot_interval
        self.log_file = log_file or (Path.home() / ".mini-agent" / "memory_profile.log")

        self._snapshots: list[MemorySnapshot] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._baseline: Optional[MemorySnapshot] = None
        self._callbacks: list[Callable[[MemorySnapshot], None]] = []

        # Start tracemalloc if enabled
        if self.enable_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start(25)  # Track up to 25 frames

    @classmethod
    def get_instance(cls) -> "MemoryProfiler":
        """Get singleton instance of MemoryProfiler."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_process_memory(self) -> tuple[float, float]:
        """Get current process memory usage in MB.

        Returns:
            Tuple of (RSS MB, VMS MB)
        """
        try:
            import psutil

            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return mem_info.rss / 1024 / 1024, mem_info.vms / 1024 / 1024
        except ImportError:
            # Fallback: estimate from sys.getsizeof
            gc.collect()
            total = sum(sys.getsizeof(obj) for obj in gc.get_objects()) / 1024 / 1024
            return total, total * 2  # Rough estimate

    def get_tracemalloc_stats(self) -> tuple[float, list[tuple[str, float]]]:
        """Get tracemalloc allocation statistics.

        Returns:
            Tuple of (total allocated MB, top allocations list)
        """
        if not tracemalloc.is_tracing():
            return 0.0, []

        current, _ = tracemalloc.get_traced_memory()
        total_mb = current / 1024 / 1024

        # Get top allocations
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")
        top_allocations = [
            (str(stat.traceback[0]), stat.size / 1024 / 1024)
            for stat in top_stats[:10]
        ]

        return total_mb, top_allocations

    def take_snapshot(self) -> MemorySnapshot:
        """Take a memory snapshot.

        Returns:
            MemorySnapshot with current memory statistics
        """
        rss_mb, vms_mb = self.get_process_memory()
        total_alloc_mb, top_allocations = self.get_tracemalloc_stats()

        # Count Python objects
        gc.collect()
        python_objects = len(gc.get_objects())

        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            python_objects=python_objects,
            total_alloc_mb=total_alloc_mb,
            top_allocations=top_allocations,
        )

        self._snapshots.append(snapshot)

        # Write to log file
        self._log_snapshot(snapshot)

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(snapshot)
            except Exception:
                pass

        return snapshot

    def set_baseline(self) -> MemorySnapshot:
        """Set baseline snapshot for comparison.

        Returns:
            The baseline snapshot
        """
        self._baseline = self.take_snapshot()
        return self._baseline

    def compare_to_baseline(self) -> dict[str, Any]:
        """Compare current memory to baseline.

        Returns:
            Dictionary with comparison results
        """
        if self._baseline is None:
            return {"error": "No baseline set"}

        current = self.take_snapshot()

        return {
            "baseline_time": self._baseline.timestamp.isoformat(),
            "current_time": current.timestamp.isoformat(),
            "rss_delta_mb": current.rss_mb - self._baseline.rss_mb,
            "vms_delta_mb": current.vms_mb - self._baseline.vms_mb,
            "objects_delta": current.python_objects - self._baseline.python_objects,
            "alloc_delta_mb": current.total_alloc_mb - self._baseline.total_alloc_mb,
            "potential_leak": (current.rss_mb - self._baseline.rss_mb) > 50,  # > 50MB growth
        }

    def start_monitoring(self):
        """Start automatic memory monitoring thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()

        def monitor_loop():
            while not self._stop_event.is_set():
                self.take_snapshot()
                self._stop_event.wait(self.snapshot_interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="MemoryMonitor")
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop automatic memory monitoring."""
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

    def add_callback(self, callback: Callable[[MemorySnapshot], None]):
        """Add callback to be notified on each snapshot.

        Args:
            callback: Function to call with each MemorySnapshot
        """
        self._callbacks.append(callback)

    def _log_snapshot(self, snapshot: MemorySnapshot):
        """Write snapshot to log file.

        Args:
            snapshot: The snapshot to log
        """
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"Memory Snapshot: {snapshot.timestamp.isoformat()}\n")
                f.write(f"{'=' * 60}\n")
                f.write(f"RSS Memory: {snapshot.rss_mb:.2f} MB\n")
                f.write(f"VMS Memory: {snapshot.vms_mb:.2f} MB\n")
                f.write(f"Python Objects: {snapshot.python_objects}\n")
                f.write(f"Traced Allocations: {snapshot.total_alloc_mb:.2f} MB\n")

                if snapshot.top_allocations:
                    f.write("\nTop Allocations:\n")
                    for loc, size in snapshot.top_allocations:
                        f.write(f"  {loc}: {size:.2f} MB\n")
        except Exception:
            pass

    def get_object_summary(self) -> dict[str, int]:
        """Get summary of Python objects by type.

        Returns:
            Dictionary mapping type name to count
        """
        gc.collect()
        type_counts: dict[str, int] = {}

        for obj in gc.get_objects():
            type_name = type(obj).__name__
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        # Sort by count
        return dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20])

    def find_leaking_objects(self, min_size: int = 1000) -> list[tuple[str, int, int]]:
        """Find potentially leaking large objects.

        Args:
            min_size: Minimum size in bytes to consider

        Returns:
            List of (type_name, count, total_size) tuples
        """
        gc.collect()
        type_sizes: dict[str, tuple[int, int]] = {}  # type -> (count, total_size)

        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
                if size >= min_size:
                    type_name = type(obj).__name__
                    count, total = type_sizes.get(type_name, (0, 0))
                    type_sizes[type_name] = (count + 1, total + size)
            except Exception:
                pass

        # Sort by total size
        result = [
            (type_name, count, total_size)
            for type_name, (count, total_size) in type_sizes.items()
        ]
        return sorted(result, key=lambda x: x[2], reverse=True)[:20]

    def force_gc(self) -> dict[str, int]:
        """Force garbage collection and return stats.

        Returns:
            Dictionary with GC statistics
        """
        before = len(gc.get_objects())
        collected = gc.collect()
        after = len(gc.get_objects())

        return {
            "objects_before": before,
            "objects_after": after,
            "objects_collected": before - after,
            "gc_collected": collected,
        }

    def get_report(self) -> str:
        """Generate a comprehensive memory report.

        Returns:
            Human-readable memory report string
        """
        snapshot = self.take_snapshot()
        object_summary = self.get_object_summary()
        leaking = self.find_leaking_objects()

        report = []
        report.append("\n" + "=" * 60)
        report.append("MINI-AGENT MEMORY REPORT")
        report.append("=" * 60)
        report.append(f"Time: {snapshot.timestamp.isoformat()}")
        report.append(f"RSS Memory: {snapshot.rss_mb:.2f} MB")
        report.append(f"VMS Memory: {snapshot.vms_mb:.2f} MB")
        report.append(f"Python Objects: {snapshot.python_objects}")
        report.append(f"Traced Allocations: {snapshot.total_alloc_mb:.2f} MB")

        if self._baseline:
            report.append("\nComparison to Baseline:")
            comparison = self.compare_to_baseline()
            report.append(f"  RSS Delta: {comparison['rss_delta_mb']:.2f} MB")
            report.append(f"  Objects Delta: {comparison['objects_delta']}")
            report.append(f"  Potential Leak: {comparison['potential_leak']}")

        report.append("\nTop Object Types by Count:")
        for type_name, count in list(object_summary.items())[:10]:
            report.append(f"  {type_name}: {count}")

        report.append("\nTop Object Types by Size:")
        for type_name, count, size in leaking[:10]:
            report.append(f"  {type_name}: {count} objects, {size / 1024 / 1024:.2f} MB total")

        if snapshot.top_allocations:
            report.append("\nTop Memory Allocations:")
            for loc, size in snapshot.top_allocations[:5]:
                report.append(f"  {loc}: {size:.2f} MB")

        report.append("=" * 60)

        return "\n".join(report)


class ResourceTracker:
    """Track specific resources for potential leaks."""

    def __init__(self):
        self._resources: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, resource_type: str, resource_id: str, metadata: Optional[dict] = None):
        """Register a resource for tracking.

        Args:
            resource_type: Type of resource (e.g., 'mcp_connection', 'background_shell')
            resource_id: Unique identifier for the resource
            metadata: Optional metadata dictionary
        """
        with self._lock:
            if resource_type not in self._resources:
                self._resources[resource_type] = {}
            self._resources[resource_type][resource_id] = {
                "registered_at": datetime.now(),
                "metadata": metadata or {},
            }

    def unregister(self, resource_type: str, resource_id: str):
        """Unregister a resource.

        Args:
            resource_type: Type of resource
            resource_id: Unique identifier for the resource
        """
        with self._lock:
            if resource_type in self._resources and resource_id in self._resources[resource_type]:
                del self._resources[resource_type][resource_id]

    def get_active(self, resource_type: Optional[str] = None) -> dict[str, Any]:
        """Get active resources.

        Args:
            resource_type: Optional filter by resource type

        Returns:
            Dictionary of active resources
        """
        with self._lock:
            if resource_type:
                return dict(self._resources.get(resource_type, {}))
            return {k: dict(v) for k, v in self._resources.items()}

    def get_leaks_report(self, max_age_seconds: float = 3600) -> list[dict]:
        """Find potentially leaked resources (active for too long).

        Args:
            max_age_seconds: Maximum expected lifetime in seconds

        Returns:
            List of potentially leaked resources
        """
        now = datetime.now()
        leaks = []

        with self._lock:
            for resource_type, resources in self._resources.items():
                for resource_id, info in resources.items():
                    age = (now - info["registered_at"]).total_seconds()
                    if age > max_age_seconds:
                        leaks.append({
                            "type": resource_type,
                            "id": resource_id,
                            "age_seconds": age,
                            "metadata": info["metadata"],
                        })

        return leaks


# Global resource tracker instance
_resource_tracker: Optional[ResourceTracker] = None


def get_resource_tracker() -> ResourceTracker:
    """Get global resource tracker instance."""
    global _resource_tracker
    if _resource_tracker is None:
        _resource_tracker = ResourceTracker()
    return _resource_tracker


def profile_agent_memory(agent: Any) -> dict[str, Any]:
    """Profile an Agent instance for memory usage.

    Args:
        agent: Agent instance to profile

    Returns:
        Dictionary with memory profile data
    """
    profile = {
        "message_count": len(agent.messages),
        "message_sizes": [],
        "total_message_size": 0,
        "tools_count": len(agent.tools),
        "potential_issues": [],
    }

    # Analyze messages
    for i, msg in enumerate(agent.messages):
        try:
            content_size = sys.getsizeof(str(msg.content))
            if msg.thinking:
                content_size += sys.getsizeof(msg.thinking)
            if msg.tool_calls:
                content_size += sys.getsizeof(msg.tool_calls)
            profile["message_sizes"].append(content_size)
            profile["total_message_size"] += content_size

            # Flag large messages
            if content_size > 100_000:  # > 100KB
                profile["potential_issues"].append({
                    "type": "large_message",
                    "index": i,
                    "role": msg.role,
                    "size_bytes": content_size,
                })
        except Exception:
            pass

    profile["avg_message_size"] = profile["total_message_size"] / max(len(agent.messages), 1)

    # Check for potential issues
    if profile["message_count"] > 100:
        profile["potential_issues"].append({
            "type": "many_messages",
            "count": profile["message_count"],
            "recommendation": "Consider summarizing or clearing message history",
        })

    if profile["total_message_size"] > 10_000_000:  # > 10MB
        profile["potential_issues"].append({
            "type": "large_history",
            "total_size_mb": profile["total_message_size"] / 1024 / 1024,
            "recommendation": "Message history is large, consider summarization",
        })

    return profile