# OpenClaw 接入 Mini-Agent 方案对比

本文档对比了在 OpenClaw 中接入 Mini-Agent 的三种方式，帮助选择适合的集成方案。

## 架构概览

### 方式 1：CLI Skill

```
┌──────────┐     bash      ┌─────────────────┐
│ OpenClaw │ ───────────── │ mini-agent-exec │
│  Agent   │               │     (CLI)       │
└──────────┘               └────────┬────────┘
                                    │ WebSocket
                                    ▼
                           ┌─────────────────┐
                           │ Mini-Agent      │
                           │ Server          │
                           └─────────────────┘

每次调用都是独立的，无会话状态
```

### 方式 2：ACP 直接对话（Thread-bound）

```
┌──────────┐    路由     ┌─────────────┐    ACP     ┌─────────────┐
│   用户   │ ──────────► │  OpenClaw   │ ─────────► │ Mini-Agent  │
│  消息    │             │  Gateway    │            │  (ACP)      │
└──────────┘             └─────────────┘            └─────────────┘
                               │
                               └─ 仅做消息路由和会话管理
                                  不参与推理和决策

用户直接与 Mini-Agent 对话，OpenClaw 作为透明代理
```

### 方式 3：ACP 委托（sessions_spawn）

```
┌──────────┐         ┌─────────────┐   sessions_spawn   ┌─────────────┐
│   用户   │ ───────► │  OpenClaw   │ ─────────────────► │ Mini-Agent  │
│  消息    │         │   Agent     │   {runtime:"acp"}  │   (ACP)     │
└──────────┘         └──────┬──────┘                    └──────┬──────┘
                            │                                  │
                     理解意图 │                          执行任务 │
                     构造任务 │                          返回结果 │
                     处理结果 │                                  │
                            ▼                                  ▼
                     ┌─────────────────────────────────────────────┐
                     │              Agent 编排协作                  │
                     │   OpenClaw Agent 可以继续处理、追问、整合     │
                     └─────────────────────────────────────────────┘

OpenClaw Agent 作为主控，委托子任务给 Mini-Agent
```

## 详细对比

| 特性 | CLI Skill | ACP 直接对话 | ACP 委托 |
|------|-----------|--------------|----------|
| **OpenClaw 参与程度** | 无（仅执行命令） | 仅路由 | 完全参与 |
| **会话状态** | ❌ 每次新建 | ✅ 多轮持久会话 | ✅ 多轮持久会话 |
| **Thinking 流式** | 部分（需手动开启） | ✅ 实时推送 | ✅ 实时推送 |
| **Tool Calls 可见** | ❌ 仅结果 | ✅ 实时更新 | ✅ 实时更新 |
| **取消执行** | ❌ 手动 kill | ✅ 原生支持 | ✅ 原生支持 |
| **Thread 绑定** | ❌ | ✅ Discord/Telegram | ✅ Discord/Telegram |
| **Agent 编排** | ❌ | ❌ | ✅ 可编排多 Agent |
| **结果处理** | 直接返回 | 直接返回 | OpenClaw 可继续处理 |
| **标准协议** | 自定义 CLI | ACP（行业标准） | ACP（行业标准） |
| **配置复杂度** | 低 | 中 | 中 |
| **适用场景** | 简单调用 | 直接使用 Mini-Agent | Agent 协作编排 |

## 使用示例

### 方式 1：CLI Skill

```bash
# 基本用法
mini-agent-exec "创建一个 hello.txt 文件"

# 指定工作目录
mini-agent-exec --workspace /path/to/project "重构代码"

# 流式输出
mini-agent-exec --stream "写一个 Python 脚本"
```

**OpenClaw Skill 定义** (`skills/mini-agent/SKILL.md`):

```markdown
---
name: mini-agent
description: 委托任务给 Mini-Agent 执行
metadata:
  { "openclaw": { "requires": { "bins": ["mini-agent-exec"] } } }
---

# Mini-Agent Skill

委托编码任务给 Mini-Agent 执行。

## 使用方式

\`\`\`bash
mini-agent-exec "Your task here"
mini-agent-exec --workspace /path "Your task"
\`\`\`
```

### 方式 2：ACP 直接对话

**用户操作**:

```
用户: /acp spawn mini-agent --mode persistent --thread auto
系统: 已创建 Mini-Agent 会话，绑定到当前线程

用户: 帮我创建一个 FastAPI 项目
Mini-Agent: [执行任务，创建文件...]

用户: 再添加一个用户认证模块
Mini-Agent: [继续在同一个会话中工作，保持上下文]
```

**OpenClaw 配置** (`openclaw.json`):

```json5
{
  acp: {
    enabled: true,
    backend: "acpx",
    allowedAgents: ["mini-agent", "codex", "claude"],
  },
  agents: {
    list: [
      {
        id: "mini-agent",
        runtime: {
          type: "acp",
          acp: {
            agent: "mini-agent",
            mode: "persistent",
          },
        },
      },
    ],
  },
}
```

### 方式 3：ACP 委托（sessions_spawn）

**场景：OpenClaw Agent 作为主控，委托子任务**

**用户对话**:

```
用户: 帮我分析这个项目，然后用 Mini-Agent 创建测试文件

OpenClaw Agent: 让我分析一下项目结构...
[OpenClaw 读取文件、分析代码结构]

OpenClaw Agent: 我发现项目缺少测试。现在委托 Mini-Agent 创建测试：

[调用 sessions_spawn]
{
  "runtime": "acp",
  "agentId": "mini-agent",
  "task": "为 src/api.py 创建单元测试，覆盖所有端点",
  "mode": "run"
}

[Mini-Agent 执行任务，返回结果]

OpenClaw Agent: Mini-Agent 已创建测试文件。我来运行测试验证...
[OpenClaw 执行 pytest]

OpenClaw Agent: 测试全部通过！
```

**OpenClaw Agent 调用方式**:

```json
// 使用 sessions_spawn 工具
{
  "task": "创建用户认证模块，包含登录、注册、密码重置功能",
  "runtime": "acp",
  "agentId": "mini-agent",
  "mode": "run"
}
```

**返回结果处理**:

```json
{
  "accepted": true,
  "childSessionKey": "agent:mini-agent:acp:abc123",
  "result": {
    "content": "已创建以下文件:\n- auth/login.py\n- auth/register.py\n- auth/password.py",
    "stopReason": "end_turn"
  }
}
```

## 选择指南

### 选择 CLI Skill 当：

- ✅ 只需要简单的单次调用
- ✅ 不需要保持会话上下文
- ✅ 任务独立，不需要 Agent 编排
- ✅ 快速验证，不想配置 ACP

### 选择 ACP 直接对话 当：

- ✅ 想直接使用 Mini-Agent 的能力
- ✅ 需要多轮对话保持上下文
- ✅ 在 Discord/Telegram 线程中持续工作
- ✅ 不需要 OpenClaw Agent 参与决策

### 选择 ACP 委托 当：

- ✅ 需要 OpenClaw Agent 作为主控
- ✅ 需要编排多个 Agent 协作
- ✅ 需要在任务前后进行额外处理
- ✅ 需要 Agent 之间的上下文传递
- ✅ 复杂工作流，需要决策和分支

## 典型场景示例

### 场景 1：简单文件操作 → CLI Skill

```
用户: 用 Mini-Agent 创建一个 config.yaml
OpenClaw: [调用 mini-agent-exec "创建 config.yaml"]
```

### 场景 2：持续编程会话 → ACP 直接对话

```
用户: /acp spawn mini-agent --thread auto
用户: 创建项目结构
Mini-Agent: [创建目录和文件]
用户: 添加数据库模型
Mini-Agent: [在上下文中继续工作]
用户: 写测试
Mini-Agent: [继续工作]
```

### 场景 3：复杂项目开发 → ACP 委托

```
用户: 帮我构建一个完整的后端 API

OpenClaw Agent:
1. [分析需求，规划架构]
2. [委托 Mini-Agent 创建项目结构]
3. [验证结构，委托 Mini-Agent 实现核心模块]
4. [运行测试，发现问题]
5. [委托 Mini-Agent 修复 bug]
6. [最终验证，生成文档]

OpenClaw Agent 作为项目经理，Mini-Agent 作为执行者
```

## 技术要求

### CLI Skill

| 要求 | 说明 |
|------|------|
| Mini-Agent 服务器 | 需要运行 `mini-agent-server` |
| CLI 工具 | 需要安装 `mini-agent-exec` |
| 配置 | 无需额外配置 |

### ACP 集成

| 要求 | 说明 |
|------|------|
| acpx 插件 | OpenClaw 需要安装 acpx backend |
| Mini-Agent ACP | 使用 `mini-agent-acp` 命令 |
| 配置 | 需要配置 `openclaw.json` 和 acpx adapter |

## 实现状态

| 方式 | Mini-Agent 实现 | OpenClaw 支持 |
|------|----------------|---------------|
| CLI Skill | ✅ `mini-agent-exec` | ✅ Skill 机制 |
| ACP 直接对话 | ✅ `mini-agent-acp` | ✅ ACP runtime |
| ACP 委托 | ✅ `mini-agent-acp` | ✅ sessions_spawn |

## 总结

| 需求 | 推荐方式 | 原因 |
|------|----------|------|
| 快速调用，无状态 | CLI Skill | 简单直接 |
| 直接使用 Mini-Agent | ACP 直接对话 | 多轮会话支持 |
| Agent 协作编排 | ACP 委托 | 灵活的任务分发 |

---

**相关文档**:
- [Mini-Agent WebSocket Server 使用指南](../Mini-Agent/examples/websocket_usage.md)
- [OpenClaw ACP Agents 文档](../openclaw/docs/tools/acp-agents.md)
- [Agent Client Protocol 官网](https://agentclientprotocol.com/)