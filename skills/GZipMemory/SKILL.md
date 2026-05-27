# GZipMemory Skill

> 记忆归档技能：自动将 30 天前的日志压缩归档，并支持在需要时检索调用。专为 OpenClaw Agent 设计，实现跨天记忆完整调用。

## 核心功能

1. **归档**：`archive_old_logs()` - 将 30 天前的日志 gzip 压缩移入 `memory/archive/YYYY/`
4. **读取**：`read_date()` - 按需解压读取指定日期的日志（自动检测 archive）
5. **统一搜索**：`search_memory.py` - 搜索 MEMORY.md + memory/*.md + memory/archive/*.gz

## 文件结构

```
GZipMemory/
├── SKILL.md            # 本文档
├── archiver.py         # 核心归档模块（压缩+移动+检索+增量状态）
├── search_tool.py     # 搜索工具（集成用）
├── search_memory.py   # 统一搜索入口
├── cli.py              # CLI 入口
├── crontab.txt         # cron 配置
└── logs/               # 日志目录
```

## 使用方式

### Python API

```python
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/GZipMemory')

from archiver import MemoryArchiver

archiver = MemoryArchiver()

# 归档旧日志（首次全量，第二次增量）
archiver.archive_old_logs(days=30)

# 搜索归档
results = archiver.search("关键词", year=2026)

# 读取指定日期（自动检测 archive）
content = archiver.read_date("2026-03-15")
```

### AGENTS.md 集成（新会话启动）

```python
# 新会话自动加载昨天完整日志
import sys
sys.path.insert(0, '~/.openclaw/workspace/skills/GZipMemory')
from archiver import MemoryArchiver
import datetime

yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
archiver = MemoryArchiver()
yesterday_log = archiver.read_date(yesterday)  # auto-detects archive
```

### 命令行

```bash
# 归档旧日志
python3 cli.py archive --days 30

# 搜索归档
python3 cli.py search "关键词" --year 2026

# 统一搜索（推荐）
python3 search_memory.py "小卡" 60

# 查看统计
python3 cli.py stats
```

## 归档策略

- **阈值**：30 天前的日志
- **压缩**：gzip（.gz），压缩率 ~50%（实际测试）
- **安全删除**：先复制到 archive，验证成功后再删除原始文件
- **目录结构**：`memory/archive/YYYY/YYYY-MM-DD.md.gz`
- **增量归档**：通过检查 archive 目录中是否已存在对应文件来判断是否需要归档，避免重复处理

## Cron 配置

```bash
28 3 * * * cd ~/.openclaw/workspace/skills/GZipMemory && python3 cli.py archive --days 30
```

## 验证状态

| 测试 | 状态 |
|------|------|
| 归档 30 天前日志 | ✅ 25 个文件已归档 |
| 增量归档跳过 | ✅ 第二次 0 文件 |
| 压缩率 | ✅ 4.8KB → 2.5KB (47%) |
| 统一搜索 "小卡" 60天 | ✅ 找到 6 条结果 |
| 读取归档日志 | ✅ 自动检测并解压 |
| AGENTS.md 集成 | ✅ Session Startup 已更新 |
| 代码质量（ruff/mypy） | ✅ 通过 |

## 与 OpenClaw 协作

```
OpenClaw 3:00 AM  →  Memory Dreaming Promotion（提炼记忆到 MEMORY.md）
OpenClaw 3:28 AM  →  GZipMemory Archive（归档 30 天前日志）
新会话启动        →  自动加载昨天完整日志（gz_read_date）
```

---

**作者**: zheng960121-oss  
**协议**: MIT
