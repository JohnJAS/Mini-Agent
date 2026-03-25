# Mini-Agent WebSocket Server 使用指南

## 快速开始

### 1. 启动服务器

打开一个终端窗口：

```bash
cd D:/workspace/Mini-Agent
uv run mini-agent-server
```

看到以下输出表示服务器已启动：

```
Server listening on ws://localhost:8765
```

### 2. 运行客户端示例

打开另一个终端窗口：

```bash
cd D:/workspace/Mini-Agent
uv run python examples/websocket_client_examples.py
```

---

## 客户端使用方法

### 方式 1：快捷函数（最简单）

```python
import asyncio
from mini_agent.server import chat

async def main():
    response = await chat("你好，请介绍一下你自己")
    print(response)

asyncio.run(main())
```

### 方式 2：MiniAgentClient 类（推荐）

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 发送消息，等待完整响应
        response = await client.send_message("你好", stream=False)
        print(response.content)

asyncio.run(main())
```

### 方式 3：流式响应

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 流式接收消息
        async for event in client.send_message_stream("讲一个故事"):
            if event["type"] == "message_chunk":
                print(event["content"], end="", flush=True)
            elif event["type"] == "completed":
                print("\n[完成]")

asyncio.run(main())
```

---

## 完整示例

### 多轮对话

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 第一轮
        r1 = await client.send_message("我的名字是小明")
        print(f"Agent: {r1.content}")

        # 第二轮（Agent 会记住上下文）
        r2 = await client.send_message("你还记得我的名字吗？")
        print(f"Agent: {r2.content}")

asyncio.run(main())
```

### 带回调的流式响应

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    def on_thinking(content):
        print(f"[思考] {content}")

    def on_tool_call(tool_info):
        print(f"[工具] {tool_info.tool_name}")

    async with MiniAgentClient("ws://localhost:8765") as client:
        response = await client.send_message(
            "列出当前目录的文件",
            stream=True,
            on_thinking=on_thinking,
            on_tool_call=on_tool_call,
        )
        print(f"回复: {response.content}")

asyncio.run(main())
```

### 指定工作目录

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient(
        "ws://localhost:8765",
        workspace="/path/to/workspace"  # 指定工作目录
    ) as client:
        response = await client.send_message("创建一个 test.txt 文件")
        print(response.content)

asyncio.run(main())
```

---

## API 参考

### MiniAgentClient

```python
client = MiniAgentClient(
    url="ws://localhost:8765",  # WebSocket 服务器地址
    workspace="/path/to/ws",     # 可选，工作目录
)
```

#### 方法

| 方法 | 说明 |
|------|------|
| `connect()` | 连接服务器 |
| `close()` | 关闭连接 |
| `create_session(workspace=None)` | 创建会话 |
| `send_message(content, stream=False, ...)` | 发送消息 |
| `send_message_stream(content)` | 流式发送消息 |
| `cancel()` | 取消当前执行 |
| `close_session()` | 关闭当前会话 |

### AgentResponse

```python
@dataclass
class AgentResponse:
    content: str                    # 回复内容
    thinking: str | None            # 思考过程
    tool_calls: list[ToolCallInfo]  # 工具调用列表
    tool_results: list[ToolResultInfo]  # 工具结果列表
    stop_reason: str                # 结束原因
```

### 事件类型（流式模式）

| type | 说明 |
|------|------|
| `thinking` | Agent 思考内容 |
| `message_chunk` | 消息片段 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具执行结果 |
| `completed` | 执行完成 |
| `error` | 错误 |

---

## 常见问题

### Q: 运行报错 "Connection refused"

确保服务器已启动：

```bash
uv run mini-agent-server
```

### Q: 运行报错 "Configuration file not found"

确保配置文件存在：

- `mini_agent/config/config.yaml`（开发模式）
- `~/.mini-agent/config/config.yaml`（用户配置）

### Q: 如何在任意目录运行客户端？

全局安装：

```bash
cd D:/workspace/Mini-Agent
uv tool install .

# 然后可以在任意目录运行
mini-agent-server
```

---

## 文件结构

```
mini_agent/server/
├── __init__.py          # 模块入口
├── client.py            # 客户端实现
├── message_types.py     # 消息类型定义
├── session_manager.py   # 会话管理
├── streaming_agent.py   # 流式 Agent 包装
├── websocket_server.py  # WebSocket 服务器
└── README.md            # 详细文档

examples/
└── websocket_client_examples.py  # 示例脚本
```