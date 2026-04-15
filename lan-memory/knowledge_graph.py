"""
KnowledgeGraph - 知识图谱模块
用于 lan memory 的实体关系存储和查询
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

# 尝试导入 jieba 用于实体抽取
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    print("Warning: jieba not installed, entity extraction will be less accurate")

GRAPH_FILE = str(Path(__file__).parent / "knowledge_graph.json")

class KnowledgeGraph:
    """
    轻量级知识图谱
    
    数据结构:
    {
        "实体": {
            "关系": ["关联实体1", "关联实体2"],
            ...
        }
    }
    
    例如:
    {
        "小兰": {
            "喜欢": ["Python", "编程"],
            "擅长": ["写作", "AI"],
            "类型": "人"
        },
        "Python": {
            "是": ["编程语言"],
            "用于": ["Web开发", "AI"]
        }
    }
    """
    
    def __init__(self):
        """初始化知识图谱"""
        self.graph = self._load_graph()
        print(f"KnowledgeGraph initialized. Loaded {len(self.graph)} entities.")
    
    def _load_graph(self) -> Dict:
        """从文件加载知识图谱"""
        if os.path.exists(GRAPH_FILE):
            try:
                with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                print("Warning: Could not decode graph file. Starting with empty graph.")
                return {}
        return {}
    
    def _save_graph(self):
        """保存知识图谱到文件"""
        with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.graph, f, indent=4, ensure_ascii=False)
        print(f"KnowledgeGraph saved to {GRAPH_FILE}")
    
    def _extract_entities(self, text: str) -> Set[str]:
        """从文本中提取实体（使用jieba分词）"""
        entities = set()
        
        # 使用jieba分词
        if JIEBA_AVAILABLE:
            words = jieba.cut(text)
        else:
            # 没有jieba时的简单分词（按标点和空格分割）
            words = re.split(r'[\s，、，。！？]', text)
        
        # 停用词
        stopwords = {'的', '是', '在', '了', '和', '与', '对', '也', '有', '我', '你', '他', '她', '它', '我们', '你们', '他们', '她们', '一个', '这个', '那个', '什么', '怎么', '为什么'}
        
        # 过滤停用词和短词
        for word in words:
            word = word.strip()
            if len(word) >= 2 and word not in stopwords:
                # 检查是否是有效实体（包含中文或英文）
                if re.search(r'[\u4e00-\u9fa5a-zA-Z]', word):
                    entities.add(word)
        
        return entities
    
    def _infer_relations(self, text: str) -> List[Tuple[str, str, str]]:
        """
        从文本中推断关系（基于jieba分词）
        返回: [(实体1, 关系, 实体2), ...]
        """
        relations = []
        
        # 使用jieba分词
        if JIEBA_AVAILABLE:
            words = list(jieba.cut(text))
        else:
            words = text.split()
        
        # 关系词及其对应关系
        relation_words = {
            '喜欢': '喜欢',
            '擅长': '擅长', 
            '是': '是',
            '在': '在',
            '有': '有',
            '用于': '用于',
            '属于': '属于',
            '和': '和',  # A和B -> 同事关系
            '一起': '一起',
            '研究': '研究',
            '开发': '开发',
            '学习': '学习',
        }
        
        # 遍历分词结果，找关系
        for i, word in enumerate(words):
            if word in relation_words and i > 0 and i < len(words) - 1:
                relation = relation_words[word]
                entity1 = words[i-1].strip()
                entity2 = words[i+1].strip() if i + 1 < len(words) else None
                
                # 过滤短词和停用词
                stopwords = {'的', '了', '很', '也', '都', '就', '和', '与', '对', '有', '一个'}
                
                if entity1 and len(entity1) >= 1 and entity1 not in stopwords:
                    if entity2 and len(entity2) >= 1 and entity2 not in stopwords:
                        relations.append((entity1, relation, entity2))
                        
                        # 如果是"和"关系，同时添加双向关系
                        if relation == '和':
                            relations.append((entity2, '和', entity1))
        
        return relations
        
        for pattern, relation in relation_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                entity1, entity2 = match.groups()
                relations.append((entity1, relation, entity2))
        
        return relations
    
    def add_memory(self, text: str):
        """
        从记忆文本中提取知识并添加到图谱
        """
        # 1. 提取实体
        entities = self._extract_entities(text)
        
        # 2. 推断关系
        relations = self._infer_relations(text)
        
        # 3. 添加实体到图谱
        for entity in entities:
            if entity not in self.graph:
                self.graph[entity] = {"类型": "实体"}
        
        # 4. 添加关系到图谱
        for entity1, relation, entity2 in relations:
            # 确保实体存在（如果不在entities里）
            if entity1 not in self.graph:
                self.graph[entity1] = {"类型": "实体"}
            if entity2 not in self.graph:
                self.graph[entity2] = {"类型": "实体"}
            
            # 添加关系
            if relation not in self.graph[entity1]:
                self.graph[entity1][relation] = []
            if entity2 not in self.graph[entity1][relation]:
                self.graph[entity1][relation].append(entity2)
            
            # 添加反向关系
            reverse_relation = f"被{relation}"
            if reverse_relation not in self.graph[entity2]:
                self.graph[entity2][reverse_relation] = []
            if entity1 not in self.graph[entity2][reverse_relation]:
                self.graph[entity2][reverse_relation].append(entity1)
        
        # 5. 如果没有显式关系，添加共现关系
        if not relations and len(entities) > 1:
            # 同一句话中出现的实体，记录为"相关"
            entity_list = list(entities)
            for i in range(len(entity_list)):
                for j in range(i + 1, len(entity_list)):
                    e1, e2 = entity_list[i], entity_list[j]
                    if "相关" not in self.graph[e1]:
                        self.graph[e1]["相关"] = []
                    if e2 not in self.graph[e1]["相关"]:
                        self.graph[e1]["相关"].append(e2)
                    if "相关" not in self.graph[e2]:
                        self.graph[e2]["相关"] = []
                    if e1 not in self.graph[e2]["相关"]:
                        self.graph[e2]["相关"].append(e1)
        
        # 6. 保存
        self._save_graph()
        
        print(f"Added {len(entities)} entities and {len(relations)} relations to knowledge graph.")
    
    def query_entity(self, entity: str) -> Optional[Dict]:
        """
        查询实体的所有信息和关系
        """
        return self.graph.get(entity)
    
    def query_relation(self, entity1: str, entity2: str) -> List[str]:
        """
        查询两个实体之间的关系
        """
        relations = []
        if entity1 not in self.graph:
            return relations
        
        for relation, targets in self.graph[entity1].items():
            if entity2 in targets:
                relations.append(relation)
        
        return relations
    
    def query_path(self, start: str, end: str, max_depth: int = 3) -> List[List[str]]:
        """
        查找两个实体之间的路径（广度优先）
        """
        if start not in self.graph or end not in self.graph:
            return []
        
        # BFS
        queue = [(start, [start])]
        visited = {start}
        
        while queue:
            current, path = queue.pop(0)
            
            if len(path) > max_depth:
                continue
            
            if current == end:
                return [path]
            
            if current in self.graph:
                for relation, targets in self.graph[current].items():
                    if relation == "类型":  # 跳过类型属性
                        continue
                    for target in targets:
                        if target not in visited:
                            visited.add(target)
                            queue.append((target, path + [target]))
        
        return []
    
    def get_related_entities(self, entity: str, depth: int = 1) -> Dict[str, List[str]]:
        """
        获取实体相关的所有实体（指定深度）
        """
        if entity not in self.graph:
            return {}
        
        related = {}
        self._dfs_related(entity, depth, related, set())
        return related
    
    def _dfs_related(self, entity: str, depth: int, result: Dict, visited: Set):
        """深度优先搜索相关实体"""
        if depth == 0 or entity in visited:
            return
        
        visited.add(entity)
        
        if entity not in self.graph:
            return
        
        for relation, targets in self.graph[entity].items():
            if relation == "类型":
                continue
            if relation not in result:
                result[relation] = []
            for target in targets:
                if target not in result[relation]:
                    result[relation].append(target)
                self._dfs_related(target, depth - 1, result, visited)
    
    def get_all_entities(self) -> List[str]:
        """获取所有实体"""
        return list(self.graph.keys())
    
    def get_stats(self) -> Dict:
        """获取图谱统计信息"""
        total_entities = len(self.graph)
        total_relations = sum(
            len([r for r in attrs.keys() if r != "类型"])
            for attrs in self.graph.values()
        )
        
        # 统计关系类型
        relation_types = {}
        for entity, attrs in self.graph.items():
            for relation in attrs.keys():
                if relation != "类型":
                    relation_types[relation] = relation_types.get(relation, 0) + 1
        
        return {
            "总实体数": total_entities,
            "总关系数": total_relations,
            "关系类型": relation_types
        }


# --- 示例用法 ---
if __name__ == "__main__":
    # 初始化
    kg = KnowledgeGraph()
    
    # 添加一些记忆
    print("\n=== 添加记忆到知识图谱 ===")
    kg.add_memory("小兰喜欢Python编程，对Web开发很感兴趣")
    kg.add_memory("小兰擅长AI和机器学习，对深度学习有研究")
    kg.add_memory("Python是一种编程语言，广泛用于Web开发和数据分析")
    kg.add_memory("小兰和老大是团队成员，一起工作")
    
    # 查询统计
    print("\n=== 图谱统计 ===")
    stats = kg.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    # 查询实体
    print("\n=== 查询小兰 ===")
    xiaolan = kg.query_entity("小兰")
    print(f"  小兰的信息: {xiaolan}")
    
    # 查询关系
    print("\n=== 查询小兰和Python的关系 ===")
    relations = kg.query_relation("小兰", "Python")
    print(f"  关系: {relations}")
    
    # 查找路径
    print("\n=== 查找小兰到深度学习的路径 ===")
    paths = kg.query_path("小兰", "深度学习")
    print(f"  路径: {paths}")
    
    # 获取相关实体
    print("\n=== 获取小兰的一度关联 ===")
    related = kg.get_related_entities("小兰")
    for relation, entities in related.items():
        print(f"  {relation}: {entities}")
