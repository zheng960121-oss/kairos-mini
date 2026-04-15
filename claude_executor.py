"""
ClaudeCodeExecutor - 小卡的Claude Code执行器
让小卡能够调用Claude Code执行AI任务
"""

import os
import subprocess
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class ClaudeCodeExecutor:
    """
    Claude Code 执行器
    - 调用本地 Ollama 模型
    - 通过 Claude Code CLI 执行任务
    """
    
    def __init__(self, 
                 ollama_base_url: str = "http://localhost:11434",
                 ollama_api_key: str = "ollama",
                 model: str = "gemma4:e4b",
                 workspace: str = None):
        self.ollama_base_url = ollama_base_url
        self.ollama_api_key = ollama_api_key
        self.model = model
        self.workspace = workspace or str(Path.home() / "Desktop" / "11")
        
        # 设置环境变量
        self.env = os.environ.copy()
        self.env["ANTHROPIC_BASE_URL"] = self.ollama_base_url
        self.env["ANTHROPIC_API_KEY"] = self.ollama_api_key
    
    def execute(self, 
                prompt: str, 
                task_name: str = "task",
                output_file: str = None,
                timeout: int = 300,
                verbose: bool = False) -> Dict[str, Any]:
        """
        执行 Claude Code 任务
        
        Args:
            prompt: 要执行的提示词
            task_name: 任务名称（用于生成文件）
            output_file: 输出文件路径（可选）
            timeout: 超时时间（秒）
            verbose: 是否显示详细输出
        
        Returns:
            执行结果字典
        """
        print(f"[ClaudeCodeExecutor] 开始执行任务: {task_name}")
        print(f"[ClaudeCodeExecutor] 模型: {self.model}")
        print(f"[ClaudeCodeExecutor] 工作目录: {self.workspace}")
        
        # 构建命令
        cmd = [
            "claude",
            "-p",  # print mode, 非交互
            "--print",
            "--model", self.model,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--output-format", "text"
        ]
        
        # 添加工作目录
        if self.workspace:
            cmd.extend(["--add-dir", self.workspace])
        
        # 构建完整的prompt（包含指令）
        full_prompt = f"""你是一个专业的写作助手。请完成以下任务：

{prompt}

请直接输出结果，不需要解释过程。如果需要保存文件，请保存到适当的位置。"""

        # 执行
        start_time = datetime.now()
        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace
            )
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            success = result.returncode == 0
            
            if verbose:
                print(f"[ClaudeCodeExecutor] 返回码: {result.returncode}")
                print(f"[ClaudeCodeExecutor] 执行时间: {duration:.1f}秒")
            
            response = {
                "success": success,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": duration,
                "model": self.model,
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
            
            if output_file:
                Path(output_file).write_text(result.stdout, encoding="utf-8")
                response["output_file"] = output_file
                if verbose:
                    print(f"[ClaudeCodeExecutor] 结果已保存: {output_file}")
            
            if success:
                print(f"[ClaudeCodeExecutor] ✅ 任务完成！耗时: {duration:.1f}秒")
            else:
                print(f"[ClaudeCodeExecutor] ❌ 任务失败！返回码: {result.returncode}")
                if result.stderr:
                    print(f"[ClaudeCodeExecutor] 错误: {result.stderr[:500]}")
            
            return response
            
        except subprocess.TimeoutExpired:
            print(f"[ClaudeCodeExecutor] ❌ 任务超时！超过{timeout}秒")
            return {
                "success": False,
                "error": f"任务超时（{timeout}秒）",
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
        except Exception as e:
            print(f"[ClaudeCodeExecutor] ❌ 执行异常: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
    
    def write_chapter(self, 
                      chapter_num: int,
                      outline_file: str,
                      output_file: str = None,
                      novel_path: str = None) -> Dict[str, Any]:
        """
        写小说章节
        
        Args:
            chapter_num: 章节号
            outline_file: 大纲文件路径
            output_file: 输出文件路径
            novel_path: 小说目录路径
        
        Returns:
            执行结果
        """
        if novel_path is None:
            novel_path = str(Path.home() / "Desktop" / "11" / "novel-writing")
        
        if output_file is None:
            output_file = str(Path(novel_path) / f"正文-第{chapter_num}章.md")
        
        outline_content = Path(outline_file).read_text(encoding="utf-8")
        
        prompt = f"""请根据以下大纲，写第{chapter_num}章的正文。

章节大纲：
{outline_content}

要求：
- 字数：3500-4000字
- 风格：玄幻小说，热血燃系
- 人物：林寒（主角）、周蛮（兄弟）、苏幼微（女主）
- 格式：每个段落之间空一行，章节结尾用"**（第{chapter_num}章完）**"
- 直接输出正文，不要额外的说明

请开始写作："""

        return self.execute(
            prompt=prompt,
            task_name=f"第{chapter_num}章",
            output_file=output_file
        )


# 全局实例
_executor: Optional[ClaudeCodeExecutor] = None

def get_executor() -> ClaudeCodeExecutor:
    """获取全局执行器实例"""
    global _executor
    if _executor is None:
        _executor = ClaudeCodeExecutor()
    return _executor


def execute_task(prompt: str, **kwargs) -> Dict[str, Any]:
    """便捷函数：执行任意任务"""
    return get_executor().execute(prompt, **kwargs)


def write_chapter_task(chapter_num: int, outline_file: str, **kwargs) -> Dict[str, Any]:
    """便捷函数：写小说章节"""
    return get_executor().write_chapter(chapter_num, outline_file, **kwargs)


if __name__ == "__main__":
    # 测试
    print("=" * 50)
    print("ClaudeCodeExecutor 测试")
    print("=" * 50)
    
    executor = ClaudeCodeExecutor()
    
    # 简单测试
    result = executor.execute(
        prompt="用一句话介绍自己",
        task_name="test"
    )
    
    print("\n结果:")
    print(result.get("stdout", result.get("error", "无输出")))
