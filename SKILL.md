# kairos-mini Skill

KAIROS-mini 是一个参考 Claude Code KAIROS 架构实现的自主代理 Skill。

## 功能

- **记忆系统**: Append-only daily log + 自动 distill
- **Tick 引擎**: 心跳调度，支持 cron 表达式
- **任务管理**: 定时任务、周期任务
- **状态管理**: 单例模式，Signal 处理
- **OpenClaw 集成**: 通过 HEARTBEAT.md 和小兰通信

## 激活方式

```
/skill kairos-mini
```

## 使用方法

### 查看状态
```
kairos-mini status
```

### 添加定时任务
```
kairos-mini add-task "*/5 * * * *:检查系统状态"
```

### 列出任务
```
kairos-mini list-tasks
```

### 单次执行
```
kairos-mini run-once
```

### 启动常驻
```
kairos-mini start
```

### 停止常驻
```
kairos-mini stop
```

## 工作原理

kairos-mini 运行在独立进程中，通过以下机制和小兰交互：

1. **HEARTBEAT.md** - 状态文件，小兰读取
2. **信号处理** - SIGTERM/SIGINT 优雅退出
3. **文件锁** - 防止多实例
4. **CronTab** - cron 表达式调度

## 架构

```
kairos-mini/
├── SKILL.md           # 本文件，入口
├── README.md          # 项目说明
├── requirements.txt   # 依赖
├── LICENSE            # MIT License
└── src/
    ├── main.py        # CLI 入口
    ├── state.py       # StateManager
    ├── memory.py      # MemDir
    ├── cron.py        # CronTab
    ├── notifier.py    # Notifier
    ├── skill_invoker.py
    └── openclaw.py    # OpenClawIntegration
```

## 技术参考

- Claude Code KAIROS 源码架构 (2026-03 泄露版)
- 单进程 + Signal/atexit 管理生命周期
- Append-only log 记忆系统
- cron 表达式任务调度
