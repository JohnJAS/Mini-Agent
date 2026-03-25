#!/usr/bin/env python
"""Mini-Agent WebSocket Client 示例脚本

使用前请确保服务器已启动:
    uv run mini-agent-server
"""

import asyncio
from mini_agent.server import MiniAgentClient, chat, chat_stream


async def example_simple_chat():
    """示例 1: 最简单的一次性对话"""
    print("\n" + "=" * 50)
    print("示例 1: 一次性对话 (chat 函数)")
    print("=" * 50)

    response = await chat("你好，请用一句话介绍你自己")
    print(f"\nAgent 回复: {response}")


async def example_complete_response():
    """示例 2: 完整响应模式"""
    print("\n" + "=" * 50)
    print("示例 2: 完整响应模式")
    print("=" * 50)

    async with MiniAgentClient("ws://localhost:8765") as client:
        response = await client.send_message(
            "请列出 3 种编程语言及其主要用途",
            stream=False  # 等待完整响应
        )

        print(f"\n回复内容: {response.content}")
        print(f"停止原因: {response.stop_reason}")


async def example_streaming():
    """示例 3: 流式响应模式"""
    print("\n" + "=" * 50)
    print("示例 3: 流式响应模式")
    print("=" * 50)

    async with MiniAgentClient("ws://localhost:8765") as client:
        print("\nAgent 回复: ", end="", flush=True)

        async for event in client.send_message_stream("请写一首关于春天的短诗"):
            if event["type"] == "thinking":
                print(f"\n\n[思考] {event['content']}\n")
            elif event["type"] == "message_chunk":
                print(event["content"], end="", flush=True)
            elif event["type"] == "tool_call":
                print(f"\n[工具调用] {event['tool_name']}")
            elif event["type"] == "completed":
                print(f"\n\n[完成] 原因: {event['stop_reason']}")


async def example_multi_turn():
    """示例 4: 多轮对话"""
    print("\n" + "=" * 50)
    print("示例 4: 多轮对话（Agent 会记住上下文）")
    print("=" * 50)

    async with MiniAgentClient("ws://localhost:8765") as client:
        # 第一轮
        print("\n用户: 我的名字是小明，我喜欢编程")
        r1 = await client.send_message("我的名字是小明，我喜欢编程", stream=False)
        print(f"Agent: {r1.content}")

        # 第二轮
        print("\n用户: 你还记得我的名字吗？")
        r2 = await client.send_message("你还记得我的名字吗？", stream=False)
        print(f"Agent: {r2.content}")

        # 第三轮
        print("\n用户: 我说过我喜欢什么吗？")
        r3 = await client.send_message("我说过我喜欢什么吗？", stream=False)
        print(f"Agent: {r3.content}")


async def example_with_tool_calls():
    """示例 5: 带工具调用的任务"""
    print("\n" + "=" * 50)
    print("示例 5: 带工具调用的任务")
    print("=" * 50)

    async with MiniAgentClient("ws://localhost:8765") as client:
        response = await client.send_message(
            "请帮我创建一个 test_hello.txt 文件，内容是 'Hello from Mini-Agent!'",
            stream=False
        )

        print(f"\n回复: {response.content}")

        # 显示工具调用详情
        if response.tool_calls:
            print("\n工具调用记录:")
            for tc in response.tool_calls:
                print(f"  - {tc.tool_name}({tc.arguments})")

        if response.tool_results:
            print("\n工具执行结果:")
            for tr in response.tool_results:
                status = "✓ 成功" if tr.success else "✗ 失败"
                print(f"  - {tr.tool_name}: {status}")
                if tr.error:
                    print(f"    错误: {tr.error}")


async def example_with_callbacks():
    """示例 6: 使用回调函数处理事件"""
    print("\n" + "=" * 50)
    print("示例 6: 使用回调函数")
    print("=" * 50)

    def on_thinking(content):
        print(f"\n[思考中...] {content[:100]}...")

    def on_tool_call(tool_info):
        print(f"\n[调用工具] {tool_info.tool_name}")

    def on_tool_result(result_info):
        status = "成功" if result_info.success else "失败"
        print(f"[工具结果] {result_info.tool_name}: {status}")

    async with MiniAgentClient("ws://localhost:8765") as client:
        response = await client.send_message(
            "当前目录下有哪些文件？",
            stream=True,
            on_thinking=on_thinking,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )
        print(f"\n最终回复: {response.content}")


async def example_with_workspace():
    """示例 7: 指定工作目录"""
    import tempfile
    print("\n" + "=" * 50)
    print("示例 7: 指定工作目录")
    print("=" * 50)

    # 使用临时目录作为工作空间
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n工作目录: {tmpdir}")

        async with MiniAgentClient("ws://localhost:8765", workspace=tmpdir) as client:
            response = await client.send_message(
                "创建一个 hello.txt 文件，内容是 'Hello World!'",
                stream=False
            )
            print(f"\n回复: {response.content}")

            # 验证文件是否创建
            import os
            files = os.listdir(tmpdir)
            print(f"目录中的文件: {files}")


# 菜单
EXAMPLES = {
    "1": ("一次性对话", example_simple_chat),
    "2": ("完整响应模式", example_complete_response),
    "3": ("流式响应模式", example_streaming),
    "4": ("多轮对话", example_multi_turn),
    "5": ("带工具调用的任务", example_with_tool_calls),
    "6": ("使用回调函数", example_with_callbacks),
    "7": ("指定工作目录", example_with_workspace),
}


async def main():
    print("\n" + "=" * 50)
    print("Mini-Agent WebSocket Client 示例")
    print("=" * 50)
    print("\n请确保服务器已启动: uv run mini-agent-server")
    print("\n可用示例:")

    for key, (name, _) in EXAMPLES.items():
        print(f"  {key}. {name}")

    print("  a. 运行所有示例")
    print("  q. 退出")

    while True:
        choice = input("\n请选择 (1-7/a/q): ").strip().lower()

        if choice == "q":
            print("再见！")
            break
        elif choice == "a":
            for key in sorted(EXAMPLES.keys()):
                name, func = EXAMPLES[key]
                try:
                    await func()
                except Exception as e:
                    print(f"\n示例 {key} 运行失败: {e}")
        elif choice in EXAMPLES:
            name, func = EXAMPLES[choice]
            try:
                await func()
            except Exception as e:
                print(f"\n运行失败: {e}")
        else:
            print("无效选择，请重试")


if __name__ == "__main__":
    asyncio.run(main())