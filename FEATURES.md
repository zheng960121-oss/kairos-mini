# kairos-mini 功能介绍

> 基于 Claude Code KAIROS 架构的轻量级自主代理系统
> 验证日期：2026-04-08

---

## 1. 项目简介

**kairos-mini** 是一个参考 Anthropic Claude Code 泄露源码中的 KAIROS 架构设计的 Python 自主代理系统。核心设计目标是**单进程常驻 + Cron 调度 + 文件系统记忆**。

### 核心特性

- 🧠 **三层记忆系统**：Append-only daily log + 自动 distill + 跨会话记忆
- ⏰ **Cron 调度**：支持标准 5 段式 cron 表达式，不只是固定 interval
- 🔄 **单进程架构**：Signal/atexit 管理生命周期，无复杂 watchdog
- 🔗 **OpenClaw 集成**：通过 `HEARTBEAT.md` 文件和主 Agent 通信
- 🌐 **Web Dashboard**：HTTP 实时状态监控（默认 8080 端口）
- 📡 **双模通知**：Proactive（立即推送）和 Normal（队列）两种通知模式

### 技术栈

- Python 3.12+
- 标准库为主：`signal`、`atexit`、`fcntl`、`threading`、`http.server`
- 无重型依赖：仅 `requirements.txt` 中列出少量依赖

---

## 2. 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         KAIROSmini (main.py)                     │
│  单进程 orchestrator，管理所有模块生命周期，处理 Signal/atexit    │
└──────────┬──────────────┬───────────┬───────────┬────────────────┘
           │              │           │           │
    ┌──────▼──────┐ ┌──────▼──┐ ┌─────▼─────┐ ┌──▼──────────────┐
    │ StateManager│ │  CronTab │ │  MemDir   │ │  OpenClawIntegr. │
    │  单例全局状态│ │ cron调度 │ │ 记忆系统  │ │ HEARTBEAT.md通信 │
    │ +Signal回调 │ │文件+内存 │ │append-only│ │                  │
    └──────┬──────┘ └──────┬──┘ └─────┬─────┘ └──────────────────┘
           │               │           │
    ┌──────▼──────┐ ┌──────▼──┐ ┌─────▼─────┐ ┌──▼──────────────┐
    │  Notifier   │ │TaskQueue │ │  Skill    │ │  web_dashboard  │
    │双模通知推送 │ │ 任务队列  │ │ Invoker   │ │  HTTP :8080     │
    └─────────────┘ └─────────┘ └───────────┘ └──────────────────┘
           │
    ┌──────▼──────────┐
    │  HEARTBEAT.md   │  ← OpenClaw 主 Agent 读取此文件通信
    └─────────────────┘
```

### 模块说明

| 模块 | 文件 | 职责 |
|------|------|------|
| `KAIROSmini` | `main.py` | 主入口，tick 循环，任务编排 |
| `StateManager` | `StateManager.py` | 全局单例状态，Signal 回调，tick hooks |
| `CronTab` | `CronTab.py` | Cron 表达式解析与定时任务调度 |
| `MemDir` | `MemDir.py` | Append-only daily log 记忆系统 |
| `Notifier` | `Notifier.py` | 双模通知推送（proactive/normal） |
| `TaskQueue` | `tasks.py` | 文件持久化任务队列 + 处理器注册 |
| `SkillInvoker` | `SkillInvoker.py` | Skill 执行器 |
| `OpenClawIntegration` | `OpenClawIntegration.py` | HEARTBEAT.md 读写，与 OpenClaw 主 Agent 通信 |
| `web_dashboard` | `web_dashboard.py` | HTTP Dashboard (HTML/JSON) |
| `watchdog` | `watchdog.py` | 可选进程守护，监控主进程健康 |

---

## 3. 核心功能详解

### 3.1 StateManager — 全局状态单例

**设计参考**：KAIROS `state.ts`

```python
from StateManager import StateManager, SessionCronTask

sm = StateManager.get_instance()  # 获取单例
```

**核心属性**：
- `session_id` — 当前会话 ID（UUID 前 8 位）
- `tick_count` — 心跳计数
- `kairos_active` — KAIROS 模式总开关（默认 False）
- `user_opt_in` — 用户主动 opt-in 标志
- `is_remote_mode` — 远程模式标志
- `session_cron_tasks` — 内存中的 Cron 任务列表（Session 级，进程退出消失）
- `invoked_skills` — 已调用 Skill 记录（compaction 保护）

**Signal 回调机制**：
```python
def on_session_switch(callback):
    """注册会话切换回调，接收 (old_session_id, new_session_id)"""

def switch_session(new_id):
    """切换会话，触发所有已注册的回调"""
    sm.switch_session('new-session-id')

def on_tick(callback):
    """注册心跳回调，接收 (tick_count, context_dict)"""

def fire_tick(context):
    """触发所有 tick hooks"""
    sm.fire_tick({'source': 'test'})
```

**实测验证** ✅：
```
session_id=4aa80c83, tick_count=1
switch_session + callback: ['switch:4aa8->new-session-99']
fire_tick: tick_count=1 回调正常触发
```

### 3.2 CronTab — Cron 表达式调度器

**设计参考**：KAIROS `sessionCronTasks`

```python
from CronTab import CronTab
ct = CronTab(tasks_file=Path('.kairos/scheduled_tasks.json'))
```

**支持功能**：
- 标准 5 段式 cron 表达式：`minute hour day month weekday`
- 复杂表达式：`*`, `*/n`, `n-m`, `n,m`, `n-m/n`
- **文件任务**（持久化）和**内存任务**（Session 级）统一调度

**主要方法**：
```python
# 添加文件任务
ct.add_file_task({
    'id': 'task-1',
    'cron': '*/5 * * * *',  # 每5分钟
    'prompt': 'check status',
    'recurring': True,
    'created_at': int(time.time())
})

# 检查到期任务
due_tasks = ct.get_due_tasks(datetime.now())

# 获取下一次执行时间
next_run = ct.get_next_run('*/5 * * * *')

# 列出所有任务
tasks = ct.get_file_tasks()

# 移除任务
ct.remove_file_task('task-1')

# 标记任务已执行
ct.mark_task_run('task-1')
```

**辅助快捷方法**：
```python
ct.every_minute()
ct.every_5_minutes()
ct.every_15_minutes()
ct.every_hour()
ct.daily_at('09:00')
ct.weekly_on('mon')
ct.monthly_on(1)
```

**实测验证** ✅：
```
add_file_task: test-cron-1
get_due_tasks: 0 due (正确识别 */5 只在 0,5,10...分钟触发)
get_next_run: 2026-04-08 06:30:00
remove_file_task: 0 remaining
```

### 3.3 TaskQueue — 文件持久化任务队列

**设计**：文件锁保护 + JSON 持久化 + 处理器注册

```python
from tasks import TaskQueue, TaskPriority
q = TaskQueue()
```

**任务生命周期**：`pending` → `running` → `completed` / `failed`

**主要方法**：
```python
# 添加任务
task = q.add_task(
    name='my_task',
    description='do something',
    priority='normal',   # high/normal/low
    metadata={'key': 'value'},
    scheduled_at=None,   # ISO 时间字符串，None=立即
    timeout=300
)

# 获取待执行任务
pending = q.get_pending_tasks()
next_t = q.get_next_task()

# 状态流转
q.mark_running(task_id)
q.mark_completed(task_id, result='success')
q.mark_failed(task_id, error='something went wrong')
q.cancel_task(task_id)

# 历史与统计
history = q.get_history(limit=10)
stats = q.get_stats()  # {'pending': N, 'running': N, 'completed': N, 'failed': N}
```

**内置任务处理器**（`task_handlers.py` 注册）：
- `write_chapter` / `novel_chapter` — 写小说章节（调用 Ollama 本地模型）
- `ai_task` / `claude_task` — 通用 AI 任务

**实测验证** ✅：
```
add_task: id=task_20260408062824_249
get_pending_tasks: 1
get_next_task: test_task
mark_running/mark_completed: 正常
cancel_task: 正常
get_history: 2 entries
```

### 3.4 Notifier — 双模通知推送

**设计参考**：KAIROS `BriefTool`

```python
from Notifier import Notifier
notif = Notifier(
    queue_file=Path('.kairos/notification_queue.json'),
    heartbeat_file=Path('HEARTBEAT.md')
)
```

**两种通知模式**：

| 模式 | 说明 | 行为 |
|------|------|------|
| `normal` | 普通通知 | 加入队列，等待 `flush()` 批量发送 |
| `proactive` | 主动推送 | 立即调用 dispatcher 发送，绕过队列 |

**使用示例**：
```python
# 普通通知入队
notif.notify('hello', status='normal', channel='console')

# 主动推送（立即送达）
results = []
notif.set_dispatcher(lambda n: results.append(n.id) or True)
notif.notify('urgent!', status='proactive', channel='console')
# results == ['<notif-id>']

# 写入 HEARTBEAT.md（供 OpenClaw 主 Agent 读取）
notif.notify('heartbeat info', status='normal', channel='heartbeat')
```

**实测验证** ✅：
```
notify(normal): id=bbd328b3, pending=1
notify(proactive): id=83e48820, pending=1 (normal和proactive都计入pending)
proactive dispatch: ['7ade915a'] 立即分发
heartbeat: file exists=True
```

### 3.5 MemDir — Append-only Daily Log 记忆系统

**设计参考**：KAIROS `memdir.ts`

```python
from MemDir import MemDir
md = MemDir(base_dir=Path('.'))
```

**记忆存储结构**：
```
memory/
  logs/
    2026/
      04/
        2026-04-08.md   ← 每日追加日志（append-only）
        2026-04-07.md
        ...
  session.json          ← Session 记忆
  project.json          ← 项目记忆
  longterm.json         ← 长期记忆
```

**每日日志格式**（追加，永不重写）：
```markdown
- [2026-04-08 06:28] [general] test memory entry #test
- [2026-04-08 06:29] [heartbeat] 心跳 #10 | 最后交互: 06:29
- [2026-04-08 10:00] [task] [Cron Task] check email
```

**主要方法**：
```python
# 追加记忆（append-only，永不修改旧内容）
md.append_memory('content here', memory_type='general', tags=['tag1', 'tag2'])

# 读取今日日志
log = md.read_today_log()

# 搜索记忆（全文搜索）
results = md.search_memory('keyword')

# 读取最近 N 天日志
recent = md.read_recent_logs(days=7)  # Dict[datetime, str]

# 夜间 distill（提炼日志到索引）
md.distill_nightly(force=False)
```

**实测验证** ✅：
```
append_memory: 写入 55 字符
read_today_log: 55 chars, 内容: '- [2026-04-08 06:28] [general] test memory entry #test\n'
search_memory: 找到 1 条结果
```

### 3.6 SkillInvoker — Skill 执行器

```python
from SkillInvoker import SkillInvoker
invoker = SkillInvoker(state_manager)
```

负责注册和调用 OpenClaw Skills，支持主动注入上下文。

### 3.7 OpenClawIntegration — OpenClaw 主 Agent 通信

```python
from OpenClawIntegration import OpenClawIntegration
oi = OpenClawIntegration(workspace)
```

通过文件机制和 OpenClaw 主 Agent 通信：
- 读取 `HEARTBEAT.md` 了解主 Agent 指令
- 写入通知到 `HEARTBEAT.md` 反馈执行结果

### 3.8 Web Dashboard — HTTP 状态面板

```python
from web_dashboard import DashboardServer, DashboardData
```

默认端口 8080，提供：
- `/` — HTML 状态面板（深色主题）
- `/api/status` — JSON 状态数据

---

## 4. 命令行用法

### 4.1 启动参数

```bash
# 前台运行（测试用）
python main.py --workspace ~

# 后台常驻
python main.py --start --workspace ~

# 单次执行（不驻留）
python main.py --run-once --workspace ~

# 停止后台进程
python main.py --stop --workspace ~

# 启动并打开 Web Dashboard
python main.py --dashboard --workspace ~

# 添加定时任务
python main.py --add-task "*/5 * * * *:检查系统状态" --workspace ~

# 列出所有任务
python main.py --list-tasks --workspace ~

# 指定 tick 间隔（秒）
python main.py --start --workspace ~ --tick-interval 600
```

### 4.2 工作目录结构

运行后会创建以下目录结构：
```
~/.kairos/
  config.json          # 用户配置
  state.json           # 状态快照
  scheduled_tasks.json # 定时任务（持久化）
  notification_queue.json  # 通知队列
  kairos.pid           # PID 文件
  kairos.lock          # 文件锁
  heartbeat.txt        # Watchdog 心跳
```

---

## 5. Tick 引擎（Heartbeat Loop）

Tick 是 kairos-mini 的主循环，每个 tick 执行：

```
_tick_loop (每 60 秒迭代一次):
  1. 检查 CronTab.get_due_tasks() → 执行到期任务
  2. 检查 TaskQueue → 执行待处理任务
  3. 每 3 个 tick 持久化状态到 .kairos/state.json
  4. 每 10 个 tick 追加记忆到日志
  5. 触发所有 StateManager.tick_hooks
  6. 更新 HEARTBEAT.md
```

**强制 fallback tick**（无任务到期时，按 `tick_interval` 强制执行）：
- 默认 900 秒（15 分钟）
- 保证即使没有 cron 任务，系统也会定期活跃

---

## 6. 配置文件格式

### 6.1 定时任务 (scheduled_tasks.json)

```json
[
  {
    "id": "task-001",
    "cron": "*/5 * * * *",
    "prompt": "检查邮件",
    "recurring": true,
    "created_at": 1744089600,
    "last_run": 0
  }
]
```

### 6.2 状态快照 (state.json)

```json
{
  "session_id": "cb7e21d0",
  "parent_session_id": null,
  "kairos_active": true,
  "user_opt_in": false,
  "cwd": "/Users/jk/Desktop/11/kairos-mini",
  "start_time": "2026-04-08T06:00:00",
  "last_interaction": "2026-04-08T06:30:00",
  "tick_count": 47,
  "is_remote_mode": false,
  "scheduled_tasks_enabled": true
}
```

### 6.3 通知队列 (notification_queue.json)

```json
[
  {
    "id": "eacf4359",
    "content": "任务完成通知",
    "status": "normal",
    "channel": "console",
    "timestamp": "2026-04-08T06:28:00",
    "title": null,
    "metadata": null
  }
]
```

---

## 7. 任务类型

### 7.1 内置任务类型

| 任务名 | 说明 | 执行器 |
|--------|------|--------|
| `write_chapter` / `novel_chapter` | 写小说章节 | Ollama (gemma4) |
| `ai_task` / `claude_task` | 通用 AI 任务 | Ollama |
| 任意字符串 | 追加到记忆作为待办 | `memdir.append_memory()` |

### 7.2 自定义任务

通过 `TaskQueue.register_handler()` 注册自定义处理器：

```python
from tasks import TaskQueue

def my_handler(task: Task) -> str:
    return f"处理了: {task.description}"

q = TaskQueue()
q.register_handler('my_custom_task', my_handler)
q.add_task('my_custom_task', description='hello')
```

---

## 8. 已知 Limitations

1. **单机器单实例**：依赖文件锁防止多实例，不支持分布式部署
2. **Session Cron 任务不持久化**：`session_cron_tasks` 在内存中，进程重启丢失
3. **Ollama 硬编码依赖**：`task_handlers` 默认连接 `http://localhost:11434`，Ollama 不可用时 AI 任务会失败
4. **无 WebSocket**：Dashboard 使用轮询，非真正实时推送
5. **Python 3.12+**：依赖 `copy Kathy` 等较新特性（测试于 3.14）
6. **CronTab 为内存+文件混合**：SessionCronTasks 在内存，FileTasks 在磁盘，需要 `save_tasks_to_file()` 手动持久化新增的文件任务（`add_file_task` 会自动写文件）
7. **飞书通知需要配置 webhook**：Notifier 支持 `feishu` channel 但需要预先配置 `_feishu_webhook`
8. **WatchDog 是可选模块**：默认 main.py 不自动启动 WatchDog，需要单独启动 `watchdog.py`

---

## 9. 验证结果摘要

| 测试项 | 结果 | 备注 |
|--------|------|------|
| 核心模块导入 | ✅ | StateManager, MemDir, CronTab, Notifier, TaskQueue, SkillInvoker, OpenClawIntegration |
| TaskQueue 添加/执行/完成 | ✅ | 生命周期正常 |
| TaskQueue 取消任务 | ✅ | pending→cancelled |
| CronTab 添加文件任务 | ✅ | cron=`*/5 * * * *` |
| CronTab 到期检查 | ✅ | get_due_tasks 正确返回 |
| CronTab 下次执行时间 | ✅ | get_next_run 返回正确时间 |
| CronTab 移除任务 | ✅ | 文件同步删除 |
| StateManager Signal 回调 | ✅ | session switch 触发回调 |
| StateManager tick hooks | ✅ | fire_tick 触发所有 hooks |
| Notifier normal 入队 | ✅ | pending 列表正常 |
| Notifier proactive 立即分发 | ✅ | dispatcher 同步调用 |
| Notifier heartbeat 通道 | ✅ | 文件正常创建 |
| MemDir append memory | ✅ | append-only 写入 |
| MemDir search | ✅ | 全文搜索正常 |
| 整体 tick 模拟 | ✅ | tick_count 递增，hooks 触发 |
