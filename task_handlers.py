"""
Task Handlers - 任务处理器注册
支持本地模型调用的任务处理器
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 延迟导入，避免循环依赖
_executor = None

def get_ollama_executor():
    """获取Ollama直接执行器（延迟加载）"""
    global _executor
    if _executor is None:
        from ollama_direct import OllamaDirectExecutor
        _executor = OllamaDirectExecutor(
            base_url="http://localhost:11434",
            model="gemma4:e4b"
        )
    return _executor


def write_chapter_handler(task) -> str:
    """
    写小说章节任务处理器
    必须使用本地模型（Claude Code + Ollama）
    
    Task metadata expected:
        - chapter_num: int 章节号
        - outline_file: str 大纲文件路径
        - output_file: str (optional) 输出文件路径
        - novel_path: str (optional) 小说目录路径
    """
    import json
    
    print(f"[write_chapter_handler] 开始处理任务: {task.id}")
    print(f"[write_chapter_handler] 描述: {task.description}")
    
    # 解析任务参数
    metadata = task.metadata or {}
    chapter_num = metadata.get("chapter_num")
    outline_file = metadata.get("outline_file", "")
    output_file = metadata.get("output_file", "")
    novel_path = metadata.get("novel_path", "")
    
    # 从描述中提取章节号（如果metadata没有）
    if not chapter_num:
        if "第" in task.description and "章" in task.description:
            try:
                import re
                match = re.search(r'第(\d+)章', task.description)
                if match:
                    chapter_num = int(match.group(1))
            except:
                pass
        if not chapter_num:
            chapter_num = 1
    
    # 获取执行器
    executor = get_ollama_executor()
    
    # 读取大纲（如果提供的是文件路径）
    if outline_file and Path(outline_file).exists():
        outline_content = Path(outline_file).read_text(encoding="utf-8")
    elif "大纲" in task.description:
        # 尝试从小说目录查找大纲
        novel_dir = Path(novel_path) if novel_path else Path.home() / "Desktop" / "11" / "novel-writing"
        possible_outline = novel_dir / f"第1卷-第{chapter_num}章-详细大纲.md"
        if possible_outline.exists():
            outline_content = possible_outline.read_text(encoding="utf-8")
        else:
            outline_content = task.description
    else:
        outline_content = task.description
    
    # 确定输出文件
    if not output_file:
        novel_dir = Path(novel_path) if novel_path else Path.home() / "Desktop" / "11" / "novel-writing"
        output_file = str(novel_dir / f"正文-第{chapter_num}章.md")
    
    # 执行写作任务
    print(f"[write_chapter_handler] 章节号: {chapter_num}")
    print(f"[write_chapter_handler] 输出文件: {output_file}")
    print(f"[write_chapter_handler] 使用模型: {executor.model}")
    
    result = executor.execute(
        prompt=f"""你是一个专业的玄幻小说作家。请根据以下大纲，写第{chapter_num}章的正文。

大纲内容：
{outline_content}

写作要求：
- 字数：3500-4000字
- 风格：玄幻小说，热血燃系，节奏快
- 人物：林寒（主角，时间血脉）、周蛮（好兄弟）、苏幼微（女主，冰系血脉）
- 格式：每个段落之间空一行，章节结尾用"**（第{chapter_num}章完）**"
- 直接输出正文，不要任何解释或说明

请开始写作：""",
        task_name=f"第{chapter_num}章",
        output_file=output_file,
        timeout=task.timeout or None
    )
    
    if result["success"]:
        return f"完成！已保存到: {output_file}"
    else:
        raise Exception(f"写作失败: {result.get('error', '未知错误')}")


def general_ai_task_handler(task) -> str:
    """
    通用AI任务处理器
    使用本地模型执行任意任务
    """
    executor = get_ollama_executor()
    
    print(f"[general_ai_task_handler] 开始处理任务: {task.id}")
    print(f"[general_ai_task_handler] 使用模型: {executor.model}")
    
    result = executor.execute(
        prompt=task.description,
        task_name=task.name,
        timeout=task.timeout or None
    )
    
    if result["success"]:
        output = result.get("stdout", "执行成功")
        if result.get("output_file"):
            output += f"\n\n已保存到: {result['output_file']}"
        return output
    else:
        raise Exception(f"任务失败: {result.get('error', '未知错误')}")


def register_all_handlers(task_queue):
    """
    注册所有任务处理器
    """
    # 写小说章节 - 必须用本地模型
    task_queue.register_handler("write_chapter", write_chapter_handler)
    task_queue.register_handler("novel_chapter", write_chapter_handler)
    
    # 通用AI任务 - 必须用本地模型
    task_queue.register_handler("ai_task", general_ai_task_handler)
    task_queue.register_handler("claude_task", general_ai_task_handler)
    
    print("[TaskHandlers] 已注册本地模型任务处理器:")
    print("  - write_chapter: 写小说章节")
    print("  - novel_chapter: 写小说章节（别名）")
    print("  - ai_task: 通用AI任务")
    print("  - claude_task: 通用AI任务（别名）")
    print(f"[TaskHandlers] 默认模型: gemma4:e4b")
    print(f"[TaskHandlers] API地址: http://localhost:11434")


# 测试
if __name__ == "__main__":
    print("=" * 50)
    print("TaskHandlers 测试")
    print("=" * 50)
    
    # 测试执行器
    executor = get_ollama_executor()
    print(f"执行器模型: {executor.model}")
    
    # 简单测试
    result = executor.execute(
        prompt="用一句话介绍自己",
        task_name="test"
    )
    print(f"\n测试结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"输出: {result.get('stdout', result.get('error'))[:100]}")
