# LAN Memory Skill

## 📚 Description
This skill enhances the assistant's memory by implementing a lightweight Retrieval-Augmented Generation (RAG) system focused on retaining and recalling contextual information discussed previously. It aims to provide the system with 'memory' that can be queried contextually, improving conversation depth without requiring a complex, external vector database.

## ✨ Functionality
The `lan memory` module provides the following core functionalities:
1.  **`add_memory(text)`**: Stores new pieces of information (memories) into the system's memory bank.
2.  **`search_memory(query, k=3)`**: Searches the stored memories using simple textual matching and a scoring mechanism (mimicking TF-IDF or keyword relevance) to find the top `k` most relevant memories for a given `query`.
3.  **`get_context(query)`**: Orchestrates the process by querying the memory bank and combining the results into an enhanced context string suitable for prompting the LLM.

## 🛠️ Usage Instructions
To use this skill, you must first ensure the required dependencies are installed:
1.  **Install Dependencies**:
    ```bash
    pip install -r ./requirements.txt
    ```
2.  **Run the Script**: The core logic resides in `memory.py`. You can interact with it by calling the functions:
    ```python
    from lan_memory.memory import MemorySystem
    
    # Initialize the memory system (it handles loading/saving)
    memory_system = MemorySystem() 
    
    # 1. Add memory
    memory_system.add_memory("小兰最近对Python编程非常感兴趣，尤其是在Web框架方面。")
    
    # 2. Search memory
    search_results = memory_system.search_memory("她对什么编程感兴趣？", k=1)
    print(f"Search Results: {search_results}")
    
    # 3. Get context for LLM
    context = memory_system.get_context("关于她的兴趣点", query="什么话题需要上下文支持?")
    print(f"\n--- Generated Context ---\n{context}")
    ```
