# MINI-AGENT 上下文管理机制详解

## 概述

本文档详细分析 MINI-AGENT 项目的上下文（Context）管理实现，包括消息历史、Token 控制、智能摘要等核心机制。

---

## 一、核心组件概览

上下文管理主要由 `agent.py` 中的 `Agent` 类实现，核心文件包括：

| 文件 | 作用 |
|------|------|
| `agent.py` | 核心 Agent 类，包含消息管理和摘要逻辑 |
| `schema/schema.py` | Message 数据结构定义 |
| `llm/openai_client.py` | LLM 客户端，处理消息格式转换 |

---

## 二、消息历史管理

### 2.1 Message 数据结构

位置：`mini_agent/schema/schema.py`

```python
class Message(BaseModel):
    """Chat message."""
    
    role: str                              # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]]    # 消息内容
    thinking: str | None = None           # 扩展思考内容（推理过程）
    tool_calls: list[ToolCall] | None = None  # 工具调用列表
    tool_call_id: str | None = None       # 工具调用ID
    name: str | None = None               # 工具名称（用于 tool 角色）
```

### 2.2 消息历史初始化

位置：`agent.py` 第 76 行

```python
# Initialize message history
self.messages: list[Message] = [Message(role="system", content=system_prompt)]
```

消息历史初始只包含系统提示，后续对话会不断追加新的消息。

---

## 三、Token 计数与限制

### 3.1 双重 Token 计数机制

MINI-AGENT 采用双重 Token 计数策略：

| Token 来源 | 获取方式 | 用途 |
|------------|----------|------|
| **本地估算** | `_estimate_tokens()` | 使用 tiktoken 库实时计算 |
| **API 报告** | `response.usage.total_tokens` | 从 LLM API 响应获取 |

```python
# agent.py 第55行：默认 Token 上限
token_limit: int = 80000  # 超过此值触发摘要
```

### 3.2 本地 Token 估算

位置：`agent.py` 第 123-158 行

使用 `cl100k_base` 编码器（GPT-4/Claude/M2 兼容）：

```python
def _estimate_tokens(self) -> int:
    """使用 tiktoken 精确计算消息历史的 Token 数量"""
    
    # 使用 cl100k_base 编码器
    encoding = tiktoken.get_encoding("cl100k_base")
    total_tokens = 0
    
    for msg in self.messages:
        # 1. 计算 text content
        if isinstance(msg.content, str):
            total_tokens += len(encoding.encode(msg.content))
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict):
                    total_tokens += len(encoding.encode(str(block)))
        
        # 2. 计算 thinking（推理过程）
        if msg.thinking:
            total_tokens += len(encoding.encode(msg.thinking))
        
        # 3. 计算 tool_calls
        if msg.tool_calls:
            total_tokens += len(encoding.encode(str(msg.tool_calls)))
        
        # 4. 每个消息的元数据开销（约 4 tokens）
        total_tokens += 4
    
    return total_tokens
```

### 3.3 触发摘要的条件

位置：`agent.py` 第 198-205 行

```python
# 两种情况任一满足即触发摘要
estimated_tokens = self._estimate_tokens()
should_summarize = (
    estimated_tokens > self.token_limit or 
    self.api_total_tokens > self.token_limit
)
```

---

## 四、智能消息摘要策略

### 4.1 核心设计理念

**Agent 模式的摘要策略**：

```
原始消息流:
system → user1 → assistant1 → tool1 → user2 → assistant2 → tool2 → ...

摘要后:
system → user1 → summary1 → user2 → summary2
```

**关键原则**：
1. **保留所有 user 消息** - 因为它们代表用户意图
2. **压缩执行过程** - 将 assistant 和 tool 消息摘要为简短总结
3. **按轮次分段** - 每个 user 消息及其后续执行作为一组

### 4.2 摘要执行流程

位置：`agent.py` 第 180-260 行

```python
async def _summarize_messages(self):
    """消息历史摘要：当 Token 超过限制时执行"""
    
    # 1. 跳过刚完成摘要后的检查（避免连续触发）
    if self._skip_next_token_check:
        self._skip_next_token_check = False
        return
    
    # 2. 检查是否需要摘要
    estimated_tokens = self._estimate_tokens()
    should_summarize = (
        estimated_tokens > self.token_limit or 
        self.api_total_tokens > self.token_limit
    )
    
    if not should_summarize:
        return
    
    # 3. 找到所有 user 消息索引（跳过系统提示）
    user_indices = [
        i for i, msg in enumerate(self.messages) 
        if msg.role == "user" and i > 0
    ]
    
    # 4. 构建新的消息列表
    new_messages = [self.messages[0]]  # 保留系统提示
    
    # 5. 遍历每个 user 消息，摘要其后的执行过程
    for i, user_idx in enumerate(user_indices):
        # 添加当前 user 消息
        new_messages.append(self.messages[user_idx])
        
        # 确定要摘要的消息范围
        if i < len(user_indices) - 1:
            next_user_idx = user_indices[i + 1]
        else:
            next_user_idx = len(self.messages)
        
        # 提取执行消息
        execution_messages = self.messages[user_idx + 1 : next_user_idx]
        
        # 生成摘要
        if execution_messages:
            summary_text = await self._create_summary(execution_messages, i + 1)
            summary_message = Message(
                role="user",
                content=f"[Assistant Execution Summary]\n\n{summary_text}",
            )
            new_messages.append(summary_message)
    
    # 6. 替换消息列表
    self.messages = new_messages
    
    # 7. 跳过下次 Token 检查（等待下次 LLM 调用后更新 api_total_tokens）
    self._skip_next_token_check = True
```

### 4.3 摘要生成逻辑

位置：`agent.py` 第 262-319 行

```python
async def _create_summary(self, messages: list[Message], round_num: int) -> str:
    """为一个执行轮次生成摘要"""
    
    if not messages:
        return ""
    
    # 1. 构建摘要内容
    summary_content = f"Round {round_num} execution process:\n\n"
    
    for msg in messages:
        if msg.role == "assistant":
            content_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            summary_content += f"Assistant: {content_text}\n"
            
            # 记录调用的工具
            if msg.tool_calls:
                tool_names = [tc.function.name for tc in msg.tool_calls]
                summary_content += f"  → Called tools: {', '.join(tool_names)}\n"
        
        elif msg.role == "tool":
            result_preview = msg.content if isinstance(msg.content, str) else str(msg.content)
            summary_content += f"  ← Tool returned: {result_preview}...\n"
    
    # 2. 调用 LLM 生成精简摘要
    summary_prompt = f"""Please provide a concise summary of the following Agent execution process:

{summary_content}

Requirements:
1. Focus on what tasks were completed and which tools were called
2. Keep key execution results and important findings
3. Be concise and clear, within 1000 words
4. Use English
5. Do not include "user" related content, only summarize the Agent's execution process"""
    
    # 3. 调用 LLM 生成摘要
    response = await self.llm.generate(messages=[
        Message(
            role="system",
            content="You are an assistant skilled at summarizing Agent execution processes.",
        ),
        Message(role="user", content=summary_prompt),
    ])
    
    return response.content
```

---

## 五、执行流程中的上下文管理

### 5.1 主循环中的上下文检查

位置：`agent.py` 第 321-519 行

```python
async def run(self, cancel_event: Optional[asyncio.Event] = None) -> str:
    """Agent 主循环"""
    
    step = 0
    while step < self.max_steps:
        # 1. 检查是否取消
        if self._check_cancelled():
            self._cleanup_incomplete_messages()
            return "Task cancelled by user."
        
        # 2. 每个步骤开始前检查并摘要消息历史
        await self._summarize_messages()
        
        # 3. 调用 LLM
        response = await self.llm.generate(messages=self.messages, tools=tool_list)
        
        # 4. 累计 API 报告的 Token 使用量
        if response.usage:
            self.api_total_tokens = response.usage.total_tokens
        
        # 5. 添加助手消息到历史
        assistant_msg = Message(
            role="assistant",
            content=response.content,
            thinking=response.thinking,
            tool_calls=response.tool_calls,
        )
        self.messages.append(assistant_msg)
        
        # 6. 如果没有工具调用，任务完成
        if not response.tool_calls:
            return response.content
        
        # 7. 执行工具调用
        for tool_call in response.tool_calls:
            result = await tool.execute(**arguments)
            
            # 添加工具结果消息
            tool_msg = Message(
                role="tool",
                content=result.content if result.success else f"Error: {result.error}",
                tool_call_id=tool_call_id,
                name=function_name,
            )
            self.messages.append(tool_msg)
        
        step += 1
```

### 5.2 思考内容的保留

位置：`llm/openai_client.py` 第 160-166 行

代码中特别强调了 `thinking`（推理过程）的完整保留：

```python
# IMPORTANT: Add reasoning_details if thinking is present
# This is CRITICAL for Interleaved Thinking to work properly!
# The complete response_message (including reasoning_details) must be
# preserved in Message History and passed back to the model in the next turn.
# This ensures the model's chain of thought is not interrupted.

if msg.thinking:
    assistant_msg["reasoning_details"] = [{"text": msg.thinking}]
```

这确保模型的思维链不会因为上下文管理而被打断。

---

## 六、关键技术细节

### 6.1 消息角色说明

| 角色 | 说明 | 示例 |
|------|------|------|
| `system` | 系统提示 | 初始配置的一次性设置 |
| `user` | 用户消息 | 用户的输入和指令 |
| `assistant` | 助手回复 | LLM 的响应和工具调用 |
| `tool` | 工具结果 | 工具执行后的返回值 |

### 6.2 防止连续触发

代码中使用了 `_skip_next_token_check` 标志来防止在刚完成摘要后立即再次触发摘要：

```python
# 摘要完成后设置标志
self._skip_next_token_check = True

# 下次检查时跳过
if self._skip_next_token_check:
    self._skip_next_token_check = False
    return  # 跳过本次检查
```

这是因为 API 返回的 `total_tokens` 是在请求之后才更新的，需要等待下一次 LLM 调用后才能获取准确的 Token 数量。

### 6.3 消息清理机制

位置：`agent.py` 第 100-121 行

当用户取消执行时，清理不完整的消息：

```python
def _cleanup_incomplete_messages(self):
    """移除不完整的助手消息及其工具结果
    
    这确保取消后消息一致性，只移除当前步骤的不完整消息，
    保留已完成的步骤。
    """
    # 找到最后一个助手消息的索引
    last_assistant_idx = -1
    for i in range(len(self.messages) - 1, -1, -1):
        if self.messages[i].role == "assistant":
            last_assistant_idx = i
            break
    
    if last_assistant_idx == -1:
        return
    
    # 移除最后一个助手消息及其之后的所有消息
    self.messages = self.messages[:last_assistant_idx]
```

---

## 七、总结

### 7.1 上下文管理的四大支柱

| 机制 | 实现方式 |
|------|----------|
| **消息存储** | `self.messages` 列表，维护完整的对话历史 |
| **Token 控制** | 本地估算 + API 报告双重检查，默认 80K 上限 |
| **智能摘要** | 按 user 消息分段摘要，保留用户意图，压缩执行过程 |
| **思考保留** | 完整保留模型的推理过程（reasoning_details） |

### 7.2 设计优势

1. **无限上下文能力**：通过摘要机制支持处理无限长的任务
2. **意图保留**：始终保留用户消息，确保不丢失任务目标
3. **思维连贯**：完整保留推理过程，保证 Agent 思维链不断裂
4. **双重保障**：本地估算 + API 报告，避免 Token 超限
5. **安全取消**：支持安全取消执行，清理不完整消息

### 7.3 配置参数

在 `Agent` 初始化时可以调整以下参数：

```python
Agent(
    llm_client=...,
    system_prompt=...,
    tools=...,
    max_steps=50,           # 最大执行步骤
    token_limit=80000,      # Token 限制（触发摘要的值）
    workspace_dir="./workspace",
)
```

---

## 参考代码

- 核心实现：`mini_agent/agent.py`
- 数据结构：`mini_agent/schema/schema.py`
- LLM 客户端：`mini_agent/llm/openai_client.py`

---

**文档信息**
- 分析时间：2026年2月22日
- 项目路径：D:\AIworkspace\Mini-Agent\mini_agent
