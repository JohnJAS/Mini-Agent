# Mini-Agent WebSocket Server 使用说明

## 安装与运行

### 方式 1：使用 uv run（推荐）

在项目目录下使用 `uv run` 命令：

```bash
# 进入项目目录
cd /path/to/Mini-Agent

# 安装依赖并运行
uv run mini-agent-server

# 指定端口
uv run mini-agent-server --port 9000

# 详细日志模式
uv run mini-agent-server --verbose
```

### 方式 2：以模块方式运行

```bash
cd /path/to/Mini-Agent
uv run python -m mini_agent.server
```

### 方式 3：全局安装（可选）

使用 `uv tool install` 安装后可在任意目录运行：

```bash
# 安装为全局工具
cd /path/to/Mini-Agent
uv tool install .

# 现在可以在任意目录运行
mini-agent-server
mini-agent-server --port 9000
```

### ⚠️ 注意事项

**不要直接运行 Python 文件：**

```bash
# ❌ 错误方式 - 会导致导入错误
python mini_agent/server/websocket_server.py

# ❌ 错误方式
uv run mini_agent/server/websocket_server.py
```

这会报错：
```
ImportError: attempted relative import with no known parent package
```

原因是 `websocket_server.py` 使用了相对导入（如 `from .message_types import ...`），必须作为包的一部分运行。

## 快速开始

### 启动服务器

```bash
# 默认端口 8765
mini-agent-server

# 指定端口
mini-agent-server --port 9000

# 绑定所有网卡（允许远程访问）
mini-agent-server --host 0.0.0.0 --port 8765

# 详细日志模式
mini-agent-server --verbose
```

## API 消息格式

所有消息均为 JSON 格式。

### 客户端 → 服务器

#### 1. 创建会话

```json
{
  "type": "create_session",
  "workspace": "/path/to/workspace"  // 可选，默认使用配置中的 workspace_dir
}
```

**响应:**
```json
{
  "type": "session_created",
  "session_id": "sess-abc123",
  "workspace": "/path/to/workspace"
}
```

#### 2. 发送消息

```json
{
  "type": "prompt",
  "session_id": "sess-abc123",
  "content": "你的问题或任务",
  "stream": true  // true=流式响应，false=完整响应
}
```

#### 3. 取消执行

```json
{
  "type": "cancel",
  "session_id": "sess-abc123"
}
```

#### 4. 关闭会话

```json
{
  "type": "close_session",
  "session_id": "sess-abc123"
}
```

### 服务器 → 客户端

#### 事件类型

| 类型 | 说明 | 字段 |
|------|------|------|
| `session_created` | 会话创建成功 | `session_id`, `workspace` |
| `thinking` | Agent 思考内容 | `session_id`, `content` |
| `message_chunk` | 消息片段（流式模式） | `session_id`, `content` |
| `message` | 完整消息 | `session_id`, `content` |
| `tool_call` | 工具调用开始 | `session_id`, `tool_name`, `tool_call_id`, `arguments` |
| `tool_result` | 工具执行结果 | `session_id`, `tool_call_id`, `tool_name`, `success`, `content`, `error` |
| `completed` | 执行完成 | `session_id`, `stop_reason` |
| `error` | 错误 | `session_id`, `message`, `code` |

#### stop_reason 值

| 值 | 说明 |
|---|---|
| `end_turn` | 正常结束 |
| `cancelled` | 用户取消 |
| `max_turn_requests` | 达到最大步数 |
| `refusal` | 拒绝执行 |

## Python 客户端库

Mini-Agent 提供了一个易用的 Python 客户端库，无需手动处理 WebSocket 消息。

### 导入

```python
from mini_agent.server import (
    MiniAgentClient,
    AgentResponse,
    ToolCallInfo,
    ToolResultInfo,
    chat,          # 快捷函数：一次性对话
    chat_stream,   # 快捷函数：流式对话
)
```

### 快速开始：一次性对话

```python
import asyncio
from mini_agent.server import chat

async def main():
    response = await chat("你好，请介绍一下你自己")
    print(response)

asyncio.run(main())
```

### 使用 MiniAgentClient 类

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    # 使用上下文管理器自动管理连接
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 发送消息，等待完整响应
        response = await client.send_message("你好", stream=False)
        print(f"回复: {response.content}")
        print(f"思考: {response.thinking}")
        print(f"停止原因: {response.stop_reason}")

asyncio.run(main())
```

### 流式响应

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 使用回调处理流式事件
        def on_thinking(content):
            print(f"[思考] {content}")

        def on_tool_call(tool_info):
            print(f"[工具] {tool_info.tool_name}")

        response = await client.send_message(
            "请写一首诗",
            stream=True,
            on_thinking=on_thinking,
            on_tool_call=on_tool_call,
        )
        print(f"完整回复: {response.content}")

asyncio.run(main())
```

### 使用迭代器处理流式事件

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 使用迭代器处理流式事件
        async for event in client.send_message_stream("讲一个故事"):
            event_type = event.get("type")

            if event_type == "thinking":
                print(f"[思考] {event['content']}")

            elif event_type == "message_chunk":
                print(event["content"], end="", flush=True)

            elif event_type == "tool_call":
                print(f"\n[工具调用] {event['tool_name']}")

            elif event_type == "tool_result":
                status = "✓" if event["success"] else "✗"
                print(f"\n[工具结果] {status}")

            elif event_type == "completed":
                print(f"\n[完成] {event['stop_reason']}")

asyncio.run(main())
```

### 多轮对话

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 创建会话（自动创建，也可以显式调用）
        await client.create_session()

        # 第一轮
        response1 = await client.send_message("我的名字是小明")
        print(f"Agent: {response1.content}")

        # 第二轮（同一个会话，Agent 会记住上下文）
        response2 = await client.send_message("你还记得我的名字吗？")
        print(f"Agent: {response2.content}")

        # 关闭会话
        await client.close_session()

asyncio.run(main())
```

### 获取工具调用详情

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        response = await client.send_message("帮我创建一个 test.txt 文件", stream=False)

        # 查看工具调用记录
        for tool_call in response.tool_calls:
            print(f"调用工具: {tool_call.tool_name}")
            print(f"参数: {tool_call.arguments}")

        # 查看工具执行结果
        for result in response.tool_results:
            print(f"结果: {result.success}")
            print(f"内容: {result.content}")
            if result.error:
                print(f"错误: {result.error}")

asyncio.run(main())
```

### 指定工作目录

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    # 方式 1：在构造函数中指定
    async with MiniAgentClient(
        url="ws://localhost:8765",
        workspace="/path/to/workspace"
    ) as client:
        response = await client.send_message("列出当前目录的文件")
        print(response.content)

    # 方式 2：在创建会话时指定
    async with MiniAgentClient("ws://localhost:8765") as client:
        await client.create_session(workspace="/tmp/my_project")
        response = await client.send_message("创建一个 hello.py 文件")

asyncio.run(main())
```

### 取消执行

```python
import asyncio
from mini_agent.server import MiniAgentClient

async def main():
    async with MiniAgentClient("ws://localhost:8765") as client:
        # 在另一个任务中发送消息
        async def long_task():
            return await client.send_message("执行一个耗时任务...")

        task = asyncio.create_task(long_task())

        # 3秒后取消
        await asyncio.sleep(3)
        await client.cancel()

        try:
            result = await task
            print(f"结果: {result.stop_reason}")  # 应该是 "cancelled"
        except Exception as e:
            print(f"被取消: {e}")

asyncio.run(main())
```

### AgentResponse 类

```python
@dataclass
class AgentResponse:
    content: str                           # Agent 回复内容
    thinking: str | None                   # 思考过程
    tool_calls: list[ToolCallInfo]         # 工具调用列表
    tool_results: list[ToolResultInfo]     # 工具执行结果列表
    stop_reason: str                       # 结束原因
```

### ToolCallInfo 类

```python
@dataclass
class ToolCallInfo:
    tool_name: str           # 工具名称
    tool_call_id: str        # 调用 ID
    arguments: dict[str, Any]  # 调用参数
```

### ToolResultInfo 类

```python
@dataclass
class ToolResultInfo:
    tool_call_id: str        # 对应的工具调用 ID
    tool_name: str           # 工具名称
    success: bool            # 是否成功
    content: str             # 返回内容
    error: str | None        # 错误信息（如果失败）
```

## 客户端示例（底层 WebSocket）

以下示例直接使用 WebSocket 协议，适合需要更精细控制或使用其他语言的场景。

### Python 客户端（流式模式）

```python
import asyncio
import websockets
import json

async def chat_streaming():
    async with websockets.connect("ws://localhost:8765") as ws:
        # 1. 创建会话
        await ws.send(json.dumps({"type": "create_session"}))
        response = json.loads(await ws.recv())
        session_id = response["session_id"]
        print(f"会话已创建: {session_id}")

        # 2. 发送消息（流式模式）
        await ws.send(json.dumps({
            "type": "prompt",
            "session_id": session_id,
            "content": "请写一首关于春天的诗",
            "stream": True
        }))

        # 3. 接收流式事件
        while True:
            msg = json.loads(await ws.recv())
            msg_type = msg["type"]

            if msg_type == "thinking":
                print(f"\n[思考] {msg['content']}")

            elif msg_type == "message_chunk":
                print(msg["content"], end="", flush=True)

            elif msg_type == "tool_call":
                print(f"\n[工具调用] {msg['tool_name']}({msg['arguments']})")

            elif msg_type == "tool_result":
                status = "✓" if msg["success"] else "✗"
                print(f"\n[工具结果] {status} {msg['content'][:100]}")

            elif msg_type == "completed":
                print(f"\n\n[完成] 原因: {msg['stop_reason']}")
                break

            elif msg_type == "error":
                print(f"\n[错误] {msg['message']}")
                break

asyncio.run(chat_streaming())
```

### Python 客户端（完整响应模式）

```python
import asyncio
import websockets
import json

async def chat_complete():
    async with websockets.connect("ws://localhost:8765") as ws:
        # 1. 创建会话
        await ws.send(json.dumps({"type": "create_session"}))
        response = json.loads(await ws.recv())
        session_id = response["session_id"]

        # 2. 发送消息（完整响应模式）
        await ws.send(json.dumps({
            "type": "prompt",
            "session_id": session_id,
            "content": "你好，请介绍一下你自己",
            "stream": False  # 完整响应
        }))

        # 3. 等待完整响应
        full_message = ""
        while True:
            msg = json.loads(await ws.recv())
            msg_type = msg["type"]

            if msg_type == "thinking":
                print(f"[思考] {msg['content']}")

            elif msg_type == "message":
                full_message = msg["content"]
                print(f"[回复] {full_message}")

            elif msg_type == "completed":
                print(f"[完成] 原因: {msg['stop_reason']}")
                break

            elif msg_type == "error":
                print(f"[错误] {msg['message']}")
                break

asyncio.run(chat_complete())
```

### JavaScript/Node.js 客户端

```javascript
const WebSocket = require('ws');

async function chat() {
    const ws = new WebSocket('ws://localhost:8765');

    ws.on('open', async () => {
        // 创建会话
        ws.send(JSON.stringify({ type: 'create_session' }));
    });

    ws.on('message', (data) => {
        const msg = JSON.parse(data);
        console.log('收到:', msg);

        if (msg.type === 'session_created') {
            // 发送消息
            ws.send(JSON.stringify({
                type: 'prompt',
                session_id: msg.session_id,
                content: '你好',
                stream: true
            }));
        }
    });
}

chat();
```

## 多轮对话示例

```python
import asyncio
import websockets
import json

async def multi_turn_chat():
    async with websockets.connect("ws://localhost:8765") as ws:
        # 创建会话
        await ws.send(json.dumps({"type": "create_session"}))
        response = json.loads(await ws.recv())
        session_id = response["session_id"]

        # 辅助函数：发送消息并等待完成
        async def send_and_wait(content):
            await ws.send(json.dumps({
                "type": "prompt",
                "session_id": session_id,
                "content": content,
                "stream": False
            }))

            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] == "message":
                    return msg["content"]
                elif msg["type"] == "completed":
                    return None
                elif msg["type"] == "error":
                    raise Exception(msg["message"])

        # 多轮对话
        response1 = await send_and_wait("我的名字是小明")
        print(f"Agent: {response1}")

        response2 = await send_and_wait("你还记得我的名字吗？")
        print(f"Agent: {response2}")

        # 关闭会话
        await ws.send(json.dumps({
            "type": "close_session",
            "session_id": session_id
        }))

asyncio.run(multi_turn_chat())
```

## 工具调用流程

```
Client                          Server
   |                               |
   |-- prompt ------------------>  |
   |                               |
   |  <-- thinking --------------  |
   |  <-- tool_call --------------  | (工具调用开始)
   |  <-- tool_result ------------ | (工具执行结果)
   |  <-- tool_call --------------  | (可能有多个工具调用)
   |  <-- tool_result ------------ |
   |  <-- message_chunk ----------  | (最终回复)
   |  <-- completed --------------  |
   |                               |
```

## 错误处理

```python
# 错误事件示例
{
    "type": "error",
    "session_id": "sess-abc123",
    "message": "Session not found",
    "code": "session_not_found"
}

# 常见错误码
# - unknown_type: 未知消息类型
# - invalid_json: JSON 解析失败
# - session_not_found: 会话不存在
# - agent_error: Agent 执行错误
# - internal_error: 内部错误
```

## 配置要求

服务器使用 Mini-Agent 的标准配置文件 (`config.yaml`)，需要确保：

1. 配置文件存在于以下位置之一：
   - `./mini_agent/config/config.yaml` (开发模式)
   - `~/.mini-agent/config/config.yaml` (用户配置)
   - 包安装目录下的 `config/config.yaml`

2. 配置文件包含有效的 API Key

## 与 ACP 服务器的区别

| 特性 | WebSocket Server | ACP Server |
|------|-----------------|------------|
| 协议 | WebSocket | stdio (Agent Client Protocol) |
| 用途 | 远程 API 调用 | IDE 集成 |
| 连接方式 | TCP/WebSocket | 标准输入输出 |
| 会话管理 | 支持多会话 | 支持多会话 |
| 流式输出 | ✓ | ✓ |

## 命令对比

```bash
# CLI 交互模式
mini-agent

# ACP 服务器（用于 IDE 集成）
mini-agent-acp

# WebSocket 服务器（用于 API 调用）
mini-agent-server
```