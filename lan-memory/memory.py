"""
lan-memory: 基于 Hindsight 的轻量级 Agent 记忆系统

核心概念 (来自 Hindsight):
- World Facts: 关于世界的客观事实 ("火炉是热的")
- Experiences: Agent 的亲身体验 ("我摸火炉被烫了")  
- Mental Models: 从反思中学到的理解

三种核心操作:
- Retain: 存储信息到记忆
- Recall: 搜索记忆
- Reflect: 反思生成新洞察
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# Hindsight 客户端
try:
    from hindsight_client import Hindsight, HindsightClient
    HINDSIGHT_AVAILABLE = True
except ImportError:
    HINDSIGHT_AVAILABLE = False
    print("Warning: hindsight-client not installed. Run: pip install hindsight-client")

# 尝试导入 jieba 用于中文分词
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    print("Warning: jieba not installed, Chinese tokenization will be less accurate")

# 配置文件路径
CONFIG_FILE = Path(__file__).parent / "memory_config.json"
MEMORY_FILE = Path(__file__).parent / "memory_data.json"

DEFAULT_BANK_ID = "default"
DEFAULT_MISSION = "你是一个有帮助的AI助手，善于记忆和反思。"


class MemorySystem:
    """
    基于 Hindsight 架构的轻量级 Agent 记忆系统。
    
    特点:
    - 使用 Hindsight API 进行记忆存储和检索
    - 支持三种记忆类型: facts, experiences, mental_models
    - 内置 Reflect 反思生成能力
    - 向后兼容: 如果没有 Hindsight API，可回退到本地模式
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8888",
        bank_id: str = DEFAULT_BANK_ID,
        local_mode: bool = False,
        llm_provider: str = "openai",
        llm_model: str = "gpt-4o-mini",
        llm_api_key: Optional[str] = None
    ):
        """
        初始化记忆系统。
        
        Args:
            api_url: Hindsight API 服务器地址
            bank_id: 记忆库 ID
            local_mode: 如果为 True 且没有 Hindsight，使用本地 JSON 存储
            llm_provider: LLM 提供商 (openai, anthropic, gemini, ollama 等)
            llm_model: LLM 模型名称
            llm_api_key: LLM API Key
        """
        self.api_url = api_url
        self.bank_id = bank_id
        self.local_mode = local_mode
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        
        # 如果没有 API Key，尝试从环境变量获取
        if llm_api_key is None:
            env_key = f"{llm_provider.upper()}_API_KEY"
            llm_api_key = os.environ.get(env_key)
        
        self._hindsight = None
        self._local_memories = []
        
        # 初始化 Hindsight 客户端
        if HINDSIGHT_AVAILABLE and not local_mode:
            try:
                self._hindsight = Hindsight(base_url=api_url)
                print(f"Hindsight 客户端已连接到 {api_url}")
                
                # 创建或获取记忆库
                self._ensure_bank()
            except Exception as e:
                print(f"Warning: 无法连接到 Hindsight API: {e}")
                print("将使用本地模式")
                self._hindsight = None
                self._local_mode = True
        else:
            print("使用本地存储模式")
            self._local_mode = True
        
        # 加载本地记忆
        self._load_local_memories()
        
        print(f"MemorySystem 初始化完成. 模式: {'Hindsight' if self._hindsight else 'Local'}")

    def _ensure_bank(self):
        """确保记忆库存在"""
        try:
            banks = self._hindsight.banks()
            bank_ids = [b.bank_id for b in banks]
            
            if self.bank_id not in bank_ids:
                self._hindsight.create_bank(
                    bank_id=self.bank_id,
                    mission=DEFAULT_MISSION
                )
                print(f"创建新记忆库: {self.bank_id}")
            else:
                print(f"使用已有记忆库: {self.bank_id}")
                
            # 设置任务
            self._hindsight.set_mission(self.bank_id, DEFAULT_MISSION)
            
        except Exception as e:
            print(f"Warning: 无法创建记忆库: {e}")

    def _load_local_memories(self):
        """从本地文件加载记忆"""
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    self._local_memories = json.load(f)
            except json.JSONDecodeError:
                self._local_memories = []
        print(f"加载了 {len(self._local_memories)} 条本地记忆")

    def _save_local_memories(self):
        """保存记忆到本地文件"""
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._local_memories, f, indent=2, ensure_ascii=False)

    # ==================== 核心 API ====================

    def retain(
        self,
        content: str,
        memory_type: str = "experience",
        entities: Optional[list] = None,
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
        context: Optional[str] = None
    ) -> str:
        """
        存储记忆到系统 (Retain)。
        
        Args:
            content: 要记忆的内容
            memory_type: 记忆类型 ('fact', 'experience', 'mental_model')
            entities: 实体列表 [{"name": "实体名", "type": "类型"}, ...]
            tags: 标签列表
            metadata: 额外元数据
            context: 上下文信息
            
        Returns:
            记忆 ID
        """
        if self._hindsight:
            try:
                response = self._hindsight.retain(
                    bank_id=self.bank_id,
                    content=content,
                    entities=entities,
                    tags=tags,
                    metadata=metadata,
                    context=context
                )
                print(f"记忆已存储到 Hindsight: {response.memory_id}")
                return response.memory_id
            except Exception as e:
                print(f"Hindsight retain 失败: {e}，回退到本地存储")
        
        # 本地模式 - 统一使用 content 字段
        memory_id = f"local_{len(self._local_memories) + 1}"
        memory = {
            "id": memory_id,
            "content": content,  # 统一使用 content
            "type": memory_type,
            "entities": entities or [],
            "tags": tags or [],
            "metadata": metadata or {},
            "context": context,
            "timestamp": datetime.now().isoformat()
        }
        self._local_memories.append(memory)
        self._save_local_memories()
        print(f"记忆已存储到本地: {memory_id}")
        return memory_id

    def retain_fact(self, fact: str, **kwargs) -> str:
        """
        存储世界事实 (World Fact)。
        例如: "Python 是一种编程语言"
        """
        return self.retain(fact, memory_type="fact", **kwargs)

    def retain_experience(self, experience: str, **kwargs) -> str:
        """
        存储亲身体验 (Experience)。
        例如: "用户今天让我帮他下载 Hindsight"
        """
        return self.retain(experience, memory_type="experience", **kwargs)

    def retain_insight(self, insight: str, **kwargs) -> str:
        """
        存储从反思中学到的洞察 (Mental Model)。
        例如: "用户更喜欢用中文交流"
        """
        return self.retain(insight, memory_type="mental_model", **kwargs)

    def recall(
        self,
        query: str,
        max_results: int = 5,
        memory_types: Optional[list] = None,
        include_entities: bool = True,
        include_chunks: bool = False
    ) -> list:
        """
        搜索记忆 (Recall)。
        
        Args:
            query: 搜索查询
            max_results: 最大返回数量
            memory_types: 筛选记忆类型 ['facts', 'experiences', 'mental_models']
            include_entities: 是否包含实体信息
            include_chunks: 是否包含原文片段
            
        Returns:
            记忆列表
        """
        if self._hindsight:
            try:
                response = self._hindsight.recall(
                    bank_id=self.bank_id,
                    query=query,
                    types=memory_types,
                    include_entities=include_entities,
                    include_chunks=include_chunks,
                    max_chunk_tokens=8192 if include_chunks else 0
                )
                results = []
                for item in response.results:
                    results.append({
                        "content": item.content,
                        "score": item.score,
                        "type": getattr(item, 'type', 'unknown'),
                        "entities": getattr(item, 'entities', [])
                    })
                return results
            except Exception as e:
                print(f"Hindsight recall 失败: {e}，回退到本地搜索")
        
        # 本地模式: 简单关键词匹配
        return self._local_search(query, max_results)

    def _local_search(self, query: str, max_results: int = 5) -> list:
        """本地搜索实现"""
        if not self._local_memories:
            return []
        
        # 分词
        query_words = set(jieba.cut(query) if JIEBA_AVAILABLE else query)
        
        # 计算相关性分数
        scored = []
        for mem in self._local_memories:
            # 兼容 'content' 和 'text' 字段
            text = mem.get('content') or mem.get('text', '')
            content_words = set(jieba.cut(text) if JIEBA_AVAILABLE else text)
            intersection = query_words & content_words
            if intersection:
                score = len(intersection) / len(query_words | content_words)
            else:
                score = 0
            scored.append((score, mem))
        
        # 排序返回
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, mem in scored[:max_results]:
            text = mem.get('content') or mem.get('text', '')
            results.append({
                "content": text,
                "score": score,
                "type": mem.get('type', 'unknown'),
                "entities": mem.get('entities', [])
            })
        return results

    def reflect(
        self,
        query: str,
        context: Optional[str] = None,
        max_tokens: int = 2048
    ) -> str:
        """
        反思生成新洞察 (Reflect)。
        
        Args:
            query: 反思主题
            context: 额外上下文
            max_tokens: 最大生成 tokens
            
        Returns:
            反思生成的洞察
        """
        if self._hindsight:
            try:
                response = self._hindsight.reflect(
                    bank_id=self.bank_id,
                    query=query,
                    context=context,
                    max_tokens=max_tokens
                )
                return response.reflection
            except Exception as e:
                print(f"Hindsight reflect 失败: {e}，使用本地模拟")
        
        # 本地模式: 简单的上下文总结
        return self._local_reflect(query, context)

    def _local_reflect(self, query: str, context: Optional[str] = None) -> str:
        """本地反思模拟"""
        # 获取相关记忆
        relevant = self.recall(query, max_results=5)
        if not relevant:
            return f"关于 '{query}' 没有足够的记忆来进行反思。"
        
        # 简单总结
        summary_parts = [f"根据我的记忆，关于 '{query}':"]
        for i, item in enumerate(relevant, 1):
            summary_parts.append(f"{i}. {item['content']}")
        
        if context:
            summary_parts.append(f"\n结合上下文 '{context}':")
        
        summary_parts.append(f"\n反思: 从以上记忆来看，{query} 相关的关键点是...")
        return "\n".join(summary_parts)

    # ==================== 辅助 API ====================

    def list_memories(self, memory_type: Optional[str] = None) -> list:
        """列出所有记忆"""
        if self._hindsight:
            try:
                response = self._hindsight.list_memories(
                    bank_id=self.bank_id,
                    types=[memory_type] if memory_type else None
                )
                return [{"id": m.memory_id, "content": m.content, "type": m.type} for m in response]
            except Exception as e:
                print(f"Warning: {e}")
        
        if memory_type:
            return [m for m in self._local_memories if m.get('type') == memory_type]
        return self._local_memories

    def get_memory(self, memory_id: str) -> Optional[dict]:
        """获取单条记忆"""
        if self._hindsight:
            try:
                response = self._hindsight.memory(self.bank_id, memory_id)
                return {
                    "id": response.memory_id,
                    "content": response.content,
                    "type": getattr(response, 'type', 'unknown')
                }
            except Exception as e:
                print(f"Warning: {e}")
        
        for mem in self._local_memories:
            if mem['id'] == memory_id:
                return mem
        return None

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        if self._hindsight:
            try:
                # Hindsight API 可能需要不同的删除方法
                # 这里简化处理
                pass
            except Exception as e:
                print(f"Warning: {e}")
        
        # 本地模式
        for i, mem in enumerate(self._local_memories):
            if mem['id'] == memory_id:
                del self._local_memories[i]
                self._save_local_memories()
                return True
        return False

    def get_stats(self) -> dict:
        """获取记忆统计"""
        local_count = len(self._local_memories)
        
        stats = {
            "mode": "Hindsight" if self._hindsight else "Local",
            "local_memories": local_count,
            "api_url": self.api_url,
            "bank_id": self.bank_id
        }
        
        if self._local_memories:
            # 统计各类型数量
            type_counts = {}
            for mem in self._local_memories:
                t = mem.get('type', 'unknown')
                type_counts[t] = type_counts.get(t, 0) + 1
            stats["type_distribution"] = type_counts
        
        return stats

    def clear_all(self) -> bool:
        """清空所有记忆"""
        if self._hindsight:
            try:
                # 删除并重建记忆库
                self._hindsight.delete_bank(self.bank_id)
                self._ensure_bank()
            except Exception as e:
                print(f"Warning: {e}")
        
        self._local_memories = []
        self._save_local_memories()
        return True


# ==================== 便捷函数 ====================

def create_memory_system(**kwargs) -> MemorySystem:
    """创建记忆系统的便捷函数"""
    return MemorySystem(**kwargs)


# ==================== 示例用法 ====================

if __name__ == "__main__":
    print("=== lan-memory (Hindsight Edition) 测试 ===\n")
    
    # 创建记忆系统 (本地模式，用于演示)
    memory = MemorySystem(local_mode=True)
    
    # Retain: 存储各种类型的记忆
    print("\n--- Retain 测试 ---")
    
    # 存储事实
    memory.retain_fact("Hindsight 是一个 Agent 记忆系统")
    
    # 存储体验
    memory.retain_experience("用户让我帮他下载并安装 Hindsight")
    
    # 存储洞察
    memory.retain_insight("用户倾向于使用中文交流")
    
    # 存储带标签的记忆
    memory.retain(
        "用户正在学习 AI 编程",
        tags=["AI", "学习", "用户偏好"]
    )
    
    # Recall: 搜索记忆
    print("\n--- Recall 测试 ---")
    results = memory.recall("Hindsight")
    print(f"搜索 'Hindsight' 结果: {len(results)} 条")
    for r in results:
        print(f"  [{r['score']:.2f}] {r['content']}")
    
    results = memory.recall("用户")
    print(f"\n搜索 '用户' 结果: {len(results)} 条")
    for r in results:
        print(f"  [{r['score']:.2f}] {r['content']}")
    
    # Reflect: 反思生成
    print("\n--- Reflect 测试 ---")
    reflection = memory.reflect("用户偏好和习惯")
    print(f"反思结果:\n{reflection}")
    
    # 统计
    print("\n--- 统计 ---")
    stats = memory.get_stats()
    print(f"当前模式: {stats['mode']}")
    print(f"记忆数量: {stats['local_memories']}")
    print(f"类型分布: {stats.get('type_distribution', {})}")
    
    print("\n=== 测试完成 ===")
