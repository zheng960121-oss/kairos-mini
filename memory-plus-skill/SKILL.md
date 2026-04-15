# 技能名称：memory-plus

## 技能描述
本技能旨在增强小兰（Xiao Lan）的记忆能力，核心功能是实现检索增强生成（Retrieval-Augmented Generation, RAG），通过外部知识库检索相关信息，并将检索到的内容增强到后续的生成过程中，从而提供更准确、更具上下文深度的回答。

## 功能说明
**1. 向量存储 (Vector Storage):**
技能底层维护一个向量数据库，用于存储和索引知识库中的所有文档块（Chunks）。这些文档块经过嵌入模型（Embedding Model）转换成高维向量。

**2. 检索 (Retrieval):**
当用户发起查询时，系统首先将查询文本也嵌入成向量，然后计算该查询向量与知识库中所有向量的相似度。通过相似度搜索，召回（Retrieve）与用户问题最相关的前K个知识文本块。

**3. 增强注入 (Enhancement Injection):**
召回的知识文本块不会直接呈现给用户，而是作为“上下文证据”（Context Evidence）被结构化地注入到给大型语言模型（LLM）的Prompt中，指导LLM基于这些证据进行推理和回答，显著减少幻觉（Hallucination）的发生率。

## 使用方法
**调用方式:**
本技能通常作为工作流（Workflow）或特定函数调用（Function Call）的一部分被激活。用户无需关心底层的向量检索过程，只需提出问题即可。

**用户流程示例:**
1. 用户：[提出关于某个特定领域的复杂问题]
2. 系统（自动调用 `memory-plus` 技能）：执行知识检索。
3. 系统：[结合检索到的证据] 回答用户问题。

**关键参数（若适用）:**
*   `query`: 用户提出的原始问题字符串。
*   `k`: 需要检索的证据块数量（可选，默认值）。

## 技术实现细节
**架构组件:**
1.  **知识源（Source Data）:** 外部文档集合。
2.  **嵌入模型（Embedding Model）:** 负责将文本转化为向量（例如：OpenAI Ada, BGE等）。
3.  **向量数据库（Vector DB）:** 存储和高效索引向量数据（如：Pinecone, ChromaDB）。
4.  **核心逻辑:** 负责编排检索流程，包括：
    a. 接收 Query -> b. Embed Query -> c. Vector DB Search (Top K) -> d. Context Construction -> e. LLM Prompt Composition.

**OpenClaw规范兼容性:**
本技能的API接口将严格遵循OpenClaw的`SkillDefinition`标准，确保与其他技能和工具的兼容性与可组合性。输入输出的Schema定义清晰，便于其他模块调用。
