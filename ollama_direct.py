"""
OllamaDirectExecutor - 直接调用Ollama API
不走CLI，速度更快！
"""

import json
import requests
from typing import Optional, Dict, Any
from datetime import datetime


class OllamaDirectExecutor:
    """
    直接调用 Ollama API 的执行器
    - 不走 CLI，无进程启动开销
    - 速度快，延迟低
    - 支持所有 Ollama 模型
    """
    
    def __init__(self, 
                 base_url: str = "http://localhost:11434",
                 model: str = "gemma4:e4b",
                 timeout: int = None):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout  # None = 无限制
    
    def execute(self, 
                prompt: str, 
                task_name: str = "task",
                output_file: str = None,
                system: str = None,
                timeout: int = None) -> Dict[str, Any]:
        """
        直接通过 API 调用 Ollama
        
        Args:
            prompt: 要执行的提示词
            task_name: 任务名称
            output_file: 输出文件路径（可选）
            system: 系统提示词
        
        Returns:
            执行结果字典
        """
        print(f"[OllamaDirect] 开始执行任务: {task_name}")
        print(f"[OllamaDirect] 模型: {self.model}")
        
        # 构建请求
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
            }
        }
        
        if system:
            payload["system"] = system
        
        start_time = datetime.now()
        
        effective_timeout = timeout if timeout is not None else self.timeout
        
        try:
            if effective_timeout:
                response = requests.post(url, json=payload, timeout=effective_timeout)
            else:
                # 无超时限制，但使用保守的连接/读取超时防止永久挂起
                response = requests.post(url, json=payload, timeout=(30, 120))
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            if response.status_code == 200:
                result = response.json()
                output_text = result.get("response", "")
                
                if output_file:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(output_text)
                    print(f"[OllamaDirect] 结果已保存: {output_file}")
                
                print(f"[OllamaDirect] ✅ 任务完成！耗时: {duration:.1f}秒")
                
                return {
                    "success": True,
                    "stdout": output_text,
                    "duration": duration,
                    "model": self.model,
                    "task_name": task_name,
                    "done": result.get("done", True),
                    "eval_count": result.get("eval_count", 0),
                }
            else:
                print(f"[OllamaDirect] ❌ 请求失败: {response.status_code}")
                print(f"[OllamaDirect] 错误: {response.text[:500]}")
                
                return {
                    "success": False,
                    "error": f"API错误: {response.status_code}",
                    "stderr": response.text,
                    "duration": duration,
                    "task_name": task_name,
                }
                
        except requests.exceptions.Timeout:
            print(f"[OllamaDirect] ❌ 任务超时！")
            return {
                "success": False,
                "error": "请求超时",
                "task_name": task_name,
            }
        except Exception as e:
            print(f"[OllamaDirect] ❌ 执行异常: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "task_name": task_name,
            }


# 全局实例
_executor: Optional[OllamaDirectExecutor] = None

def get_ollama_direct() -> OllamaDirectExecutor:
    """获取Ollama直接执行器实例"""
    global _executor
    if _executor is None:
        _executor = OllamaDirectExecutor(
            base_url="http://localhost:11434",
            model="gemma4:e4b"
        )
    return _executor


if __name__ == "__main__":
    print("=" * 50)
    print("OllamaDirect 测试")
    print("=" * 50)
    
    executor = get_ollama_direct()
    print(f"API地址: {executor.base_url}")
    print(f"模型: {executor.model}")
    
    # 测试
    result = executor.execute(
        prompt="用一句话介绍自己",
        task_name="test"
    )
    
    print(f"\n结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"输出: {result.get('stdout', result.get('error', '无输出'))[:200]}")
