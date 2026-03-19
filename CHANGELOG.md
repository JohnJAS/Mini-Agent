# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

#### Agent Loop Memory Tracking (`mini_agent/utils/memory_profiler.py`)

- **`AgentLoopMemoryTracker`**: Fine-grained memory tracking for agent loop execution
  - Tracks memory at each phase: step start/end, LLM calls, tool calls, summarization
  - Generates detailed reports with step-by-step memory breakdown
  - Outputs both console reports and JSON files
  - Detects potential memory leaks and provides recommendations

- **New dataclasses for memory tracking**:
  - `LoopPhase`: Constants for tracking phases (RUN_START, RUN_END, STEP_START, etc.)
  - `PhaseMemoryRecord`: Memory record for a single phase
  - `StepMemorySummary`: Memory summary for a single agent step
  - `LoopMemoryReport`: Complete memory report for an agent loop

- **Agent integration** (`mini_agent/agent.py`):
  - Added `memory_tracker` parameter to `Agent.__init__`
  - Automatic memory tracking throughout `Agent.run()` execution
  - Automatic report generation and saving to `workspace/memory_report.json`

### Changed

- **`mini_agent/utils/__init__.py`**: Exported new memory tracking classes

### Examples

- **`examples/memory_profiling_demo.py`**: Added demonstration of agent loop memory tracking
  - `agent_loop_memory_tracking()`: Shows automatic tracking with Agent
  - `manual_memory_tracking()`: Shows manual tracking for custom workflows

### Tests

- **`tests/test_memory_profiler.py`**: Added comprehensive tests for `AgentLoopMemoryTracker`
  - Tests for all tracking phases
  - Tests for report generation, printing, and saving
  - Tests for multi-step tracking and leak detection

## Usage

### Automatic Tracking (Recommended)

```python
from mini_agent.utils.memory_profiler import AgentLoopMemoryTracker

tracker = AgentLoopMemoryTracker(enable_tracemalloc=True)
agent = Agent(
    llm_client=llm_client,
    system_prompt="...",
    tools=[...],
    memory_tracker=tracker,
)

await agent.run()  # Automatically tracks memory and outputs reports
```

### Manual Tracking

```python
from mini_agent.utils.memory_profiler import AgentLoopMemoryTracker

tracker = AgentLoopMemoryTracker(enable_tracemalloc=True)

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

# Generate and print report
report = tracker.generate_report()
tracker.print_report(report)

# Save to JSON
tracker.save_report("memory_report.json", report)
```

### Output

**Console Report:**
```
======================================================================
AGENT LOOP MEMORY REPORT
======================================================================

Total Duration: 12.34s
Start RSS: 150.00 MB
End RSS: 180.00 MB
Total Delta: +30.00 MB
Peak RSS: 185.00 MB (at step 3)
Avg Delta/Step: +7.50 MB

----------------------------------------------------------------------
STEP-BY-STEP BREAKDOWN
----------------------------------------------------------------------

Step 0:
  RSS: 150.00 → 155.00 MB (+5.00 MB)
  LLM: 150.00 → 153.00 MB (+3.00 MB)
  Tools: bash (+2.00 MB)
  Duration: 3.00s

...

----------------------------------------------------------------------
POTENTIAL LEAKS DETECTED
----------------------------------------------------------------------
  ⚠️  Consistent memory growth: avg 7.50 MB per step
  ⚠️  Total memory growth: 30.00 MB

----------------------------------------------------------------------
RECOMMENDATIONS
----------------------------------------------------------------------
  💡 Check for unbounded message history growth
  💡 Consider memory cleanup between agent runs
```

**JSON Report:**
- Saved to `workspace/memory_report.json`
- Contains detailed phase records, step summaries, and analysis