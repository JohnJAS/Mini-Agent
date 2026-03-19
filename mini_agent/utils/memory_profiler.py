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


class LoopPhase:
    """Constants for agent loop phases."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    LLM_BEFORE = "llm_before"
    LLM_AFTER = "llm_after"
    TOOL_BEFORE = "tool_before"
    TOOL_AFTER = "tool_after"
    SUMMARIZE_BEFORE = "summarize_before"
    SUMMARIZE_AFTER = "summarize_after"


@dataclass
class PhaseMemoryRecord:
    """Memory record for a single phase."""

    phase: str
    step: int
    timestamp: datetime
    rss_mb: float
    vms_mb: float
    python_objects: int
    total_alloc_mb: float
    detail: Optional[str] = None


@dataclass
class StepMemorySummary:
    """Memory summary for a single agent step."""

    step: int
    start_rss_mb: float
    end_rss_mb: float
    delta_rss_mb: float
    llm_before_rss_mb: float
    llm_after_rss_mb: float
    llm_delta_mb: float
    tool_calls: list[str]
    tool_delta_mb: float
    duration_seconds: float


@dataclass
class LoopMemoryReport:
    """Complete memory report for an agent loop."""

    start_time: datetime
    end_time: datetime
    total_duration_seconds: float
    start_rss_mb: float
    end_rss_mb: float
    total_delta_rss_mb: float
    steps: list[StepMemorySummary]
    phase_records: list[PhaseMemoryRecord]
    peak_rss_mb: float
    peak_step: int
    avg_delta_per_step_mb: float
    potential_leaks: list[str]
    recommendations: list[str]


@dataclass
class MemorySnapshot:
    """Memory usage snapshot."""

    timestamp: datetime
    rss_mb: float  # Resident Set Size in MB
    vms_mb: float  # Virtual Memory Size in MB
    python_objects: int  # Number of tracked Python objects
    total_alloc_mb: float  # Total allocated memory (tracemalloc)
    top_allocations: list[tuple[str, float]] = field(
        default_factory=list
    )  # (filename:lineno, size_mb)


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
            (str(stat.traceback[0]), stat.size / 1024 / 1024) for stat in top_stats[:10]
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
            "potential_leak": (current.rss_mb - self._baseline.rss_mb)
            > 50,  # > 50MB growth
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

        self._monitor_thread = threading.Thread(
            target=monitor_loop, daemon=True, name="MemoryMonitor"
        )
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
            report.append(
                f"  {type_name}: {count} objects, {size / 1024 / 1024:.2f} MB total"
            )

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

    def register(
        self, resource_type: str, resource_id: str, metadata: Optional[dict] = None
    ):
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
            if (
                resource_type in self._resources
                and resource_id in self._resources[resource_type]
            ):
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
                        leaks.append(
                            {
                                "type": resource_type,
                                "id": resource_id,
                                "age_seconds": age,
                                "metadata": info["metadata"],
                            }
                        )

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
                profile["potential_issues"].append(
                    {
                        "type": "large_message",
                        "index": i,
                        "role": msg.role,
                        "size_bytes": content_size,
                    }
                )
        except Exception:
            pass

    profile["avg_message_size"] = profile["total_message_size"] / max(
        len(agent.messages), 1
    )

    # Check for potential issues
    if profile["message_count"] > 100:
        profile["potential_issues"].append(
            {
                "type": "many_messages",
                "count": profile["message_count"],
                "recommendation": "Consider summarizing or clearing message history",
            }
        )

    if profile["total_message_size"] > 10_000_000:  # > 10MB
        profile["potential_issues"].append(
            {
                "type": "large_history",
                "total_size_mb": profile["total_message_size"] / 1024 / 1024,
                "recommendation": "Message history is large, consider summarization",
            }
        )

    return profile


class AgentLoopMemoryTracker:
    """Track memory usage throughout an agent loop execution.

    This class provides fine-grained memory tracking at each phase of
    the agent loop: step start/end, LLM calls, tool calls, etc.

    Usage:
        tracker = AgentLoopMemoryTracker()
        tracker.start_loop()

        for step in range(max_steps):
            tracker.record_step_start(step)

            tracker.record_llm_before(step)
            response = await llm.generate(...)
            tracker.record_llm_after(step)

            for tool_call in response.tool_calls:
                tracker.record_tool_before(step, tool_call.function.name)
                result = await tool.execute(...)
                tracker.record_tool_after(step, tool_call.function.name)

            tracker.record_step_end(step)

        tracker.end_loop()
        report = tracker.generate_report()
        tracker.print_report()
        tracker.save_report("memory_report.json")
    """

    def __init__(self, enable_tracemalloc: bool = True):
        """Initialize the tracker.

        Args:
            enable_tracemalloc: Enable tracemalloc for detailed allocation tracking
        """
        self.enable_tracemalloc = enable_tracemalloc
        self._records: list[PhaseMemoryRecord] = []
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._current_step: int = -1
        self._tool_names_in_step: list[str] = []

        if self.enable_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start(25)

    def _get_memory_stats(self) -> tuple[float, float, int, float]:
        """Get current memory statistics.

        Returns:
            Tuple of (rss_mb, vms_mb, python_objects, total_alloc_mb)
        """
        rss_mb, vms_mb = 0.0, 0.0
        try:
            import psutil

            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            rss_mb = mem_info.rss / 1024 / 1024
            vms_mb = mem_info.vms / 1024 / 1024
        except ImportError:
            pass

        gc.collect()
        python_objects = len(gc.get_objects())

        total_alloc_mb = 0.0
        if tracemalloc.is_tracing():
            current, _ = tracemalloc.get_traced_memory()
            total_alloc_mb = current / 1024 / 1024

        return rss_mb, vms_mb, python_objects, total_alloc_mb

    def _record(
        self, phase: str, step: int = -1, detail: Optional[str] = None
    ) -> PhaseMemoryRecord:
        """Record a memory snapshot for a phase.

        Args:
            phase: The phase name (from LoopPhase constants)
            step: The step number (-1 for loop-level phases)
            detail: Optional detail string (e.g., tool name)

        Returns:
            The created PhaseMemoryRecord
        """
        rss_mb, vms_mb, python_objects, total_alloc_mb = self._get_memory_stats()

        record = PhaseMemoryRecord(
            phase=phase,
            step=step,
            timestamp=datetime.now(),
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            python_objects=python_objects,
            total_alloc_mb=total_alloc_mb,
            detail=detail,
        )

        self._records.append(record)
        return record

    def start_loop(self) -> PhaseMemoryRecord:
        """Mark the start of the agent loop."""
        self._start_time = datetime.now()
        self._records.clear()
        self._current_step = -1
        return self._record(LoopPhase.RUN_START)

    def end_loop(self) -> PhaseMemoryRecord:
        """Mark the end of the agent loop."""
        self._end_time = datetime.now()
        return self._record(LoopPhase.RUN_END)

    def record_step_start(self, step: int) -> PhaseMemoryRecord:
        """Record the start of a step."""
        self._current_step = step
        self._tool_names_in_step.clear()
        return self._record(LoopPhase.STEP_START, step)

    def record_step_end(self, step: int) -> PhaseMemoryRecord:
        """Record the end of a step."""
        return self._record(LoopPhase.STEP_END, step)

    def record_llm_before(self, step: int) -> PhaseMemoryRecord:
        """Record memory before an LLM call."""
        return self._record(LoopPhase.LLM_BEFORE, step)

    def record_llm_after(self, step: int) -> PhaseMemoryRecord:
        """Record memory after an LLM call."""
        return self._record(LoopPhase.LLM_AFTER, step)

    def record_tool_before(self, step: int, tool_name: str) -> PhaseMemoryRecord:
        """Record memory before a tool call."""
        self._tool_names_in_step.append(tool_name)
        return self._record(LoopPhase.TOOL_BEFORE, step, detail=tool_name)

    def record_tool_after(self, step: int, tool_name: str) -> PhaseMemoryRecord:
        """Record memory after a tool call."""
        return self._record(LoopPhase.TOOL_AFTER, step, detail=tool_name)

    def record_summarize_before(self, step: int) -> PhaseMemoryRecord:
        """Record memory before message summarization."""
        return self._record(LoopPhase.SUMMARIZE_BEFORE, step)

    def record_summarize_after(self, step: int) -> PhaseMemoryRecord:
        """Record memory after message summarization."""
        return self._record(LoopPhase.SUMMARIZE_AFTER, step)

    def _find_record(
        self, phase: str, step: int, detail: Optional[str] = None
    ) -> Optional[PhaseMemoryRecord]:
        """Find a specific record by phase and step."""
        for record in self._records:
            if record.phase == phase and record.step == step:
                if detail is None or record.detail == detail:
                    return record
        return None

    def generate_report(self) -> LoopMemoryReport:
        """Generate a comprehensive memory report.

        Returns:
            LoopMemoryReport with detailed analysis
        """
        if not self._records:
            raise ValueError("No records available. Did you call start_loop()?")

        run_start = self._find_record(LoopPhase.RUN_START, -1)
        run_end = self._find_record(LoopPhase.RUN_END, -1)

        if not run_start or not run_end:
            raise ValueError("Missing start_loop() or end_loop() records")

        # Calculate overall stats
        total_duration = (
            (self._end_time - self._start_time).total_seconds()
            if self._end_time and self._start_time
            else 0.0
        )
        total_delta = run_end.rss_mb - run_start.rss_mb

        # Find peak memory
        peak_record = max(self._records, key=lambda r: r.rss_mb)
        peak_rss = peak_record.rss_mb
        peak_step = peak_record.step

        # Analyze each step
        steps: list[StepMemorySummary] = []
        step_numbers = set(r.step for r in self._records if r.step >= 0)

        for step_num in sorted(step_numbers):
            step_start = self._find_record(LoopPhase.STEP_START, step_num)
            step_end = self._find_record(LoopPhase.STEP_END, step_num)
            llm_before = self._find_record(LoopPhase.LLM_BEFORE, step_num)
            llm_after = self._find_record(LoopPhase.LLM_AFTER, step_num)

            if not step_start or not step_end:
                continue

            duration = (step_end.timestamp - step_start.timestamp).total_seconds()

            # Calculate tool delta
            tool_delta = 0.0
            tool_names = []
            for record in self._records:
                if record.step == step_num and record.phase == LoopPhase.TOOL_BEFORE:
                    tool_names.append(record.detail or "unknown")
                    tool_before = record
                    tool_after = self._find_record(
                        LoopPhase.TOOL_AFTER, step_num, record.detail
                    )
                    if tool_after:
                        tool_delta += tool_after.rss_mb - tool_before.rss_mb

            step_summary = StepMemorySummary(
                step=step_num,
                start_rss_mb=step_start.rss_mb,
                end_rss_mb=step_end.rss_mb,
                delta_rss_mb=step_end.rss_mb - step_start.rss_mb,
                llm_before_rss_mb=llm_before.rss_mb if llm_before else 0.0,
                llm_after_rss_mb=llm_after.rss_mb if llm_after else 0.0,
                llm_delta_mb=(llm_after.rss_mb - llm_before.rss_mb)
                if llm_before and llm_after
                else 0.0,
                tool_calls=tool_names,
                tool_delta_mb=tool_delta,
                duration_seconds=duration,
            )
            steps.append(step_summary)

        avg_delta = total_delta / max(len(steps), 1)

        # Detect potential leaks
        potential_leaks: list[str] = []
        recommendations: list[str] = []

        # Check for consistent memory growth
        if len(steps) >= 3:
            deltas = [s.delta_rss_mb for s in steps]
            avg_step_delta = sum(deltas) / len(deltas)
            if avg_step_delta > 5:
                potential_leaks.append(
                    f"Consistent memory growth: avg {avg_step_delta:.2f} MB per step"
                )
                recommendations.append("Check for unbounded message history growth")

        # Check for large single-step growth
        large_growth_steps = [s for s in steps if s.delta_rss_mb > 50]
        if large_growth_steps:
            for s in large_growth_steps:
                potential_leaks.append(
                    f"Step {s.step}: large memory growth ({s.delta_rss_mb:.2f} MB)"
                )

        # Check for total growth
        if total_delta > 100:
            potential_leaks.append(f"Total memory growth: {total_delta:.2f} MB")
            recommendations.append("Consider memory cleanup between agent runs")

        # Check LLM delta patterns
        llm_deltas = [s.llm_delta_mb for s in steps if s.llm_delta_mb != 0]
        if llm_deltas and sum(llm_deltas) / len(llm_deltas) > 10:
            potential_leaks.append("High memory usage during LLM calls")
            recommendations.append("Check if LLM responses are being properly released")

        return LoopMemoryReport(
            start_time=self._start_time or datetime.now(),
            end_time=self._end_time or datetime.now(),
            total_duration_seconds=total_duration,
            start_rss_mb=run_start.rss_mb,
            end_rss_mb=run_end.rss_mb,
            total_delta_rss_mb=total_delta,
            steps=steps,
            phase_records=list(self._records),
            peak_rss_mb=peak_rss,
            peak_step=peak_step,
            avg_delta_per_step_mb=avg_delta,
            potential_leaks=potential_leaks,
            recommendations=recommendations,
        )

    def print_report(self, report: Optional[LoopMemoryReport] = None):
        """Print a formatted memory report to console.

        Args:
            report: Optional pre-generated report. If None, generates one.
        """
        if report is None:
            report = self.generate_report()

        lines = []
        lines.append("")
        lines.append("=" * 70)
        lines.append("AGENT LOOP MEMORY REPORT")
        lines.append("=" * 70)

        lines.append(f"\nTotal Duration: {report.total_duration_seconds:.2f}s")
        lines.append(f"Start RSS: {report.start_rss_mb:.2f} MB")
        lines.append(f"End RSS: {report.end_rss_mb:.2f} MB")
        lines.append(f"Total Delta: {report.total_delta_rss_mb:+.2f} MB")
        lines.append(
            f"Peak RSS: {report.peak_rss_mb:.2f} MB (at step {report.peak_step})"
        )
        lines.append(f"Avg Delta/Step: {report.avg_delta_per_step_mb:+.2f} MB")

        if report.steps:
            lines.append("\n" + "-" * 70)
            lines.append("STEP-BY-STEP BREAKDOWN")
            lines.append("-" * 70)

            for step in report.steps:
                lines.append(f"\nStep {step.step}:")
                lines.append(
                    f"  RSS: {step.start_rss_mb:.2f} → {step.end_rss_mb:.2f} MB ({step.delta_rss_mb:+.2f} MB)"
                )
                lines.append(
                    f"  LLM: {step.llm_before_rss_mb:.2f} → {step.llm_after_rss_mb:.2f} MB ({step.llm_delta_mb:+.2f} MB)"
                )
                if step.tool_calls:
                    lines.append(
                        f"  Tools: {', '.join(step.tool_calls)} (Δ {step.tool_delta_mb:+.2f} MB)"
                    )
                lines.append(f"  Duration: {step.duration_seconds:.2f}s")

        if report.potential_leaks:
            lines.append("\n" + "-" * 70)
            lines.append("POTENTIAL LEAKS DETECTED")
            lines.append("-" * 70)
            for leak in report.potential_leaks:
                lines.append(f"  ⚠️  {leak}")

        if report.recommendations:
            lines.append("\n" + "-" * 70)
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 70)
            for rec in report.recommendations:
                lines.append(f"  💡 {rec}")

        lines.append("\n" + "=" * 70)

        print("\n".join(lines))

    def save_report(self, filepath: str, report: Optional[LoopMemoryReport] = None):
        """Save the report to a JSON file.

        Args:
            filepath: Path to save the JSON file
            report: Optional pre-generated report. If None, generates one.
        """
        if report is None:
            report = self.generate_report()

        import json

        def default_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)

        data = {
            "start_time": report.start_time.isoformat(),
            "end_time": report.end_time.isoformat(),
            "total_duration_seconds": report.total_duration_seconds,
            "start_rss_mb": report.start_rss_mb,
            "end_rss_mb": report.end_rss_mb,
            "total_delta_rss_mb": report.total_delta_rss_mb,
            "peak_rss_mb": report.peak_rss_mb,
            "peak_step": report.peak_step,
            "avg_delta_per_step_mb": report.avg_delta_per_step_mb,
            "potential_leaks": report.potential_leaks,
            "recommendations": report.recommendations,
            "steps": [
                {
                    "step": s.step,
                    "start_rss_mb": s.start_rss_mb,
                    "end_rss_mb": s.end_rss_mb,
                    "delta_rss_mb": s.delta_rss_mb,
                    "llm_before_rss_mb": s.llm_before_rss_mb,
                    "llm_after_rss_mb": s.llm_after_rss_mb,
                    "llm_delta_mb": s.llm_delta_mb,
                    "tool_calls": s.tool_calls,
                    "tool_delta_mb": s.tool_delta_mb,
                    "duration_seconds": s.duration_seconds,
                }
                for s in report.steps
            ],
            "phase_records": [
                {
                    "phase": r.phase,
                    "step": r.step,
                    "timestamp": r.timestamp.isoformat(),
                    "rss_mb": r.rss_mb,
                    "vms_mb": r.vms_mb,
                    "python_objects": r.python_objects,
                    "total_alloc_mb": r.total_alloc_mb,
                    "detail": r.detail,
                }
                for r in report.phase_records
            ],
        }

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
