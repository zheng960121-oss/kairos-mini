# KAIROS-mini 2.0 重新设计方案

## 一、真实 KAIROS 架构分析

### 1.1 KAIROS 如何实现常驻

**关键发现（来自 state.ts）：**
- `kairosActive: boolean` — KAIROS 模式总开关
- `userMsgOptIn: boolean` — 用户主动 opt-in（非默认开启）
- `sessionCronTasks: SessionCronTask[]` — Session 级别 Cron 任务（内存态，不写磁盘）
- `scheduledTasksEnabled: boolean` — 控制是否监听 `.claude/scheduled_tasks.json`
- `sessionPersistenceDisabled: boolean` — 可禁用餐台持久化
- `isRemoteMode: boolean` — 远程模式标志
- 通过 `switchSession()` / `regenerateSessionId()` 实现会话切换
- 通过 `sessionSwitched` Signal 实现会话切换回调（解耦）

**常驻不是靠"守护进程"实现，而是靠：**
- 单一长进程 + 会话制（不是每次任务开新进程）
- Signal 处理保证优雅退出
- atexit 清理
- PID 文件供外部检测

### 1.2 KAIROS 心跳 Tick 实现

**关键发现（来自 state.ts 中的 sessionCronTasks）：**
```typescript
export type SessionCronTask = {
  id: string
  cron: string
  prompt: string
  createdAt: number
  recurring?: boolean
  agentId?: string  // 指明发给哪个 subagent
}
```
- **不是固定 interval timer**，而是 cron 表达式（支持多任务调度）
- 任务路由到特定 agent 的 `pendingUserMessages` 队列（内存队列）
- SessionCronTasks 只在内存中，进程退出即消失
- 真正的定时任务写 `.claude/scheduled_tasks.json`（持久化）

**关键区别：KAIROS Tick 是调度器，不是固定心跳！**

### 1.3 KAIROS 记忆系统（memdir.ts）

**关键发现：**
- 不是"三层 JSON 存储"，而是**文件系统记忆目录**
- 每个记忆一个 Markdown 文件，带 frontmatter 元数据
- `MEMORY.md` 是索引（每行一个链接），**不是存储**
- **KAIROS 模式特殊**：使用 append-only daily log（`logs/YYYY/MM/YYYY-MM-DD.md`）
  - 新记忆直接追加到今日日志文件
  - 夜间 distill 进程把日志提炼到 MEMORY.md + topic 文件
  - 这样不需要每次重写整个 MEMORY.md
- 支持跨会话记忆召回（通过 claudemd.ts 加载到 context）
- 支持 `invokedSkills` 跨 compaction 保留（compaction 时 skill 内容不丢失）

### 1.4 KAIROS 进程管理

**关键发现（来自 state.ts）：**
- 没有独立 daemon 进程
- 只有一个 Claude Code 主进程
- 进程管理通过 Signal + atexit
- PID 文件 + sessionSwitched Signal 做会话同步
- `/resume` 通过 `switchSession()` 恢复会话

### 1.5 BriefTool（真正的主动推送机制）

**关键发现：**
- BriefTool = `SendUserMessage` 的封装
- 通过 `status: 'proactive'` 区分主动推送 vs 被动回复
- 推送到用户可见的消息流（不是文件队列）
- `isBriefEnabled()` 依赖 `kairosActive || userMsgOptIn` 双门槛
- 有 `status: 'proactive'` 的 BriefTool 调用会触发飞书/终端通知

---

## 二、现有 kairos-mini 差距分析

### 2.1 架构层面

| 维度 | KAIROS（真） | kairos-mini（现有） | 差距 |
|------|------------|------------------|------|
| 常驻方式 | 单一长进程 + 会话制 | fork() 后台模式 + watchdog 守护 | 脆弱，fork 不等于 daemon |
| 心跳机制 | cron 表达式调度器 | 固定 interval timer | 无法多任务灵活调度 |
| 记忆系统 | 文件系统 + daily append log | 三层 JSON 存储 | 无 context 集成，AI 无法自然读写 |
| 推送机制 | BriefTool → 消息流 | 文件队列 → 小兰轮询 | 延迟高，不可靠 |
| 任务系统 | SessionCronTasks（内存）+ scheduled_tasks.json（持久化） | queue.json 文件轮询 | 无内存任务，无 cron 能力 |
| 会话管理 | switchSession() + Signal | 无 | 无法恢复状态 |
| 状态管理 | 全局 State 单例 + getter/setter | 分散的模块 | 无统一状态抽象 |

### 2.2 核心缺陷

1. **Watchdog 双进程模型脆弱**：fork 出来的 watchdog 和 main 进程相互依赖，信号处理复杂，资源消耗大
2. **Tick 是轮询而非调度**：固定 5 分钟 tick，任务无法在精确时间执行
3. **记忆无法被 AI 使用**：JSON 文件对 AI 不可读，AI 无法自然地增删记忆
4. **推送延迟高**：文件队列 → 小兰轮询，延迟可能超过 5 分钟
5. **无会话恢复**：进程重启后所有状态丢失
6. **无 compaction**：上下文无限增长，无压缩机制
7. **无 skill 持久化**：每次启动技能要重新加载
8. **任务队列无 cron 支持**：只有立即执行和 scheduled_at 定时，不支持 cron 表达式

---

## 三、KAIROS-mini 2.0 新架构设计

### 3.1 架构 ASCII 图

```
┌─────────────────────────────────────────────────────────────────┐
│                        KAIROS-mini 2.0                           │
│                     单一常驻进程模型                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │  Signal      │   │  Session     │   │  State Manager       │  │
│  │  Handler     │   │  Manager     │   │  (全局状态单例)       │  │
│  │  SIGTERM/INT │◄──│  switchSes  │◄──│  sessionId, cwd,     │  │
│  │  SIGHUP      │   │  regenerate  │   │  kairosActive, opts │  │
│  └──────┬───────┘   └──────┬───────┘   └──────────────────────┘  │
│         │                 │                     ▲               │
│         └────────┬────────┘                     │               │
│                  ▼                             │               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Tick / Cron 调度引擎                         │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐  │  │
│  │  │ CronTab    │  │ TickEngine │  │ SessionCronTasks   │  │  │
│  │  │ (文件调度)  │  │ (fallback) │  │ (内存, ephemeral)   │  │  │
│  │  └────────────┘  └────────────┘  └─────────────────────┘  │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│         ┌───────────────────┼───────────────────────┐          │
│         ▼                   ▼                       ▼          │
│  ┌────────────┐     ┌──────────────┐     ┌────────────────┐     │
│  │ Memory     │     │ Task         │     │ Notifier       │     │
│  │ (memdir)   │     │ Queue        │     │ (BriefTool)    │     │
│  │            │     │              │     │                │     │
│  │ daily-     │     │ CronTab 读   │     │ status=        │     │
│  │ log.md     │     │ → handler    │     │ proactive      │     │
│  │ + distill  │     │ 重试+超时   │     │ → 消息流       │     │
│  │ MEMORY.md  │     │             │     │                │     │
│  └────────────┘     └──────────────┘     └────────────────┘     │
│         │                   │                       │           │
│         └───────────────────┴───────────────────────┘           │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Skill Invoker (技能调用器)                      │  │
│  │  invokedSkills Map — 跨 compaction 保留 skill 内容          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            OpenClaw Gateway (clawflow/HEARTBEAT.md)        │  │
│  │  • HEARTBEAT.md 被主 agent 定期读取                        │  │
│  │  • 小兰通过 Feishu 推送主动消息                            │  │
│  │  • 与主 agent 共享 MEMORY.md / 记忆系统                   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 核心模块设计

#### 模块 1：StateManager（状态管理器）

```python
"""
状态管理器 - 参考 KAIROS state.ts 设计
全局单例，统一状态访问
"""

class StateManager:
    _instance = None
    
    def __init__(self):
        self.session_id = str(uuid.uuid4())[:8]
        self.parent_session_id = None
        self.kairos_active = False
        self.user_opt_in = False
        self.cwd = os.getcwd()
        self.original_cwd = os.getcwd()
        self.start_time = datetime.now()
        self.last_interaction = datetime.now()
        
        # SessionCronTasks (内存, ephemeral)
        self.session_cron_tasks: List[SessionCronTask] = []
        
        # invokedSkills (compaction 保护)
        self.invoked_skills: Dict[str, SkillInfo] = {}
        
        # scheduledTasksEnabled
        self.scheduled_tasks_enabled = False
        
        # Signal callbacks
        self._session_switch_callbacks: List[Callable] = []
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def switch_session(self, new_session_id: str):
        old = self.session_id
        self.session_id = new_session_id
        for cb in self._session_switch_callbacks:
            cb(old, new_session_id)
    
    def on_session_switch(self, callback):
        self._session_switch_callbacks.append(callback)
```

**关键改进**：
- Signal 回调机制（解耦）
- SessionCronTasks（内存任务，不写磁盘）
- invokedSkills 跨 compaction 保留

#### 模块 2：MemDir（文件系统记忆，参考 KAIROS memdir.ts）

```python
"""
记忆系统 - 参考 KAIROS memdir.ts
daily append log + 定期 distill
AI 可直接读写
"""

class MemDir:
    MEMORY_FILE = "MEMORY.md"      # 索引文件
    ENTRYPOINT_LINES_MAX = 200     # 截断行数
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.memory_dir = base_dir / "memory"
        self.log_dir = base_dir / "memory" / "logs"
    
    def today_log_path(self) -> Path:
        """今日日志文件路径：memory/logs/YYYY/MM/YYYY-MM-DD.md"""
        today = datetime.now()
        return self.log_dir / str(today.year) / f"{today.month:02d}" / f"{today.strftime('%Y-%m-%d')}.md"
    
    def append_memory(self, content: str, memory_type: str = "general"):
        """追加到今日日志（append-only）"""
        path = self.today_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] [{memory_type}] {content}\n")
    
    def distill_nightly(self):
        """
        夜间提炼：从 daily logs 提炼到 MEMORY.md
        由 cron 任务调用，每天执行一次
        """
        # 读取最近 N 天的日志
        # 去重 + 按主题分组
        # 写入 MEMORY.md 索引
        # 保留原始日志文件
        pass
    
    def build_memory_prompt(self) -> str:
        """
        构造 AI 系统提示词用的记忆段落
        包含 MEMORY.md 内容 + 目录指引
        """
        pass
    
    def search_memory(self, query: str) -> List[str]:
        """搜索记忆内容（供 AI 调用）"""
        pass
```

**关键改进**：
- Append-only daily log（无需重写大文件）
- AI 可直接读写（Markdown 文件）
- 夜间 distill 保持索引更新
- 支持 `grep` 工具搜索历史

#### 模块 3：CronTab（真正的 cron 调度器）

```python
"""
Cron 调度器 - 参考 KAIROS sessionCronTasks
支持 cron 表达式，不只是固定 interval
"""

import croniter

class CronTab:
    def __init__(self, tasks_file: Path, session_cron_tasks: List):
        self.tasks_file = tasks_file  # .claude/scheduled_tasks.json
        self.session_cron_tasks = session_cron_tasks  # 内存任务
    
    def get_due_tasks(self) -> List[Dict]:
        """返回所有到期任务（包括文件和内存的）"""
        now = datetime.now()
        due = []
        
        # 检查文件任务
        for task in self._read_file_tasks():
            if self._is_due(task, now):
                due.append(task)
        
        # 检查 session 内存任务
        for task in self.session_cron_tasks:
            if self._cron_is_due(task['cron'], now):
                due.append(task)
        
        return due
    
    def _cron_is_due(self, cron_expr: str, now: datetime) -> bool:
        try:
            cron = croniter.croniter(cron_expr, now)
            prev = cron.get_prev(datetime)
            # 上一执行时间距离现在 < interval 则到期
            return (now - prev).total_seconds() < self._tick_interval
        except:
            return False
```

**关键改进**：
- Cron 表达式支持（不只是 interval）
- 文件任务 + 内存任务统一调度
- 精确按时执行

#### 模块 4：Notifier（推送器，参考 BriefTool）

```python
"""
推送器 - 参考 KAIROS BriefTool
status='proactive' 推送到消息流
"""

class Notifier:
    TYPE_NORMAL = "normal"
    TYPE_PROACTIVE = "proactive"  # AI 主动推送
    
    def __init__(self):
        self.pending: List[Notification] = []
    
    def notify(self, content: str, status: str = TYPE_NORMAL,
               channel: str = "feishu") -> str:
        """
        发送通知
        - status=proactive: 立即推送（模拟 BriefTool）
        - status=normal: 加入队列
        """
        notif = Notification(
            content=content,
            status=status,
            channel=channel,
            timestamp=datetime.now().isoformat()
        )
        
        if status == self.TYPE_PROACTIVE:
            # 立即推送（通过 OpenClaw 消息接口）
            self._push_immediately(notif)
        else:
            self.pending.append(notif)
        
        return notif.id
    
    def _push_immediately(self, notif: Notification):
        """立即推送：写入 HEARTBEAT.md 或直接发飞书"""
        # 方案 A: 写 HEARTBEAT.md，触发主 agent 立即处理
        # 方案 B: 直接通过飞书 API 推送
        pass
    
    def tick_notification(self, tick_count: int) -> str:
        """心跳通知（低优先级）"""
        return self.notify(
            f"❤ 心跳 #{tick_count}",
            status=self.TYPE_NORMAL
        )
    
    def proactive_alert(self, content: str) -> str:
        """主动告警（高优先级，立即推送）"""
        return self.notify(content, status=self.TYPE_PROACTIVE)
```

**关键改进**：
- `status=proactive` 立即推送（不是文件队列）
- 区分主动推送 vs 被动通知

#### 模块 5：SkillInvoker（技能调用器）

```python
"""
技能调用器 - 参考 KAIROS invokedSkills
compaction 时保留 skill 内容
"""

class SkillInvoker:
    def __init__(self, state: StateManager):
        self.state = state
        self._skill_cache: Dict[str, SkillInfo] = {}
    
    def invoke(self, skill_name: str, skill_path: str, 
               content: str, agent_id: str = None) -> str:
        """调用技能，内容存入 state（跨 compaction 保留）"""
        key = f"{agent_id or ''}:{skill_name}"
        self.state.invoked_skills[key] = SkillInfo(
            skill_name=skill_name,
            skill_path=skill_path,
            content=content,
            invoked_at=datetime.now().isoformat(),
            agent_id=agent_id
        )
        return key
    
    def get_skill(self, skill_name: str, agent_id: str = None) -> Optional[SkillInfo]:
        """获取已调用的技能（compaction 恢复用）"""
        key = f"{agent_id or ''}:{skill_name}"
        return self.state.invoked_skills.get(key)
    
    def clear_for_agent(self, agent_id: str, preserved_ids: Set[str] = None):
        """清理 agent 的 skill 记录（compaction 时调用）"""
        if not preserved_ids:
            self.state.invoked_skills.clear()
        else:
            for key in list(self.state.invoked_skills.keys()):
                skill = self.state.invoked_skills[key]
                if skill.agent_id == agent_id and skill.agent_id not in preserved_ids:
                    del self.state.invoked_skills[key]
```

**关键改进**：
- Skill 内容跨 compaction 保留
- Agent 级别隔离

#### 模块 6：OpenClaw 集成

```python
"""
OpenClaw 集成 - 与主 agent 共享上下文
"""

class OpenClawIntegration:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.heartbeat_file = workspace / "HEARTBEAT.md"
        self.memory_file = workspace / "memory" / "MEMORY.md"
    
    def write_heartbeat(self, items: List[str]):
        """写 HEARTBEAT.md 供主 agent 读取"""
        content = "\n".join([f"- [ ] {item}" for item in items])
        self.heartbeat_file.write_text(content, encoding="utf-8")
    
    def read_memory(self) -> str:
        """读取记忆内容"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def push_proactive_message(self, content: str):
        """主动推送到飞书（绕过文件队列）"""
        # 通过 OpenClaw 消息接口
        # 或直接飞书 webhook
        pass
```

**关键改进**：
- HEARTBEAT.md 共享主 agent 的心跳上下文
- 记忆文件与主 agent 共用

### 3.3 Tick 引擎（整合版）

```python
class TickEngine:
    """
    心跳引擎 2.0 - 基于 CronTab 调度
    不再是固定 interval，而是事件驱动 + cron 调度
    """
    
    def __init__(self, interval: int = 300):
        self.interval = interval  # fallback tick interval
        self.crontab = CronTab(tasks_file, state.session_cron_tasks)
        self.last_fallback_tick = 0
    
    def run_once(self):
        """单次调度检查（由外部 timer 或 cron 调用）"""
        now = time.time()
        
        # 1. 检查 cron 任务
        due_tasks = self.crontab.get_due_tasks()
        for task in due_tasks:
            self._execute_task(task)
        
        # 2. Fallback: 如果很久没执行，强制 tick
        if now - self.last_fallback_tick >= self.interval:
            self._fallback_tick()
            self.last_fallback_tick = now
    
    def _fallback_tick(self):
        """强制心跳（当没有 cron 任务到期时）"""
        self.state.last_interaction = datetime.now()
        # 执行所有注册的 tick hooks
        for hook in self.tick_hooks:
            hook(self.state.tick_count, self._build_context())
    
    def _build_context(self) -> dict:
        return {
            "state": self.state,
            "memory": self.memory,
            "notifier": self.notifier,
            "skill_invoker": self.skill_invoker,
        }
```

**关键改进**：
- Cron 调度为主，固定 interval 为辅
- 非阻塞：单次 `_tick()` 执行时间可控
- 上下文包含 skill_invoker（compaction 保护）

---

## 四、与 KAIROS 的相似点说明

| KAIROS（源码） | kairos-mini 2.0 | 对应模块 |
|--------------|----------------|---------|
| `state.ts` 全局 State 单例 | `StateManager` 单例 | StateManager |
| `kairosActive` flag | `state.kairos_active` | StateManager |
| `sessionCronTasks[]` 内存任务 | `state.session_cron_tasks[]` | CronTab |
| `switchSession()` + Signal | `state.switch_session()` + callbacks | StateManager |
| `invokedSkills` Map | `SkillInvoker.invoked_skills` | SkillInvoker |
| `memdir.ts` daily append log | `MemDir.today_log_path()` + `append_memory()` | MemDir |
| `BriefTool` status=proactive | `Notifier.TYPE_PROACTIVE` | Notifier |
| `.claude/scheduled_tasks.json` | `tasks.json` | CronTab |
| `atexit` + Signal Handler | `atexit.register()` + Signal Handler | main.py |
| `sessionSwitched` Signal | `on_session_switch()` callbacks | StateManager |

---

## 五、实施路线图

### Phase 1：核心重构（不改变外部接口）
- [ ] 实现 `StateManager` 单例（替换分散的全局变量）
- [ ] 实现 `MemDir`（daily append log，替代 JSON memory）
- [ ] 实现 `CronTab`（替代固定 interval）
- [ ] 实现 `Notifier`（区分 proactive vs normal）
- [ ] 实现 `SkillInvoker`（invokedSkills Map）

### Phase 2：集成 OpenClaw
- [ ] 接入 HEARTBEAT.md（让主 agent 能感知 kairos-mini 状态）
- [ ] 实现 proactive 推送（通过飞书 webhook）
- [ ] 记忆系统与主 agent 共享目录

### Phase 3：可靠性加固
- [ ] 移除 watchdog 双进程模型（改用单进程 + Supervisor/launchd）
- [ ] 实现 compaction 友好的任务状态
- [ ] 实现夜间 distill cron 任务

### Phase 4：高级功能
- [ ] 多 agent 支持（KAIROS 的 team 模式）
- [ ] 远程模式（KAIROS `isRemoteMode`）
- [ ] 遥测集成（KAIROS 的 OpenTelemetry）

---

## 六、关键设计原则（来自 KAIROS 源码）

1. **单进程 > 多进程**：KAIROS 没有 daemon/main.js，靠 Signal + atexit 管理生命周期
2. **append-only > 重写**：daily log 不需要每次更新整个文件
3. **内存任务 > 磁盘任务**：SessionCronTasks 是 ephemeral 的，只在当前会话有效
4. **compaction 感知**：invokedSkills 在 compaction 时被保留
5. **opt-in 门槛**：`kairosActive || userOptIn` 双门槛，不是默认开启
6. **Signal 解耦**：`sessionSwitched` Signal 让状态切换对监听者透明
