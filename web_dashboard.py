#!/usr/bin/env python3
"""
KAIROS-mini Web Dashboard
参考 Claude Code 源码风格：深色主题 + 简洁状态卡
"""

import json
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, Dict, Any

# 如果作为独立脚本，KAIROSmini 可能不可用
try:
    from main import KAIROSmini
    from StateManager import StateManager
    from MemDir import MemDir
    HAS_KAIROS = True
except ImportError:
    HAS_KAIROS = False


# ─────────────────────────────────────────────
#  Dashboard Data Provider
# ─────────────────────────────────────────────

class DashboardData:
    """线程安全的状态快照"""
    
    def __init__(self):
        self.lock = threading.RLock()
        self.session_id = "—"
        self.start_time = "—"
        self.uptime = 0
        self.tick_count = 0
        self.tasks_total = 0
        self.tasks_memory = 0
        self.tasks_file = 0
        self.kairos_active = False
        self.memory_lines: list = []
        self.memory_stats: dict = {}
        self.last_updated = "—"
    
    def update(self, kairos: Optional['KAIROSmini'] = None,
               state: Optional['StateManager'] = None,
               memdir: Optional['MemDir'] = None):
        with self.lock:
            now = datetime.now()
            
            if state:
                self.session_id = state.session_id
                self.start_time = state.start_time.strftime("%Y-%m-%d %H:%M:%S")
                self.uptime = (now - state.start_time).total_seconds()
                self.tick_count = state.tick_count
                self.kairos_active = state.kairos_active
            
            if state and kairos:
                self.tasks_memory = len(state.session_cron_tasks)
                self.tasks_file = len(kairos.crontab.get_file_tasks()) if hasattr(kairos, 'crontab') else 0
                self.tasks_total = self.tasks_memory + self.tasks_file
            
            if memdir:
                try:
                    index = memdir.read_memory_index()
                    self.memory_lines = index.strip().split("\n")[-20:] if index.strip() else []
                    self.memory_stats = memdir.get_stats()
                except Exception:
                    self.memory_lines = []
                    self.memory_stats = {}
            
            self.last_updated = now.strftime("%H:%M:%S")
    
    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            uptime_str = f"{int(self.uptime)}s"
            if self.uptime >= 3600:
                uptime_str = f"{int(self.uptime//3600)}h {int((self.uptime%3600)//60)}m"
            elif self.uptime >= 60:
                uptime_str = f"{int(self.uptime//60)}m {int(self.uptime%60)}s"
            
            return {
                "session_id": self.session_id,
                "start_time": self.start_time,
                "uptime": uptime_str,
                "uptime_seconds": int(self.uptime),
                "tick_count": self.tick_count,
                "tasks_total": self.tasks_total,
                "tasks_memory": self.tasks_memory,
                "tasks_file": self.tasks_file,
                "kairos_active": self.kairos_active,
                "memory_lines": self.memory_lines,
                "memory_total_entries": self.memory_stats.get("total_entries", 0),
                "memory_total_files": self.memory_stats.get("total_files", 0),
                "last_updated": self.last_updated,
            }


# ─────────────────────────────────────────────
#  HTTP Handler
# ─────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    
    data: DashboardData = None  # 静态赋值
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html()
        elif self.path == "/api/status":
            self.send_json()
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)
    
    def send_html(self):
        html = self._build_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def send_json(self):
        d = self.data.to_dict() if self.data else {}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    
    def _build_html(self) -> str:
        d = self.data.to_dict() if self.data else {}
        
        active_pill = '<span class="pill active">● ACTIVE</span>' if d.get('kairos_active') else '<span class="pill">○ INACTIVE</span>'
        
        mem_lines = d.get('memory_lines', [])
        mem_html = ""
        if mem_lines:
            for line in mem_lines:
                line = line.strip()
                if line.startswith('-'):
                    line = line[1:].strip()
                if line:
                    mem_html += f'<div class="mem-line">{self._esc(line[:120])}</div>\n'
        else:
            mem_html = '<div class="mem-empty">No memories yet</div>'
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KAIROS-mini Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922;
  }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Mono', Consolas, monospace; background: var(--bg); color: var(--text); min-height: 100vh; padding: 2rem; }}
  .header {{ display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem; }}
  .header h1 {{ font-size: 1.4rem; font-weight: 600; color: var(--accent); letter-spacing: -0.5px; }}
  .header .tag {{ font-size: 0.75rem; color: var(--muted); background: var(--card); padding: 2px 8px; border-radius: 12px; border: 1px solid var(--border); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; position: relative; overflow: hidden; }}
  .card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--accent); opacity: 0.6; }}
  .card.session::before {{ background: var(--green); }}
  .card.tasks::before {{ background: var(--yellow); }}
  .card-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 0.5rem; }}
  .card-value {{ font-size: 1.8rem; font-weight: 700; line-height: 1; }}
  .card-sub {{ font-size: 0.75rem; color: var(--muted); margin-top: 0.4rem; }}
  .pill {{ font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; font-weight: 600; }}
  .pill.active {{ color: var(--green); background: rgba(63,185,80,0.1); border: 1px solid rgba(63,185,80,0.3); }}
  .section-title {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin: 1.5rem 0 0.8rem; }}
  .memory-block {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; max-height: 300px; overflow-y: auto; }}
  .memory-block::-webkit-scrollbar {{ width: 6px; }} .memory-block::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
  .mem-line {{ font-size: 0.8rem; color: var(--text); padding: 0.25rem 0; border-bottom: 1px solid rgba(48,54,61,0.5); line-height: 1.5; }}
  .mem-line:last-child {{ border-bottom: none; }} .mem-empty {{ color: var(--muted); font-size: 0.8rem; font-style: italic; }}
  .footer {{ margin-top: 2rem; font-size: 0.7rem; color: var(--muted); text-align: center; }}
  .refresh-note {{ display: inline-block; margin-left: 1rem; font-size: 0.7rem; color: var(--muted); }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .live {{ animation: pulse 2s ease-in-out infinite; color: var(--green); }}
</style>
</head>
<body>

<div class="header">
  <h1>◆ KAIROS-mini</h1>
  {active_pill}
  <span class="tag">Dashboard</span>
  <span class="refresh-note"><span class="live">●</span> auto-refresh 5s · last: {d.get('last_updated','—')}</span>
</div>

<div class="grid">
  <div class="card session">
    <div class="card-label">Session ID</div>
    <div class="card-value" style="font-size:1.2rem">{d.get('session_id','—')}</div>
    <div class="card-sub">started {d.get('start_time','—')}</div>
  </div>
  <div class="card">
    <div class="card-label">Uptime</div>
    <div class="card-value">{d.get('uptime','—')}</div>
    <div class="card-sub">tick #{d.get('tick_count',0):,}</div>
  </div>
  <div class="card tasks">
    <div class="card-label">Tasks</div>
    <div class="card-value">{d.get('tasks_total',0)}</div>
    <div class="card-sub">memory: {d.get('tasks_memory',0)} · file: {d.get('tasks_file',0)}</div>
  </div>
  <div class="card">
    <div class="card-label">Memory</div>
    <div class="card-value">{d.get('memory_total_entries',0)}</div>
    <div class="card-sub">{d.get('memory_total_files',0)} files</div>
  </div>
</div>

<div class="section-title">Recent Memories</div>
<div class="memory-block">
{mem_html}
</div>

<div class="footer">KAIROS-mini Dashboard · {d.get('last_updated','—')}</div>

<script>
setInterval(async () => {{
  try {{
    let r = await fetch('/api/status');
    let d = await r.json();
    let vals = document.querySelectorAll('.card-value');
    if(vals[0]) vals[0].textContent = d.session_id || '—';
    if(vals[1]) {{ vals[1].textContent = d.uptime || '—'; vals[1].nextElementSibling.textContent = 'tick #'+(d.tick_count||0).toLocaleString(); }}
    if(vals[2]) vals[2].textContent = d.tasks_total || 0;
    if(vals[3]) vals[3].textContent = d.memory_total_entries || 0;
    let pill = document.querySelector('.pill');
    if(pill) {{ if(d.kairos_active) {{ pill.className='pill active'; pill.textContent='● ACTIVE'; }} else {{ pill.className='pill'; pill.textContent='○ INACTIVE'; }} }}
    let note = document.querySelector('.refresh-note');
    if(note) note.innerHTML = '<span class="live">●</span> auto-refresh 5s · last: '+(d.last_updated||'—');
  }} catch(e) {{}}
}}, 5000);
</script>
</body>
</html>"""
        return html
    
    def _esc(self, s: str) -> str:
        return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


# ─────────────────────────────────────────────
#  Dashboard Server
# ─────────────────────────────────────────────

class DashboardServer:
    
    def __init__(self, port: int = 8741, data: Optional[DashboardData] = None):
        self.port = port
        self.data = data or DashboardData()
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
    
    def start(self, kairos: Optional[Any] = None):
        handler = DashboardHandler
        handler.data = self.data
        self.server = HTTPServer(('0.0.0.0', self.port), handler)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        print(f"[Dashboard] 🌐 启动于 http://localhost:{self.port}")
        print(f"[Dashboard] 📊 http://localhost:{self.port}/api/status (JSON)")
        self.refresh(kairos)
    
    def _serve(self):
        self.server.serve_forever()
    
    def refresh(self, kairos: Optional[Any] = None):
        if kairos is None:
            return
        try:
            self.data.update(kairos=kairos, state=kairos.state, memdir=kairos.memdir)
        except Exception as e:
            print(f"[Dashboard] refresh error: {e}")
    
    def stop(self):
        if self.server:
            self.server.shutdown()
            print(f"[Dashboard] 已停止")


# ─────────────────────────────────────────────
#  CLI 独立启动
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="KAIROS-mini Web Dashboard (standalone)")
    parser.add_argument('--port', '-p', type=int, default=8741)
    parser.add_argument('--workspace', '-w', type=str, default='.')
    args = parser.parse_args()
    
    workspace = Path(args.workspace).expanduser().resolve()
    
    data = DashboardData()
    data.session_id = "standalone"
    data.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data.uptime = 0
    data.tick_count = 0
    data.tasks_total = 0
    data.kairos_active = False
    
    try:
        memdir = MemDir(workspace)
        data.update(memdir=memdir)
    except Exception:
        pass
    
    DashboardHandler.data = data
    
    server = HTTPServer(('0.0.0.0', args.port), DashboardHandler)
    print(f"🌐 KAIROS-mini Dashboard: http://localhost:{args.port}")
    print(f"📊 JSON API: http://localhost:{args.port}/api/status")
    server.serve_forever()
