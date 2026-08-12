"""可视化面板：在独立窗口中显示 as812 的输出、立绘、心情与交互控件。

用法：在启动时导入并调用 `start_panel()`，或直接运行此文件。
此模块独立于原有插件文件，不修改任何现有文件。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import subprocess
import sys
import errno
from pathlib import Path
from typing import Dict, Optional

try:
    import tkinter as tk
    from tkinter import font as tkfont, scrolledtext
except Exception as e:
    raise RuntimeError("Tkinter 未安装或不可用: %s" % e)

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageTk = None


# 心情 → 对应表情文件名（素描本 BaseImages 目录）
MOOD_TO_EMOTION = {
    "开心": "开心.png", "高兴": "开心.png", "快乐": "开心.png", "激动": "激动.png",
    "生气": "生气.png", "愤怒": "生气.png", "恼": "生气.png",
    "害羞": "脸红.png", "脸红": "脸红.png",
    "难过": "难受.png", "伤心": "难受.png", "难受": "难受.png",
    "哭泣": "哭泣.png", "哭": "哭泣.png",
    "害怕": "害怕.png", "恐惧": "害怕.png",
    "惊讶": "惊讶.png", "震惊": "惊讶.png",
    "无语": "无语.png", "呃": "无语.png",
    "病娇": "病娇.png",
    "困": "闭眼.png", "睡觉": "闭眼.png", "闭眼": "闭眼.png",
}
EMOTION_FILES = [
    "base.png", "开心.png", "生气.png", "无语.png", "脸红.png", "病娇.png",
    "哭泣.png", "害怕.png", "惊讶.png", "激动.png", "闭眼.png", "难受.png",
]

# 心情快捷按钮
MOOD_QUICK_BTNS = [
    ("开心", "#ff69b4"), ("生气", "#ff4444"), ("害羞", "#ff8c00"),
    ("难过", "#6a5acd"), ("无语", "#808080"), ("困", "#4169e1"),
]


class VisualPanel:
    """as812 可视化面板：消息流 + 立绘 + 心情 + 控制按钮。"""

    def __init__(self, assets_dir: Optional[str] = None, logs_dir: Optional[str] = None,
                 parent_pid: Optional[int] = None, config_dir: Optional[str] = None):
        self.root = tk.Tk()
        self.root.title("as812 面板")
        self.root.configure(bg="#1e1e2e")
        self.root.geometry("960x620")
        self.root.resizable(True, True)
        self.root.minsize(600, 400)

        base = Path(__file__).parent
        self.assets_dir = Path(assets_dir) if assets_dir else base / "assests"
        self.logs_dir = Path(logs_dir) if logs_dir else base / "logs"
        self.config_dir = Path(config_dir) if config_dir else base / "config"

        # 状态
        self._current_mood: str = ""
        self._current_emotion_file: str = "base.png"
        self._current_emotion_idx: int = 0
        self._msg_count: int = 0
        self._last_reply_time: float = 0
        self._sleeping: bool = False

        # 字体
        preferred = ["Comic Sans MS", "幼圆", "Microsoft Yahei", "Arial"]
        available = list(tkfont.families())
        font_family = next((f for f in preferred if f in available), available[0])
        self._font_family = font_family

        # 后台线程控制（必须在构建 UI 之前初始化，因为 UI 构建中会启动线程）
        self._stop_event = threading.Event()
        self._file_offsets: Dict[str, int] = {}

        # ---- 构建 UI ----
        self._build_top_bar()
        # 底部栏先打包（固定高度），主区域填充剩余空间
        self._build_bottom_bar()
        self._build_main_area()

        # 立绘资源
        self._default_image_path = self.assets_dir / "img" / "立绘" / "立绘.jpg"
        self._emotion_images: Dict[str, ImageTk.PhotoImage] = {}
        self._load_emotion_images()
        self._show_default_image()

        # 启动日志轮询
        self._tail_thread = threading.Thread(target=self._tail_logs_loop, daemon=True)
        # 启动连接状态轮询
        threading.Thread(target=self._watch_connection_loop, daemon=True).start()
        # 启动面板命令结果轮询
        threading.Thread(target=self._watch_cmd_result_loop, daemon=True).start()

        # 父进程监控
        self._parent_pid = parent_pid
        if self._parent_pid:
            threading.Thread(target=self._monitor_parent, daemon=True).start()

        # 心情文件监控
        self._mood_cache: Dict[str, str] = {}
        threading.Thread(target=self._watch_mood_loop, daemon=True).start()

        # 窗口事件
        self._resize_job = None
        self.root.bind("<Configure>", self._on_configure)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_top_bar(self):
        """顶部状态栏：心情 + 统计 + 亮暗主题。"""
        bar = tk.Frame(self.root, bg="#2a2a3e", height=36)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        self._mood_label = tk.Label(
            bar, text="心情：未设置", font=(self._font_family, 11),
            fg="#ff69b4", bg="#2a2a3e", anchor="w",
        )
        self._mood_label.pack(side=tk.LEFT, padx=12)

        # 连接状态指示
        self._conn_qq = tk.Label(
            bar, text="●QQ", font=(self._font_family, 10),
            fg="#555", bg="#2a2a3e",
        )
        self._conn_qq.pack(side=tk.RIGHT, padx=(0, 4))
        self._conn_bili = tk.Label(
            bar, text="●B站", font=(self._font_family, 10),
            fg="#555", bg="#2a2a3e",
        )
        self._conn_bili.pack(side=tk.RIGHT, padx=(0, 8))

        self._stats_label = tk.Label(
            bar, text="回复：0 条", font=(self._font_family, 11),
            fg="#aaa", bg="#2a2a3e", anchor="e",
        )
        self._stats_label.pack(side=tk.RIGHT, padx=12)

        self._theme_btn = tk.Button(
            bar, text="🌙", font=(self._font_family, 11), bd=0,
            bg="#2a2a3e", fg="#fff", activebackground="#3a3a4e",
            command=self._toggle_theme, cursor="hand2",
        )
        self._theme_btn.pack(side=tk.RIGHT, padx=4)

        self._settings_btn = tk.Button(
            bar, text="⚙ 设置", font=(self._font_family, 11), bd=0,
            bg="#2a2a3e", fg="#aaa", activebackground="#3a3a4e",
            command=self._open_settings, cursor="hand2",
        )
        self._settings_btn.pack(side=tk.RIGHT, padx=4)

    def _build_main_area(self):
        """中间主区域：左侧消息 + 右侧立绘。"""
        main = tk.Frame(self.root, bg="#1e1e2e")
        main.pack(fill=tk.BOTH, expand=True)

        # 左侧消息
        left = tk.Frame(main, bg="#1e1e2e")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        msg_header = tk.Label(
            left, text="💬 消息流", font=(self._font_family, 11, "bold"),
            fg="#ccc", bg="#1e1e2e", anchor="w",
        )
        msg_header.pack(fill=tk.X, padx=10, pady=(6, 0))

        self._msg_text = tk.Text(
            left, bg="#252536", fg="#e0e0e0", font=(self._font_family, 11),
            wrap=tk.WORD, bd=0, padx=10, pady=8, state=tk.DISABLED,
            highlightthickness=0, spacing1=2, spacing3=2,
        )
        self._msg_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        # 消息标签样式
        self._msg_text.tag_configure("bot", foreground="#ff69b4")
        self._msg_text.tag_configure("user", foreground="#88ccff")
        self._msg_text.tag_configure("time", foreground="#666", font=(self._font_family, 9))
        self._msg_text.tag_configure("emoji", foreground="#ffcc00")
        self._msg_text.tag_configure("system", foreground="#6a6", font=(self._font_family, 10, "italic"))
        self._msg_text.tag_configure("cmd_result", foreground="#22d3ee", font=("Consolas", 10))

        # 右侧立绘 + 操作
        right = tk.Frame(main, bg="#1e1e2e", width=300)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(0, 8), pady=6)
        right.pack_propagate(False)

        self._canvas = tk.Canvas(
            right, bg="#1e1e2e", highlightthickness=0, cursor="hand2",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas_tip = tk.Label(
            right, text="点击换表情", font=(self._font_family, 9),
            fg="#666", bg="#1e1e2e",
        )
        self._canvas_tip.pack(pady=(0, 4))

        # 群状态面板
        sep = tk.Frame(right, bg="#3a3a4e", height=1)
        sep.pack(fill=tk.X, padx=8, pady=(4, 4))

        status_header = tk.Label(
            right, text="📋 群状态", font=(self._font_family, 10, "bold"),
            fg="#ccc", bg="#1e1e2e", anchor="w",
        )
        status_header.pack(fill=tk.X, padx=8)

        self._status_frame = tk.Frame(right, bg="#1e1e2e")
        self._status_frame.pack(fill=tk.X, padx=8, pady=(2, 6))

        # 启动群状态轮询
        self._group_status_cache: Dict[str, dict] = {}
        threading.Thread(target=self._watch_group_status_loop, daemon=True).start()

        # 集会码显示区
        sep2 = tk.Frame(right, bg="#3a3a4e", height=1)
        sep2.pack(fill=tk.X, padx=8, pady=(4, 4))
        code_header = tk.Label(
            right, text="🎮 集会码", font=(self._font_family, 10, "bold"),
            fg="#ccc", bg="#1e1e2e", anchor="w",
        )
        code_header.pack(fill=tk.X, padx=8)
        self._code_frame = tk.Frame(right, bg="#1e1e2e")
        self._code_frame.pack(fill=tk.X, padx=8, pady=(2, 6))
        # 集会码轮询
        threading.Thread(target=self._watch_team_codes_loop, daemon=True).start()

    def _build_bottom_bar(self):
        """底部控制栏：心情快捷 + 睡眠开关 + 输入发送。"""
        bar = tk.Frame(self.root, bg="#2a2a3e")
        bar.pack(fill=tk.X, side=tk.BOTTOM)

        # 心情快捷按钮行
        mood_row = tk.Frame(bar, bg="#2a2a3e")
        mood_row.pack(fill=tk.X, padx=8, pady=(6, 2))
        tk.Label(mood_row, text="心情：", font=(self._font_family, 10),
                 fg="#aaa", bg="#2a2a3e").pack(side=tk.LEFT)
        for name, color in MOOD_QUICK_BTNS:
            tk.Button(
                mood_row, text=name, font=(self._font_family, 9), bd=0,
                bg=color, fg="#fff", activebackground=color, cursor="hand2",
                padx=8, pady=1,
                command=lambda n=name: self._set_mood(n),
            ).pack(side=tk.LEFT, padx=3)

        # 睡眠 + 输入行
        action_row = tk.Frame(bar, bg="#2a2a3e")
        action_row.pack(fill=tk.X, padx=8, pady=(2, 8))

        self._sleep_btn = tk.Button(
            action_row, text="💤 睡眠模式", font=(self._font_family, 10), bd=0,
            bg="#444", fg="#fff", activebackground="#555", cursor="hand2",
            padx=10, pady=2, command=self._toggle_sleep,
        )
        self._sleep_btn.pack(side=tk.LEFT)

        # 输入框 + 发送按钮（私聊发送给自己，用于调试/帮我说）
        self._input_entry = tk.Entry(
            action_row, font=(self._font_family, 11), bg="#333", fg="#fff",
            insertbackground="#fff", bd=0, highlightthickness=1, highlightcolor="#ff69b4",
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, ipady=3)
        self._input_entry.bind("<Return>", lambda e: self._send_input())
        self._input_placeholder = False  # placeholder 状态标志
        self._input_entry.bind("<FocusIn>", self._on_input_focus_in)
        self._input_entry.bind("<FocusOut>", self._on_input_focus_out)

        self._send_btn = tk.Button(
            action_row, text="发送", font=(self._font_family, 10), bd=0,
            bg="#ff69b4", fg="#fff", activebackground="#ff85c8", cursor="hand2",
            padx=12, pady=2, command=self._send_input,
        )
        self._send_btn.pack(side=tk.RIGHT)

        # 快捷命令按钮行
        cmd_row = tk.Frame(bar, bg="#2a2a3e")
        cmd_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(cmd_row, text="命令：", font=(self._font_family, 9),
                 fg="#666", bg="#2a2a3e").pack(side=tk.LEFT)
        quick_cmds = [
            ("/怪物列表", "#6366f1"), ("/撤回记录", "#8b5cf6"),
            ("/rag_stats", "#0ea5e9"), ("/helpMH", "#f59e0b"),
            ("/rs怪物列表", "#10b981"),
        ]
        for cmd, color in quick_cmds:
            tk.Button(
                cmd_row, text=cmd, font=(self._font_family, 8), bd=0,
                bg=color, fg="#fff", activebackground=color, cursor="hand2",
                padx=6, pady=1,
                command=lambda c=cmd: self._send_quick_cmd(c),
            ).pack(side=tk.LEFT, padx=2)

    def _send_quick_cmd(self, cmd: str):
        """发送快捷命令到群（写入指令文件供 bot 读取）。"""
        try:
            cmd_file = self.logs_dir / "_panel_cmd.json"
            cmd_file.write_text(json.dumps({
                "cmd": "group_cmd", "text": cmd, "time": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
            self._append_system_msg(f"已发送命令：{cmd}")
        except Exception as e:
            self._append_system_msg(f"发送命令失败：{e}")

    # ============================================================
    # 集会码管理
    # ============================================================

    def _watch_team_codes_loop(self):
        """后台轮询集会码文件（plugins/mh/data/_team_codes.json）。"""
        codes_path = Path(self.config_dir).parent.parent / "mh" / "data" / "_team_codes.json"
        last_mtime = 0.0
        while not self._stop_event.is_set():
            try:
                if codes_path.exists():
                    mtime = codes_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        data = json.loads(codes_path.read_text(encoding="utf-8"))
                        self.root.after(0, self._update_team_codes_display, data)
            except Exception:
                pass
            time.sleep(3.0)

    def _update_team_codes_display(self, data: dict):
        """在 UI 线程刷新集会码显示。"""
        try:
            for w in self._code_frame.winfo_children():
                w.destroy()

            mhw = data.get("mhw", [])
            mhr = data.get("mhr", [])

            if not mhw and not mhr:
                tk.Label(
                    self._code_frame, text="暂无集会码",
                    font=(self._font_family, 9), fg="#555", bg="#1e1e2e",
                ).pack(anchor="w")
                return

            if mhw:
                tk.Label(
                    self._code_frame, text=f"MHW（{len(mhw)}）：",
                    font=(self._font_family, 9, "bold"), fg="#f59e0b", bg="#1e1e2e",
                ).pack(anchor="w")
                for code in mhw[-3:]:  # 最多显示 3 个
                    tk.Label(
                        self._code_frame, text=f"  {code}",
                        font=("Consolas", 9), fg="#ddd", bg="#1e1e2e",
                    ).pack(anchor="w")

            if mhr:
                tk.Label(
                    self._code_frame, text=f"MHR（{len(mhr)}）：",
                    font=(self._font_family, 9, "bold"), fg="#10b981", bg="#1e1e2e",
                ).pack(anchor="w")
                for code in mhr[-3:]:
                    tk.Label(
                        self._code_frame, text=f"  {code}",
                        font=("Consolas", 9), fg="#ddd", bg="#1e1e2e",
                    ).pack(anchor="w")
        except Exception:
            pass

    # ============================================================
    # 心情管理
    # ============================================================

    def _watch_connection_loop(self):
        """后台轮询连接状态（通过 logs/_connection.json 文件）。"""
        conn_path = self.logs_dir / "_connection.json"
        while not self._stop_event.is_set():
            try:
                if conn_path.exists():
                    data = json.loads(conn_path.read_text(encoding="utf-8"))
                    qq_ok = data.get("qq", False)
                    bili_ok = data.get("bilibili", False)
                    self.root.after(0, self._update_conn_display, qq_ok, bili_ok)
            except Exception:
                pass
            time.sleep(3.0)

    def _update_conn_display(self, qq_ok: bool, bili_ok: bool):
        """在 UI 线程更新连接状态指示灯。"""
        self._conn_qq.configure(fg="#4ade80" if qq_ok else "#ef4444")
        self._conn_bili.configure(fg="#4ade80" if bili_ok else "#ef4444")

    def _watch_cmd_result_loop(self):
        """后台轮询面板命令结果文件，显示在消息流中。"""
        result_path = self.logs_dir / "_panel_result.json"
        last_mtime = 0.0
        while not self._stop_event.is_set():
            try:
                if result_path.exists():
                    mtime = result_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        data = json.loads(result_path.read_text(encoding="utf-8"))
                        cmd = data.get("cmd", "")
                        result = data.get("result", "")
                        if result:
                            self.root.after(0, self._append_cmd_result, cmd, result)
            except Exception:
                pass
            time.sleep(1.5)

    def _append_cmd_result(self, cmd: str, result: str):
        """在消息流中显示命令结果（青色等宽字体，区别于群聊回复）。"""
        try:
            self._msg_text.config(state=tk.NORMAL)
            ts = time.strftime("%H:%M")
            self._msg_text.insert(tk.END, f"[{ts}] ", "time")
            self._msg_text.insert(tk.END, f"📋 {cmd}\n", "system")
            for line in result.splitlines():
                self._msg_text.insert(tk.END, f"  {line}\n", "cmd_result")
            self._msg_text.see(tk.END)
            self._msg_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _watch_mood_loop(self):
        """后台轮询统一心情文件（_mood.json），变化时更新 UI。"""
        mood_path = self.logs_dir / "_mood.json"
        last_mtime = 0.0
        last_mood = ""
        while not self._stop_event.is_set():
            try:
                if mood_path.exists():
                    mtime = mood_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        data = json.loads(mood_path.read_text(encoding="utf-8"))
                        mood = str(data.get("mood", "") or "").strip()
                        if mood and mood != last_mood:
                            last_mood = mood
                            self.root.after(0, self._update_mood_display, mood)
            except Exception:
                pass
            time.sleep(1.5)

    def _update_mood_display(self, mood: str, group_id: str = ""):
        """在 UI 线程更新心情显示和立绘（静默，不产生系统消息）。"""
        if mood == self._current_mood and group_id == "":
            return
        self._current_mood = mood
        suffix = f"（{group_id}）" if group_id else ""
        self._mood_label.config(text=f"心情：{mood}{suffix}")

        # 自动切换立绘（仅当对应表情文件实际存在时才切换）
        emotion = MOOD_TO_EMOTION.get(mood, "base.png")
        if emotion != self._current_emotion_file and emotion in self._available_emotions:
            self._show_emotion(emotion)

    def _set_mood(self, mood: str):
        """点击心情快捷按钮：通知 bot 设置心情，并更新面板显示。"""
        self._current_mood = ""  # 清空以允许 _update_mood_display 执行
        self._update_mood_display(mood)
        # 写入指令文件通知 bot + 直接写入心情文件（面板立即生效）
        try:
            cmd_file = self.logs_dir / "_panel_cmd.json"
            cmd_file.write_text(json.dumps({
                "cmd": "set_mood", "text": mood, "time": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
            mood_file = self.logs_dir / "_mood.json"
            mood_file.write_text(json.dumps({"mood": mood}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        self._append_system_msg(f"手动设置心情：{mood}")

    def _watch_group_status_loop(self):
        """后台轮询群状态：心情、主动回复、最近活跃。"""
        while not self._stop_event.is_set():
            try:
                status = {}
                # 读取配置
                config = {}
                try:
                    cfg_path = self.config_dir / "config.yaml"
                    if cfg_path.exists():
                        import yaml
                        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    pass

                active_ids = config.get("active_group_id", [])
                if isinstance(active_ids, str):
                    active_ids = [active_ids]
                active_ids = set(str(g) for g in active_ids)

                # 读取统一心情文件
                unified_mood = ""
                try:
                    mood_file = self.logs_dir / "_mood.json"
                    if mood_file.exists():
                        data = json.loads(mood_file.read_text(encoding="utf-8"))
                        unified_mood = str(data.get("mood", "") or "").strip()
                except Exception:
                    pass

                # 扫描禁言文件和历史文件
                if self.logs_dir.exists():
                    for f in self.logs_dir.glob("*_mute.json"):
                        gid = f.stem.replace("_mute", "")
                        try:
                            data = json.loads(f.read_text(encoding="utf-8"))
                            status.setdefault(gid, {})["muted"] = bool(data.get("muted", False))
                        except Exception:
                            pass

                    for f in self.logs_dir.glob("*_history.log"):
                        gid = f.stem.replace("_history", "")
                        status.setdefault(gid, {})
                        status[gid]["active"] = gid in active_ids
                        # 最后活跃时间
                        try:
                            size = f.stat().st_size
                            if size > 0:
                                with open(f, "rb") as hf:
                                    # 读最后 500 字节找最后一行
                                    hf.seek(max(0, size - 500))
                                    tail = hf.read().decode("utf-8", errors="replace")
                                    last_line = ""
                                    for line in reversed(tail.splitlines()):
                                        line = line.strip()
                                        if line:
                                            last_line = line
                                            break
                                    if last_line:
                                        try:
                                            last_data = json.loads(last_line)
                                            ts = last_data.get("timestamp", 0)
                                            if ts:
                                                from datetime import datetime
                                                dt = datetime.fromtimestamp(float(ts))
                                                status[gid]["last_time"] = dt.strftime("%H:%M")
                                        except Exception:
                                            pass
                        except Exception:
                            pass

                # 统一心情应用到所有群
                if unified_mood:
                    for gid in status:
                        status[gid]["mood"] = unified_mood

                self._group_status_cache = status
                self.root.after(0, self._update_group_status_display)
            except Exception:
                pass
            time.sleep(5.0)

    def _update_group_status_display(self):
        """在 UI 线程刷新群状态面板。"""
        try:
            for w in self._status_frame.winfo_children():
                w.destroy()

            if not self._group_status_cache:
                tk.Label(
                    self._status_frame, text="暂无群数据",
                    font=(self._font_family, 9), fg="#666", bg="#1e1e2e",
                ).pack(anchor="w")
                return

            for gid in sorted(self._group_status_cache.keys()):
                info = self._group_status_cache[gid]
                mood = info.get("mood", "")
                active = info.get("active", False)
                muted = info.get("muted", False)
                last_time = info.get("last_time", "")

                row = tk.Frame(self._status_frame, bg="#252536", padx=6, pady=3)
                row.pack(fill=tk.X, pady=1)

                # 群号
                tk.Label(
                    row, text=f"群 {gid}", font=(self._font_family, 9, "bold"),
                    fg="#ddd", bg="#252536", anchor="w",
                ).pack(side=tk.LEFT)

                # 心情
                mood_text = mood if mood else "—"
                mood_color = "#ff69b4" if mood else "#555"
                tk.Label(
                    row, text=f"💭{mood_text}", font=(self._font_family, 9),
                    fg=mood_color, bg="#252536",
                ).pack(side=tk.LEFT, padx=(8, 0))

                # 禁言状态
                if muted:
                    tk.Label(
                        row, text="🔇禁言", font=(self._font_family, 8),
                        fg="#ef4444", bg="#252536",
                    ).pack(side=tk.LEFT, padx=(6, 0))

                # 主动回复
                if active:
                    tk.Label(
                        row, text="🔔主动", font=(self._font_family, 8),
                        fg="#4ade80", bg="#252536",
                    ).pack(side=tk.RIGHT)
                else:
                    tk.Label(
                        row, text="—", font=(self._font_family, 8),
                        fg="#555", bg="#252536",
                    ).pack(side=tk.RIGHT)

                # 最近活跃
                if last_time:
                    tk.Label(
                        row, text=last_time, font=(self._font_family, 8),
                        fg="#666", bg="#252536",
                    ).pack(side=tk.RIGHT, padx=(0, 6))

        except Exception:
            pass

    # ============================================================
    # 立绘管理
    # ============================================================

    def _load_emotion_images(self):
        """预加载表情图片（懒加载，首次用到才加载）。只扫描 assests 目录。"""
        self._emotion_images = {}
        self._available_emotions: list[str] = []
        if self.assets_dir.exists():
            for f in sorted(self.assets_dir.iterdir()):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
                    self._available_emotions.append(f.name)
        if not self._available_emotions:
            self._available_emotions = ["立绘.jpg"]

    def _get_emotion_image(self, filename: str) -> Optional[ImageTk.PhotoImage]:
        """获取表情图片（缓存），缩放到 canvas 大小。只从 assests 目录找。"""
        if filename in self._emotion_images:
            return self._emotion_images[filename]

        path = self.assets_dir / filename
        if not path.exists():
            return None

        try:
            if Image is None:
                return None
            img = Image.open(path).convert("RGBA")
            try:
                c_w = max(50, self._canvas.winfo_width() - 10)
                c_h = max(50, self._canvas.winfo_height() - 10)
            except Exception:
                c_w, c_h = 280, 440
            img.thumbnail((c_w, c_h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            self._emotion_images[filename] = tk_img
            return tk_img
        except Exception:
            return None

    def _show_default_image(self):
        """显示默认立绘（assests/img/立绘/立绘.jpg）。"""
        try:
            if Image is None or not self._default_image_path.exists():
                return
            img = Image.open(self._default_image_path).convert("RGBA")
            try:
                c_w = max(50, self._canvas.winfo_width() - 10)
                c_h = max(50, self._canvas.winfo_height() - 10)
            except Exception:
                c_w, c_h = 280, 440
            img.thumbnail((c_w, c_h), Image.LANCZOS)
            self._default_tk_image = ImageTk.PhotoImage(img)
            self._canvas.delete("all")
            x = max(0, (c_w - self._default_tk_image.width()) // 2)
            y = max(0, (c_h - self._default_tk_image.height()) // 2)
            self._canvas.create_image(x, y, anchor="nw", image=self._default_tk_image)
            self._current_emotion_file = "立绘.jpg"
            self._current_emotion_idx = -1  # -1 表示默认立绘（不在 _available_emotions 中）
        except Exception:
            pass

    def _show_emotion(self, filename: str):
        """在 canvas 上显示指定表情（安全，任何异常都不崩溃）。"""
        try:
            tk_img = self._get_emotion_image(filename)
            if tk_img is None:
                return
            self._canvas.delete("all")
            try:
                c_w = self._canvas.winfo_width()
                c_h = self._canvas.winfo_height()
            except Exception:
                c_w, c_h = 300, 500
            x = max(0, (c_w - tk_img.width()) // 2)
            y = max(0, (c_h - tk_img.height()) // 2)
            self._canvas.create_image(x, y, anchor="nw", image=tk_img)
            self._current_emotion_file = filename
            try:
                self._current_emotion_idx = self._available_emotions.index(filename)
            except ValueError:
                self._current_emotion_idx = 0
        except Exception:
            pass

    def _on_canvas_click(self, event):
        """点击立绘：从默认立绘开始，循环切换实际存在的表情文件。"""
        if not self._available_emotions:
            return
        # 从默认立绘（-1）或当前表情开始，切换到下一个
        self._current_emotion_idx = (self._current_emotion_idx + 1) % len(self._available_emotions)
        new_file = self._available_emotions[self._current_emotion_idx]
        self._emotion_images.pop(new_file, None)
        self._show_emotion(new_file)
        self._canvas_tip.config(text=new_file.rsplit(".", 1)[0])

    # ============================================================
    # 消息显示
    # ============================================================

    def _append_msg(self, text: str, tag: str = "bot"):
        """向消息流追加一条消息（线程安全，通过 after 调用）。"""
        try:
            self._msg_text.config(state=tk.NORMAL)
            ts = time.strftime("%H:%M")
            self._msg_text.insert(tk.END, f"[{ts}] ", "time")
            self._msg_text.insert(tk.END, text + "\n", tag)
            self._msg_text.see(tk.END)
            self._msg_text.config(state=tk.DISABLED)
            # 限制行数
            lines = int(self._msg_text.index("end-1c").split(".")[0])
            if lines > 200:
                self._msg_text.config(state=tk.NORMAL)
                self._msg_text.delete("1.0", f"{lines - 150}.0")
                self._msg_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _append_system_msg(self, text: str):
        self._append_msg(f"⚙ {text}", "system")

    def update_message(self, text: str):
        """更新最新消息显示（兼容旧接口）。"""
        if not text:
            return
        display = text.strip()
        if len(display) > 500:
            display = display[:500] + "..."
        self._append_msg(display, "bot")

    def _append_to_buffer(self, msg: str):
        """消息缓冲：短时间多条消息合并后显示。"""
        try:
            if not hasattr(self, "_msg_buffer"):
                self._msg_buffer = []
            self._msg_buffer.append(msg)
            if hasattr(self, "_buffer_job") and self._buffer_job:
                try:
                    self.root.after_cancel(self._buffer_job)
                except Exception:
                    pass
            self._buffer_job = self.root.after(200, self._flush_buffer)
        except Exception:
            pass

    def _flush_buffer(self):
        try:
            if not getattr(self, "_msg_buffer", None):
                self._buffer_job = None
                return
            for msg in self._msg_buffer:
                self._append_msg(msg, "bot")
            self._msg_count += len(self._msg_buffer)
            self._stats_label.config(text=f"回复：{self._msg_count} 条")
            self._msg_buffer.clear()
            self._buffer_job = None
        except Exception:
            pass

    # ============================================================
    # 控制交互
    # ============================================================

    def _toggle_sleep(self):
        """切换睡眠模式：通知 bot 实际执行。"""
        self._sleeping = not self._sleeping
        if self._sleeping:
            self._sleep_btn.config(text="☀ 唤醒", bg="#2d8b2d")
            self._append_system_msg("睡眠模式已开启")
        else:
            self._sleep_btn.config(text="💤 睡眠模式", bg="#444")
            self._append_system_msg("睡眠模式已关闭")
        # 通知 bot
        try:
            cmd_file = self.logs_dir / "_panel_cmd.json"
            cmd_file.write_text(json.dumps({
                "cmd": "set_sleep", "value": self._sleeping, "time": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _on_input_focus_in(self, event):
        """输入框获得焦点时清除 placeholder。"""
        if self._input_placeholder:
            self._input_placeholder = False
            self._input_entry.delete(0, tk.END)
            self._input_entry.configure(fg="#fff")

    def _on_input_focus_out(self, event):
        """输入框失去焦点时恢复 placeholder。"""
        if not self._input_entry.get().strip():
            self._input_placeholder = True
            self._input_entry.configure(fg="#666")

    def _send_input(self):
        """发送输入内容（写入日志文件供 bot 读取，或通过子进程发送）。"""
        if self._input_placeholder:
            return
        text = self._input_entry.get().strip()
        if not text:
            return
        self._input_entry.delete(0, tk.END)
        self._append_msg(f"📤 {text}", "user")
        # 写入一个临时文件供 bot 读取（或直接用子进程发消息）
        try:
            cmd_file = self.logs_dir / "_panel_cmd.json"
            cmd_file.write_text(json.dumps({
                "cmd": "send", "text": text, "time": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
            self._append_system_msg("指令已发送，等待 bot 处理…")
        except Exception as e:
            self._append_system_msg(f"发送失败：{e}")

    # ============================================================
    # 设置窗口
    # ============================================================

    def _open_settings(self):
        """打开设置窗口（config.yaml + cat_prompt.txt 编辑器）。"""
        win = tk.Toplevel(self.root)
        win.title("as812 设置")
        win.geometry("720x560")
        win.configure(bg="#1e1e2e")
        win.transient(self.root)
        win.grab_set()

        notebook = tk.Frame(win, bg="#1e1e2e")
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ---- Tab 切换 ----
        tab_bar = tk.Frame(notebook, bg="#1e1e2e")
        tab_bar.pack(fill=tk.X)

        self._settings_tab = "config"
        config_tab_btn = tk.Button(
            tab_bar, text="⚙ config.yaml", font=(self._font_family, 11, "bold"),
            bg="#ff69b4", fg="#fff", bd=0, padx=14, pady=4, cursor="hand2",
        )
        prompt_tab_btn = tk.Button(
            tab_bar, text="📝 cat_prompt.txt", font=(self._font_family, 11),
            bg="#333", fg="#aaa", bd=0, padx=14, pady=4, cursor="hand2",
        )
        log_tab_btn = tk.Button(
            tab_bar, text="📋 bot.log", font=(self._font_family, 11),
            bg="#333", fg="#aaa", bd=0, padx=14, pady=4, cursor="hand2",
        )
        config_tab_btn.pack(side=tk.LEFT, padx=(0, 4))
        prompt_tab_btn.pack(side=tk.LEFT, padx=(0, 4))
        log_tab_btn.pack(side=tk.LEFT)

        # 内容区
        content_frame = tk.Frame(notebook, bg="#1e1e2e")
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # ---- config.yaml 编辑器 ----
        config_frame = tk.Frame(content_frame, bg="#1e1e2e")
        config_hint = tk.Label(
            config_frame, text="直接编辑 YAML 键值对，修改后点「保存 config」生效（部分项需重启 bot）",
            font=(self._font_family, 10), fg="#888", bg="#1e1e2e", anchor="w",
        )
        config_hint.pack(fill=tk.X, pady=(0, 4))

        config_text = tk.Text(
            config_frame, bg="#252536", fg="#e0e0e0", font=("Consolas", 11),
            wrap=tk.NONE, bd=0, padx=10, pady=8, insertbackground="#fff",
            highlightthickness=0,
        )
        config_scroll_y = tk.Scrollbar(config_frame, command=config_text.yview)
        config_scroll_x = tk.Scrollbar(config_frame, orient=tk.HORIZONTAL, command=config_text.xview)
        config_text.configure(yscrollcommand=config_scroll_y.set, xscrollcommand=config_scroll_x.set)
        config_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        config_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        config_text.pack(fill=tk.BOTH, expand=True)

        # 加载 config.yaml
        config_path = self.config_dir / "config.yaml"
        try:
            config_text.insert("1.0", config_path.read_text(encoding="utf-8"))
        except Exception:
            config_text.insert("1.0", "# config.yaml 读取失败")

        def save_config():
            try:
                content = config_text.get("1.0", tk.END).rstrip("\n")
                import yaml
                yaml.safe_load(content)  # 验证 YAML 语法
                config_path.write_text(content + "\n", encoding="utf-8")
                self._append_system_msg("config.yaml 已保存")
                win.destroy()
            except Exception as e:
                self._append_system_msg(f"config.yaml 保存失败: {e}")

        config_btn_bar = tk.Frame(config_frame, bg="#1e1e2e")
        config_btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
        config_save_btn = tk.Button(
            config_btn_bar, text="💾 保存 config", font=(self._font_family, 11),
            bg="#ff69b4", fg="#fff", bd=0, padx=16, pady=4, cursor="hand2",
            command=save_config,
        )
        config_save_btn.pack()

        # ---- cat_prompt.txt 编辑器 ----
        prompt_frame = tk.Frame(content_frame, bg="#1e1e2e")
        prompt_hint = tk.Label(
            prompt_frame, text="编辑 bot 的人设提示词，保存后下次回复即生效",
            font=(self._font_family, 10), fg="#888", bg="#1e1e2e", anchor="w",
        )
        prompt_hint.pack(fill=tk.X, pady=(0, 4))

        prompt_text = tk.Text(
            prompt_frame, bg="#252536", fg="#e0e0e0", font=(self._font_family, 12),
            wrap=tk.WORD, bd=0, padx=10, pady=8, insertbackground="#fff",
            highlightthickness=0, spacing1=2, spacing3=2,
        )
        prompt_scroll = tk.Scrollbar(prompt_frame, command=prompt_text.yview)
        prompt_text.configure(yscrollcommand=prompt_scroll.set)
        prompt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        prompt_text.pack(fill=tk.BOTH, expand=True)

        # 加载 cat_prompt.txt
        prompt_path = self.config_dir / "cat_prompt.txt"
        try:
            prompt_text.insert("1.0", prompt_path.read_text(encoding="utf-8"))
        except Exception:
            prompt_text.insert("1.0", "# cat_prompt.txt 读取失败")

        def save_prompt():
            try:
                content = prompt_text.get("1.0", tk.END).rstrip("\n")
                prompt_path.write_text(content + "\n", encoding="utf-8")
                self._append_system_msg("cat_prompt.txt 已保存，下次回复即生效")
                win.destroy()
            except Exception as e:
                self._append_system_msg(f"cat_prompt.txt 保存失败: {e}")

        prompt_btn_bar = tk.Frame(prompt_frame, bg="#1e1e2e")
        prompt_btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
        prompt_save_btn = tk.Button(
            prompt_btn_bar, text="💾 保存 prompt", font=(self._font_family, 11),
            bg="#ff69b4", fg="#fff", bd=0, padx=16, pady=4, cursor="hand2",
            command=save_prompt,
        )
        prompt_save_btn.pack()

        # ---- bot.log 查看器 ----
        log_frame = tk.Frame(content_frame, bg="#1e1e2e")
        log_hint = tk.Label(
            log_frame, text="bot.log 最后 200 行（只读，点击「刷新」重新加载）",
            font=(self._font_family, 10), fg="#888", bg="#1e1e2e", anchor="w",
        )
        log_hint.pack(fill=tk.X, pady=(0, 4))

        log_text = tk.Text(
            log_frame, bg="#1a1a2e", fg="#a0a0a0", font=("Consolas", 10),
            wrap=tk.WORD, bd=0, padx=8, pady=6, state=tk.DISABLED,
            highlightthickness=0,
        )
        log_scroll = tk.Scrollbar(log_frame, command=log_text.yview)
        log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        log_text.pack(fill=tk.BOTH, expand=True)

        def load_log():
            log_text.config(state=tk.NORMAL)
            log_text.delete("1.0", tk.END)
            # 尝试多个日志路径
            log_paths = [
                self.logs_dir.parent / "logs" / "bot.log",
                Path("logs/bot.log"),
                self.logs_dir / "bot.log",
            ]
            loaded = False
            for lp in log_paths:
                if lp.exists():
                    try:
                        content = lp.read_text(encoding="utf-8", errors="replace")
                        lines = content.splitlines()
                        tail = lines[-200:] if len(lines) > 200 else lines
                        log_text.insert("1.0", "\n".join(tail))
                        log_text.see(tk.END)
                        loaded = True
                        break
                    except Exception:
                        pass
            if not loaded:
                log_text.insert("1.0", "# bot.log 未找到")
            log_text.config(state=tk.DISABLED)

        log_btn_bar = tk.Frame(log_frame, bg="#1e1e2e")
        log_btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
        tk.Button(
            log_btn_bar, text="🔄 刷新日志", font=(self._font_family, 11),
            bg="#6366f1", fg="#fff", bd=0, padx=16, pady=4, cursor="hand2",
            command=load_log,
        ).pack()

        # ---- Tab 切换逻辑 ----
        all_frames = [config_frame, prompt_frame, log_frame]
        all_btns = [config_tab_btn, prompt_tab_btn, log_tab_btn]

        def switch_tab(idx):
            for i, (frame, btn) in enumerate(zip(all_frames, all_btns)):
                if i == idx:
                    frame.pack(fill=tk.BOTH, expand=True)
                    btn.configure(bg="#ff69b4", fg="#fff", font=(self._font_family, 11, "bold"))
                else:
                    frame.pack_forget()
                    btn.configure(bg="#333", fg="#aaa", font=(self._font_family, 11))
            if idx == 2:
                load_log()

        config_tab_btn.configure(command=lambda: switch_tab(0))
        prompt_tab_btn.configure(command=lambda: switch_tab(1))
        log_tab_btn.configure(command=lambda: switch_tab(2))

        # 默认显示 config
        switch_tab(0)

    # ============================================================
    # 主题切换
    # ============================================================

    _LIGHT = {
        "bg": "#ffffff", "bar_bg": "#f0f0f0", "text_bg": "#fafafa",
        "text_fg": "#222", "mood_fg": "#ff2d95", "canvas_bg": "#ffffff",
        "theme_icon": "🌙",
    }
    _DARK = {
        "bg": "#1e1e2e", "bar_bg": "#2a2a3e", "text_bg": "#252536",
        "text_fg": "#e0e0e0", "mood_fg": "#ff69b4", "canvas_bg": "#1e1e2e",
        "theme_icon": "☀",
    }

    def _toggle_theme(self):
        """切换亮/暗主题。"""
        is_dark = self.root.cget("bg") == self._DARK["bg"]
        t = self._LIGHT if is_dark else self._DARK
        self.root.configure(bg=t["bg"])
        # 遍历更新所有 widget 的颜色
        for w in [self._mood_label, self._stats_label]:
            try:
                w.configure(bg=t["bar_bg"], fg=t["mood_fg"] if w == self._mood_label else "#aaa")
            except Exception:
                pass
        try:
            self._msg_text.configure(bg=t["text_bg"], fg=t["text_fg"])
        except Exception:
            pass
        try:
            self._canvas.configure(bg=t["canvas_bg"])
            self._canvas_tip.configure(bg=t["canvas_bg"])
        except Exception:
            pass
        self._theme_btn.configure(text=t["theme_icon"], bg=t["bar_bg"])

    # ============================================================
    # 日志监控（只读 812 的回复）
    # ============================================================

    def _tail_logs_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.logs_dir.exists():
                    time.sleep(0.5)
                    continue
                for file in self.logs_dir.glob("*_history.log"):
                    path = str(file)
                    if path not in self._file_offsets:
                        try:
                            self._file_offsets[path] = file.stat().st_size
                        except Exception:
                            self._file_offsets[path] = 0
                        continue
                    last_offset = self._file_offsets.get(path, 0)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            f.seek(last_offset)
                            lines = f.readlines()
                            if lines:
                                self._file_offsets[path] = f.tell()
                                for line in lines:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        data = json.loads(line)
                                    except Exception:
                                        continue
                                    nickname = data.get("nickname") or data.get("qq")
                                    if nickname in ("812", 812) or data.get("qq") in ("812",):
                                        msg = data.get("message")
                                        if msg:
                                            self.root.after(0, self._append_to_buffer, msg)
                    except FileNotFoundError:
                        continue
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.6)

    # ============================================================
    # 窗口管理
    # ============================================================

    def _on_configure(self, event):
        if self._resize_job:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(150, self._handle_resize)

    def _handle_resize(self):
        try:
            self._emotion_images.clear()
            if self._current_emotion_idx == -1:
                self._show_default_image()
            else:
                self._show_emotion(self._current_emotion_file)
        except Exception:
            pass

    def _monitor_parent(self):
        """监控父进程是否存活，不存在时自动关闭面板。Windows 用 ctypes OpenProcess。"""
        try:
            parent = int(self._parent_pid)
        except Exception:
            return

        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            while not self._stop_event.is_set():
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent)
                if handle:
                    kernel32.CloseHandle(handle)
                else:
                    # OpenProcess 失败 = 进程不存在
                    try:
                        self.root.after(0, self.stop)
                    except Exception:
                        try:
                            self.stop()
                        except Exception:
                            pass
                    break
                time.sleep(2.0)
        else:
            while not self._stop_event.is_set():
                try:
                    os.kill(parent, 0)
                except OSError:
                    try:
                        self.root.after(0, self.stop)
                    except Exception:
                        try:
                            self.stop()
                        except Exception:
                            pass
                    break
                except Exception:
                    pass
                time.sleep(2.0)

    def start(self):
        try:
            self._initialize_file_offsets()
        except Exception:
            pass
        self._tail_thread.start()
        self._append_system_msg("面板已启动，等待消息…")
        self.root.mainloop()

    def stop(self):
        self._stop_event.set()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _initialize_file_offsets(self):
        try:
            if not self.logs_dir.exists():
                return
            for file in self.logs_dir.glob("*_history.log"):
                path = str(file)
                try:
                    self._file_offsets[path] = file.stat().st_size
                except Exception:
                    self._file_offsets[path] = 0
        except Exception:
            pass


# ============================================================
# 子进程启动入口
# ============================================================

def start_panel(assets_dir: Optional[str] = None, logs_dir: Optional[str] = None,
                config_dir: Optional[str] = None):
    """以独立子进程启动面板 GUI。"""
    script_path = Path(__file__).resolve()
    args = [sys.executable, str(script_path)]
    if assets_dir:
        args.append(str(assets_dir))
    if logs_dir:
        args.append(str(logs_dir))
    if config_dir:
        args.append(str(config_dir))
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc
    except Exception:
        return None


if __name__ == "__main__":
    p = Path(__file__).parent
    assets = p / "assests"
    logs = p / "logs"
    config = p / "config"
    if len(sys.argv) >= 2:
        assets = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        logs = Path(sys.argv[2])
    if len(sys.argv) >= 4:
        config = Path(sys.argv[3])

    panel = VisualPanel(assets_dir=str(assets), logs_dir=str(logs),
                        config_dir=str(config),
                        parent_pid=int(sys.argv[4]) if len(sys.argv) >= 5 else None)
    panel.start()
