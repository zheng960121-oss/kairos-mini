# KAIROS-mini

轻量级主动助手心跳引擎 - 小兰背后的心跳系统

支持**长期无人值守运行**，具备完善的崩溃恢复、故障报警、文件锁保护机制。

---

## 功能特性

### P0 核心功能

1. **Tick Engine（心跳引擎）**
   - 每隔5分钟触发一次检查（可配置）
   - 单次心跳超时控制（60s），防止阻塞
   - 心跳时间戳文件（供 watchdog 监控）
   - SIGTERM/SIGINT/SIGHUP 信号处理
   - atexit 退出清理

2. **Memory Bus（三层记忆）**
   - Project Memory：项目基本信息
   - Session Memory：当前会话状态
   - Long-term Memory：跨会话重要信息
   - **文件锁保护**（fcntl.flock），防止多进程写坏数据

3. **Notifier（主动推送）**
   - 发现重要事件写入通知文件
   - 支持高优先级通知
   - **文件锁保护**
   - 供小兰读取推送

4. **Task Queue（任务队列）**
   - 从文件读取待执行任务
   - 支持任务重试（默认3次）
   - **scheduled_at 定时任务**（真正按时间执行）
   - **任务超时控制**（默认300s）
   - **连续失败报警**（连续3次失败后通知）
   - **文件锁保护**

### P1 可靠性功能

5. **Watchdog（进程守护）**
   - 独立进程监控主进程健康
   - 异常退出后自动重启
   - 心跳超时检测（15分钟无心跳视为僵死）
   - 连续重启失败报警
   - 最小重启间隔保护（60s 防抖）

6. **Logger（统一日志）**
   - 文件滚动日志（5MB/文件，保留3个备份）
   - 错误日志单独记录
   - 控制台彩色输出
   - 分级日志（DBG/INF/WRN/ERR/CRT）

7. **健康检查**
   - 每30次心跳输出状态摘要
   - 高优先级通知即时提醒

---

## 目录结构

```
kairos-mini/
├── main.py              # 入口文件
├── tick_engine.py       # 心跳主循环
├── memory.py            # 记忆系统（文件锁保护）
├── notifier.py          # 推送模块（文件锁保护）
├── tasks.py             # 任务队列（文件锁、定时、超时、连续失败报警）
├── logger.py            # 统一日志系统
├── watchdog.py          # 进程守护
├── memory/              # 记忆存储
│   ├── project.json
│   ├── session.json
│   └── longterm.json
├── notifications/       # 通知队列（供小兰读取）
│   ├── queue.json
│   └── sent.json
├── tasks/               # 任务存储
│   ├── queue.json
│   ├── history.json
│   └── failure_count.json
├── run/                 # 运行时文件（PID、心跳）
│   ├── kairos-main.pid
│   └── heartbeat.txt
└── logs/                # 日志文件
    ├── kairos-mini.log
    └── errors.log
```

---

## 快速开始

### 安装依赖

```bash
pip install psutil  # 可选，用于系统健康检查
```

### 启动（推荐用 watchdog）

```bash
# 安装 watchdog（守护进程模式）
python watchdog.py &

# 或前台运行（调试用）
python main.py

# 指定间隔（60秒）
python main.py -i 60
```

### 命令行操作

```bash
# 查看状态
python main.py --status

# 查看通知队列
python main.py --notifications

# 查看任务队列
python main.py --tasks

# 添加立即执行的任务
python main.py --add-task notify "测试任务" normal

# 添加定时任务（ISO格式时间）
python main.py --add-task notify "喝水提醒" normal "2026-04-02T14:00:00"

# 查看任务历史
python main.py --history

# 发送测试通知
python main.py --test-notification

# 手动触发心跳
python main.py --trigger-tick

# 清空通知队列
python main.py --clear-notifications

# 检查 watchdog 守护的主进程状态
python watchdog.py --check
```

---

## 与小兰的接口

通知文件保存在 `notifications/queue.json`，小兰可以：

1. 定期读取 `queue.json`
2. 处理通知后调用 `mark_sent(id)` 标记已发送
3. 推送给老大

---

## 定时任务

`scheduled_at` 参数支持 ISO 格式时间字符串：

```python
# 添加一个 10 分钟后执行的任务
task_queue.add_task(
    name="remind_drink",
    description="喝水提醒",
    priority="normal",
    scheduled_at="2026-04-02T18:00:00"
)
```

未到执行时间的任务会自动跳过，不会阻塞其他任务。

---

## 崩溃恢复

```
┌─────────────────────────────────────────────┐
│              watchdog.py                     │
│   每 60s 检查：                              │
│   1. 主进程是否存活                          │
│   2. heartbeat.txt 是否 15 分钟内更新       │
│   → 异常则自动重启                            │
│   → 连续 3 次重启失败 → 报警通知             │
└─────────────────────────────────────────────┘
          ↓ 监控 ↓
┌─────────────────────────────────────────────┐
│              main.py (KAIROS-mini)           │
│   每心跳更新 heartbeat.txt                   │
│   SIGTERM/SIGINT → 优雅退出 + atexit 清理    │
└─────────────────────────────────────────────┘
```

---

## 扩展开发

### 注册任务处理器

```python
from tasks import get_task_queue

def my_task_handler(task):
    print(f"执行任务: {task.name}")
    return "任务完成"

tq = get_task_queue()
tq.register_handler("my_task", my_task_handler)

# 添加任务（10分钟后执行）
tq.add_task("my_task", "测试", scheduled_at="2026-04-02T18:10:00")
```

### 注册心跳钩子

```python
from tick_engine import get_tick_engine

def my_hook(tick_count, context):
    print(f"心跳 #{tick_count}")

engine = get_tick_engine()
engine.on_tick(my_hook)
```

---

## 通知类型

| 类型 | 说明 | 优先级 |
|------|------|--------|
| tick | 心跳触发 | normal |
| alert | 告警 | high |
| task_complete | 任务完成 | normal |
| task_failed | 任务失败 | high |
| timeout | 任务超时 | high |
| reminder | 提醒 | normal |
| info | 普通信息 | normal |
| important | 重要信息 | high |
| health | 健康检查 | high |

---

## 文件锁说明

所有数据文件使用 `fcntl.flock` 保护：
- **共享锁（读）**：多个进程可同时读取
- **排他锁（写）**：同一时刻只有一个进程能写入

这确保了多进程（如 watchdog + main）同时访问文件时不会丢数据。

---

## 故障排查

```bash
# 查看日志
tail -f logs/kairos-mini.log
tail -f logs/errors.log

# 检查 watchdog 状态
python watchdog.py --check

# 检查任务队列
python main.py --tasks

# 检查连续失败计数
cat tasks/failure_count.json
```
