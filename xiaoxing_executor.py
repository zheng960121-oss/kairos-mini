"""
XiaoXingExecutor - 小星执行器
Rust版Claw Code，专门负责代码执行任务
归小兰管理的小弟
"""

import os
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class XiaoXingExecutor:
    """
    小星 - Rust版Claw Code执行器
    - 速度快，性能强
    - 归小兰管理
    - 专门处理编程/代码任务
    """
    
    def __init__(self, 
                 claw_path: str = None,
                 workspace: str = None):
        # claw 二进制路径：优先从环境变量读取，其次尝试常见路径
        if claw_path is None:
            claw_path = os.environ.get("CLAW_PATH", "")
        
        if not claw_path or not Path(claw_path).exists():
            # 尝试常见路径
            candidates = [
                str(Path.home() / "Desktop" / "11" / "claw-code" / "rust" / "target" / "debug" / "claw"),
                str(Path.home() / "Desktop" / "11" / "claw" / "claw"),
                str(Path.home() / "go" / "bin" / "claw"),
            ]
            found = False
            for candidate in candidates:
                if Path(candidate).exists():
                    claw_path = candidate
                    found = True
                    break
            if not found:
                raise FileNotFoundError(
                    f"小星不存在！请设置 CLAW_PATH 环境变量指向 claw 二进制路径。"
                    f"\n尝试过的路径: {candidates}"
                )

        self.claw_path = claw_path
        self.workspace = workspace or str(Path.home() / "Desktop" / "11")
        
        # 设置环境变量（使用Ollama本地模型）
        self.env = os.environ.copy()
        self.env["ANTHROPIC_API_KEY"] = "ollama"
        self.env["ANTHROPIC_BASE_URL"] = "http://localhost:11434"
        
        # 检查claw是否存在
        if not Path(self.claw_path).exists():
            raise FileNotFoundError(f"小星不存在: {self.claw_path}")
    
    def execute(self, 
                prompt: str, 
                task_name: str = "task",
                output_file: str = None,
                timeout: int = None) -> Dict[str, Any]:
        """
        执行任务
        
        Args:
            prompt: 要执行的提示词
            task_name: 任务名称
            output_file: 输出文件路径（可选）
            timeout: 超时时间（秒）
        
        Returns:
            执行结果字典
        """
        print(f"[小星] 🌟 开始执行任务: {task_name}")
        print(f"[小星] 工作目录: {self.workspace}")
        
        # 构建命令
        # 注意：Ollama的模型名需要是完整的，如 gemma4:e4b
        # 使用 --output-format json 模式，因为这个模式支持 Ollama
        ollama_model = "gemma4:e4b"
        
        # 构建命令
        # 注意：使用 'prompt' 关键字而不是 '-p' shorthand，这样环境变量才能正确传递
        ollama_model = "gemma4:e4b"
        
        # 构建命令
        # 注意：使用 'prompt' 关键字让claw从命令行接收prompt文本
        ollama_model = "gemma4:e4b"
        
        cmd = [
            self.claw_path,
            "--model", ollama_model,
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "prompt",
            prompt  # 直接传递 prompt 文本
        ]
        
        # 添加工作目录
        cmd.extend(["--add-dir", self.workspace])
        
        # 执行
        start_time = datetime.now()
        try:
            # 只有timeout有值时才传参，否则不限制
            if timeout:
                result = subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=timeout, cwd=self.workspace)
            else:
                result = subprocess.run(cmd, env=self.env, capture_output=True, text=True, cwd=self.workspace)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            success = result.returncode == 0
            
            response = {
                "success": success,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": duration,
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
            
            # 解析JSON输出
            if success and result.stdout:
                try:
                    json_output = json.loads(result.stdout)
                    response["stdout"] = json_output.get("message", result.stdout)
                    response["model"] = json_output.get("model", ollama_model)
                    response["usage"] = json_output.get("usage", {})
                except json.JSONDecodeError:
                    pass  # 保持原样
            
            if output_file and success:
                Path(output_file).write_text(result.stdout, encoding="utf-8")
                response["output_file"] = output_file
            
            if success:
                print(f"[小星] ✅ 任务完成！耗时: {duration:.1f}秒")
            else:
                print(f"[小星] ❌ 任务失败！返回码: {result.returncode}")
                if result.stderr:
                    print(f"[小星] 错误: {result.stderr[:500]}")
            
            return response
            
        except subprocess.TimeoutExpired:
            print(f"[小星] ❌ 任务超时！超过{timeout}秒")
            return {
                "success": False,
                "error": f"任务超时（{timeout}秒）",
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
        except Exception as e:
            print(f"[小星] ❌ 执行异常: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "task_name": task_name,
                "timestamp": start_time.isoformat()
            }
    
    def code_task(self, 
                  task: str,
                  language: str = "python",
                  output_file: str = None) -> Dict[str, Any]:
        """
        执行代码任务
        
        Args:
            task: 代码任务描述
            language: 编程语言
            output_file: 输出文件路径
        
        Returns:
            执行结果
        """
        prompt = f"""你是一个专业的{language}程序员。请完成以下编程任务：

{task}

要求：
- 代码要完整可运行
- 简洁高效
- 有适当的注释
- 直接输出代码，不要解释

请开始编程："""

        return self.execute(
            prompt=prompt,
            task_name=f"代码任务({language})",
            output_file=output_file
        )
    
    def website_task(self,
                     description: str,
                     output_dir: str = None) -> Dict[str, Any]:
        """
        执行网站开发任务
        
        Args:
            description: 网站需求描述
            output_dir: 输出目录
        
        Returns:
            执行结果
        """
        if output_dir:
            full_path = str(Path(output_dir) / "index.html")
        else:
            full_path = None
        
        prompt = f"""你是一个专业的网站开发者。请根据以下需求创建一个网站：

{description}

要求：
- 响应式设计
- 美观的CSS样式
- 纯HTML/CSS/JS单文件
- 使用emoji代替图片
- 直接创建文件并输出结果

请开始开发："""

        return self.execute(
            prompt=prompt,
            task_name="网站开发",
            output_file=full_path
        )


# 全局实例
_executor: Optional[XiaoXingExecutor] = None

def get_xiaoxing() -> XiaoXingExecutor:
    """获取小星实例"""
    global _executor
    if _executor is None:
        _executor = XiaoXingExecutor()
    return _executor


def execute_xiaoxing_task(prompt: str, **kwargs) -> Dict[str, Any]:
    """便捷函数：通过小星执行任务"""
    return get_xiaoxing().execute(prompt, **kwargs)


def code_task(task: str, language: str = "python", **kwargs) -> Dict[str, Any]:
    """便捷函数：代码任务"""
    return get_xiaoxing().code_task(task, language, **kwargs)


def website_task(description: str, **kwargs) -> Dict[str, Any]:
    """便捷函数：网站任务"""
    return get_xiaoxing().website_task(description, **kwargs)


if __name__ == "__main__":
    print("=" * 50)
    print("🌟 小星测试")
    print("=" * 50)
    
    xiaoxing = get_xiaoxing()
    print(f"小星路径: {xiaoxing.claw_path}")
    
    # 简单测试
    result = xiaoxing.execute(
        prompt="用一句话介绍自己",
        task_name="test"
    )
    
    print(f"\n结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"输出: {result.get('stdout', result.get('error', '无输出'))[:100]}")
