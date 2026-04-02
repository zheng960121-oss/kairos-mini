# kairos-mini

> 参考 Claude Code KAIROS 架构实现的轻量级自主代理

## 🎯 项目简介

kairos-mini 是一个参考 Anthropic Claude Code 泄露源码中的 KAIROS 架构设计的自主代理系统。

**核心特性：**
- 🧠 **三层记忆系统**: Append-only daily log + 自动 distill + 跨会话记忆
- ⏰ **Cron 调度**: 支持标准 cron 表达式，不只是固定 interval
- 🔄 **单进程架构**: Signal/atexit 管理，无复杂 watchdog
- 🔗 **OpenClaw 集成**: 通过 HEARTBEAT.md 和主 Agent 通信

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 基本使用

```bash
# 单次执行（测试用）
python src/main.py --run-once --workspace ~

# 启动后台常驻
python src/main.py --start --workspace ~

# 停止后台进程
python src/main.py --stop --workspace ~

# 添加定时任务
python src/main.py --add-task "*/5 * * * *:检查系统状态" --workspace ~

# 列出所有任务
python src/main.py --list-tasks --workspace ~
```

### 作为 OpenClaw Skill 使用

```bash
# 在 OpenClaw 中激活
/skill kairos-mini
```

## 📄 License

MIT License
