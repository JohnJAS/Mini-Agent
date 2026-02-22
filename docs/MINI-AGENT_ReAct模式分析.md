# MINI-AGENT 执行模式分析：ReAct

## 结论

**是的，MINI-AGENT 项目使用的是 ReAct 模式。**

---

## 什么是 ReAct 模式？

### 定义

**ReAct** = **Re**asoning + **Act**ing（推理 + 行动）

是一种让 LLM 能够**动态使用工具**的经典执行范式，核心思想是将推理（Reasoning）和行动（Acting）交替进行，并通过观察（Observation）来指导后续推理。

### 核心循环

```
┌─────────────────────────────────────────────────────────┐
│  1. Thought (思考)    : 分析问题，决定下一步做什么     │
│  2. Action (行动)     : 调用工具或API                  │
│  3. Observation (观察): 获取工具返回结果                │
│  4. 重复循环直到完成任务                                │
└─────────────────────────────────────────────────────────┘
```

### 伪代码

```
while 任务未完成:
    thought = 推理(历史记录)           # 分析当前情况
    action = 选择工具(thought)         # 决定调用什么工具
    result = 执行工具(action)          # 执行行动
    observation = 观察(result)        # 获取结果
    添加到历史记录(thought, action, observation)
```

---

## MINI-AGENT 中的 ReAct 实现

### 代码位置

核心代码位于 `mini_agent/agent.py` 的 `run()` 方法中。

### 1. Thought（推理）

```python
# agent.py 第 372 行
response = await self.llm.generate(messages=self.messages, tools=tool_list)

# 第 406-409 行：打印推理过程
if response.thinking:
    print(f"🧠 Thinking: {response.thinking}")
```

模型会在响应中包含 `thinking` 字段，记录其推理过程。

### 2. Action（行动 - 工具调用）

```python
# agent.py 第 430-451 行
for tool_call in response.tool_calls:
    function_name = tool_call.function.name
    arguments = tool_call.function.arguments
    
    print(f"🔧 Tool Call: {function_name}")
    
    # 执行工具
    if function_name not in self.tools:
        result = ToolResult(success=False, error=f"Unknown tool: {function_name}")
    else:
        result = await tool.execute(**arguments)
```

### 3. Observation（观察 - 工具结果）

```python
# agent.py 第 494-501 行
tool_msg = Message(
    role="tool",
    content=result.content if result.success else f"Error: {result.error}",
    tool_call_id=tool_call_id,
    name=function_name,
)
# 将结果添加回消息历史，下一轮继续推理
self.messages.append(tool_msg)
```

关键点：**工具执行结果会被添加回消息历史**，供下一轮推理使用。

### 4. 循环执行

```python
# agent.py 第 343 行
while step < self.max_steps:
    # ... 执行 ReAct 循环
    
    # 检查任务是否完成
    if not response.tool_calls:
        return response.content  # 无工具调用 = 任务完成
```

---

## 执行流程图示

```
用户输入: "帮我创建一个文件 test.txt，内容是 Hello"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1:
  ↓
  [Thought] "我需要先检查文件是否存在"
  ↓
  [Action] 调用 read_file 工具，参数: path="test.txt"
  ↓
  [Observation] "文件不存在"
  ↓
  添加到消息历史: user → assistant(tool_call) → tool(result)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 2:
  ↓
  [Thought] "文件不存在，我需要创建它"
  ↓
  [Action] 调用 write_file 工具，参数: path="test.txt", content="Hello"
  ↓
  [Observation] "文件创建成功"
  ↓
  添加到消息历史

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 3:
  ↓
  [Thought] "任务已完成，不需要更多工具调用"
  ↓
  [Action] 无工具调用 (task complete)
  ↓
  返回最终回复给用户

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ReAct vs 其他模式对比

| 模式 | 特点 | 适用场景 | MINI-AGENT |
|------|------|----------|------------|
| **ReAct** | 推理 + 工具调用交替进行 | 需要外部交互的任务 | ✅ 是 |
| **Chain-of-Thought (CoT)** | 只推理，不调用工具 | 数学、逻辑推理 | ❌ |
| **Tool Use (Function Calling)** | 直接调用工具，一次性返回 | 简单工具调用 | ❌ 太简单 |
| **Agent** | 自主规划 + 循环执行 | 复杂多步骤任务 | ✅ 是 |

### 各模式简单说明

#### Chain-of-Thought (CoT)
```
问题: 5 * 6 + 3 = ?
思考: 5 * 6 = 30, 30 + 3 = 33
答案: 33
```
只输出推理过程，不调用外部工具。

#### Tool Use / Function Calling
```
用户: 今天天气如何?
→ 直接调用天气API
→ 返回结果
```
一次性调用，不循环。

#### ReAct
```
用户: 帮我查下北京天气，如果下雨就带伞
→ 调用天气API
→ 观察结果: 今天有雨
→ 推理: 需要带伞
→ 输出建议
```
推理 + 行动 + 观察的循环。

---

## MINI-AGENT 的 ReAct 增强特性

在经典 ReAct 基础上，MINI-AGENT 增加了一些增强功能：

### 1. 完整的思考过程保留

```python
# openai_client.py
if msg.thinking:
    assistant_msg["reasoning_details"] = [{"text": msg.thinking}]
```

模型推理过程中的 `thinking` 会被完整保留，确保思维链不断裂。

### 2. 智能上下文管理

- **Token 限制**: 默认 80K，超过后自动摘要
- **消息摘要策略**: 保留 user 消息，压缩 assistant + tool 消息
- **支持长任务**: 可以处理无限长的任务

### 3. 丰富的工具生态

| 工具类型 | 示例 |
|----------|------|
| 基础工具 | 文件读写、Bash 命令、会话笔记 |
| 文档技能 | Word、PDF、Excel、PPT |
| 创意工具 | 算法艺术、画布设计 |
| 开发工具 | MCP 构建器、Web 测试 |

### 4. MCP 扩展支持

支持 Model Context Protocol，可以接入外部服务（知识图谱、网络搜索等）。

### 5. 安全取消机制

```python
# agent.py
if self._check_cancelled():
    self._cleanup_incomplete_messages()  # 清理不完整消息
    return "Task cancelled by user."
```

支持在执行过程中安全中断。

---

## 总结

| 项目 | 说明 |
|------|------|
| **执行模式** | ReAct (Reasoning + Acting) |
| **核心循环** | 推理 → 行动 → 观察 → 重复 |
| **特点** | 增强版 ReAct，支持长上下文、多工具、MCP 扩展 |
| **代码位置** | `mini_agent/agent.py` 的 `run()` 方法 |

MINI-AGENT 是一个**生产级别的 ReAct Agent 实现**，在保持经典 ReAct 简单优雅的循环机制基础上，增加了上下文管理、持久化记忆、安全机制等生产环境所需的功能。

---

## 参考资料

- 原始 ReAct 论文: [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- 项目代码: `mini_agent/agent.py`
