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

## 客户端示例

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