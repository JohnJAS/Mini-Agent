# Mini-Agent 内存泄漏分析与修复报告

## 一、发现的内存泄漏风险点

| 文件 | 位置 | 问题 | 风险级别 |
|------|------|------|----------|
| `agent.py` | `self.messages` | 消息历史无限增长，长时间运行会累积大量数据 | 🔴 高 |
| `agent.py` | `tiktoken.get_encoding()` | 每次调用 `_estimate_tokens()` 都重新创建 encoder | 🟡 中 |
| `bash_tool.py` | `BackgroundShellManager._shells` | 类变量字典永不释放，shell 进程引用残留 | 🔴 高 |
| `bash_tool.py` | `output_lines` | 每个后台 shell 的输出行列表无限累积 | 🔴 高 |
| `mcp_loader.py` | `_mcp_connections` | 全局列表可能残留未清理的连接引用 | 🟡 中 |

---

## 二、修复内容

### 2.1 `mini_agent/agent.py`

**修复项：**

1. **缓存 tiktoken encoder**
   - 将 encoder 缓存为模块级变量 `_tiktoken_encoder`
   - 通过 `_get_tiktoken_encoder()` 函数获取，避免重复初始化

2. **新增方法**

```python
def get_memory_stats(self) -> dict:
    """获取 Agent 内存使用统计"""

def clear_history(self, keep_system: bool = True):
    """清理消息历史释放内存"""
```

### 2.2 `mini_agent/tools/bash_tool.py`

**修复项：**

1. **添加常量限制**

```python
MAX_OUTPUT_LINES = 10000      # 每个 shell 最大输出行数
MAX_COMPLETED_SHELLS = 50     # 保留的已完成 shell 数量
```

2. **输出行自动截断**
   - `BackgroundShell.add_output()` 方法自动截断超出的旧输出行

3. **新增方法**

```python
@classmethod
def get_memory_stats(cls) -> dict:
    """获取后台 shell 内存统计"""

@classmethod
def cleanup_all(cls) -> int:
    """强制清理所有 shell 和监控任务"""
```

### 2.3 `mini_agent/tools/mcp_loader.py`

**新增方法：**

```python
def get_mcp_connections_stats() -> dict:
    """获取 MCP 连接统计信息"""

async def safe_cleanup_mcp_connections():
    """安全清理 MCP 连接（用于关闭时）"""
```

---

## 三、新增内存分析工具

### 3.1 文件结构

| 文件 | 说明 |
|------|------|
| `mini_agent/utils/memory_profiler.py` | 内存分析工具核心模块 |
| `examples/memory_profiling_demo.py` | 使用示例代码 |
| `tests/test_memory_profiler.py` | 单元测试 |

### 3.2 MemoryProfiler 类

**功能：**

- 内存快照采集
- 基线对比分析
- 后台自动监控
- 对象类型统计
- 潜在泄漏检测
- GC 强制回收

**使用示例：**

```python
from mini_agent.utils.memory_profiler import MemoryProfiler

# 创建分析器
profiler = MemoryProfiler(
    enable_tracemalloc=True,    # 启用详细内存追踪
    snapshot_interval=30.0,     # 自动快照间隔（秒）
)

# 设置基线
profiler.set_baseline()

# ... 你的代码运行 ...

# 采集快照
snapshot = profiler.take_snapshot()
print(f"RSS: {snapshot.rss_mb:.2f} MB")
print(f"对象数: {snapshot.python_objects}")

# 对比基线
comparison = profiler.compare_to_baseline()
print(f"内存增长: {comparison['rss_delta_mb']:.2f} MB")
print(f"潜在泄漏: {comparison['potential_leak']}")

# 生成报告
print(profiler.get_report())

# 启动后台监控
profiler.start_monitoring()

# 停止监控
profiler.stop_monitoring()
```

### 3.3 ResourceTracker 类

**功能：**

- 注册/注销资源
- 检测长期存活的资源（潜在泄漏）
- 按类型查询活跃资源

**使用示例：**

```python
from mini_agent.utils.memory_profiler import get_resource_tracker

tracker = get_resource_tracker()

# 注册资源
tracker.register("mcp_connection", "conn_1", {"url": "http://..."})

# 注销资源
tracker.unregister("mcp_connection", "conn_1")

# 检测长期存活的资源
leaks = tracker.get_leaks_report(max_age_seconds=3600)
for leak in leaks:
    print(f"潜在泄漏: {leak['type']} - {leak['id']} (存活 {leak['age_seconds']}s)")
```

### 3.4 Agent 内存分析

```python
from mini_agent.utils.memory_profiler import profile_agent_memory

profile = profile_agent_memory(agent)

print(f"消息数量: {profile['message_count']}")
print(f"总大小: {profile['total_message_size'] / 1024:.2f} KB")
print(f"平均消息: {profile['avg_message_bytes']:.0f} bytes")

# 检查潜在问题
for issue in profile['potential_issues']:
    print(f"问题: {issue}")
```

---

## 四、CLI 新增命令

### `/memory` 命令

显示完整的内存使用分析，包括：

```
Memory Usage Analysis:
──────────────────────────────────────────────────

Agent Memory:
  Messages: 45
  Content Size: 2.35 MB
  Avg Message: 53.2 KB
  Max Message: 156.8 KB
  Tools Loaded: 12

Background Shells:
  Total Shells: 3
  Running: 1
  Completed: 2
  Total Output Lines: 15234

MCP Connections:
  Total Connections: 2
    - filesystem: 15 tools (active)
    - web-search: 8 tools (active)

Process Memory:
  RSS: 156.2 MB
  VMS: 420.5 MB

Python GC:
  Tracked Objects: 45,678

⚠️ Potential Issues:
  - Message history large (2.35 MB)
  Consider using /clear to reset history
```

---

## 五、最佳实践建议

### 5.1 长期运行的服务

```python
# 定期采集快照监控内存
profiler = MemoryProfiler(enable_tracemalloc=True)
profiler.set_baseline()

# 每隔一段时间检查
async def periodic_check():
    while True:
        await asyncio.sleep(60)
        comparison = profiler.compare_to_baseline()
        if comparison['potential_leak']:
            logger.warning(f"内存可能泄漏: {comparison['rss_delta_mb']:.2f} MB 增长")
```

### 5.2 大量交互后

```bash
# CLI 中清理消息历史
/clear
```

### 5.3 后台任务完成后

```bash
# 确保终止后台进程
# Agent 会自动调用 bash_kill
```

### 5.4 程序退出时

```python
# 确保 MCP 连接清理
from mini_agent.tools.mcp_loader import safe_cleanup_mcp_connections

await safe_cleanup_mcp_connections()

# 清理所有后台 shell
from mini_agent.tools.bash_tool import BackgroundShellManager
BackgroundShellManager.cleanup_all()
```

---

## 六、依赖说明

内存分析工具可选依赖：

- `psutil` - 获取精确的进程内存（RSS/VMS）
- `tracemalloc` - Python 内置，详细内存分配追踪

安装：

```bash
pip install psutil
```

---

## 七、测试

运行内存分析工具测试：

```bash
python -m pytest tests/test_memory_profiler.py -v
```

---

## 八、修改文件清单

| 文件 | 修改类型 |
|------|----------|
| `mini_agent/agent.py` | 修改 |
| `mini_agent/tools/bash_tool.py` | 修改 |
| `mini_agent/tools/mcp_loader.py` | 修改 |
| `mini_agent/cli.py` | 修改 |
| `mini_agent/utils/memory_profiler.py` | 新增 |
| `examples/memory_profiling_demo.py` | 新增 |
| `tests/test_memory_profiler.py` | 新增 |