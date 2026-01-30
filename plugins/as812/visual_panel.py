"""可视化面板：在独立窗口中显示 as812 的输出与立绘。

用法：在启动时导入并调用 `start_panel()`，或直接运行此文件。
此模块独立于原有插件文件，不修改任何现有文件。
"""
from __future__ import annotations

import json
import os
import threading
import time
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception as e:
    raise RuntimeError("Tkinter 未安装或不可用: %s" % e)

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


class VisualPanel:
    """显示窗口，左侧为文本输出，右侧为立绘图片。"""

    def __init__(self, assets_dir: Optional[str] = None, logs_dir: Optional[str] = None):
        self.root = tk.Tk()
        self.root.title("as812 面板")
        self.root.configure(bg="#ffffff")
        self.root.geometry("900x500")
        self.root.resizable(True, True)

        base = Path(__file__).parent
        self.assets_dir = Path(assets_dir) if assets_dir else base / "assests"
        self.logs_dir = Path(logs_dir) if logs_dir else base / "logs"

        # 布局：左右两列
        self.left_frame = tk.Frame(self.root, bg="#ffffff")
        self.right_frame = tk.Frame(self.root, bg="#ffffff")
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH)

        # 文本显示（左侧）
        # 使用可爱字体优先：Comic Sans MS / 幼圆 / 默认
        preferred_fonts = ["Comic Sans MS", "幼圆", "Microsoft Yahei", "Arial"]
        available_fonts = list(tkfont.families())
        font_family = next((f for f in preferred_fonts if f in available_fonts), available_fonts[0])
        self.msg_font = tkfont.Font(family=font_family, size=28, weight="bold")

        self.msg_label = tk.Label(
            self.left_frame,
            text="连接成功",
            font=self.msg_font,
            fg="#ff2d95",
            bg="#ffffff",
            justify=tk.LEFT,
            wraplength=560,
        )
        self.msg_label.pack(padx=20, pady=20, anchor="nw")

        # 右侧图片显示
        self.canvas = tk.Canvas(self.right_frame, width=300, height=500, bg="#ffffff", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.image_id = None
        self.tk_image = None

        # 默认立绘路径
        self.default_image_path = self.assets_dir / "img" / "立绘" / "立绘.jpg"
        if not self.default_image_path.exists():
            # 尝试常见拼写
            alt = self.assets_dir / "img" / "立绘.jpg"
            if alt.exists():
                self.default_image_path = alt

        # 启动日志轮询线程
        self._stop_event = threading.Event()
        self._tail_thread = threading.Thread(target=self._tail_logs_loop, daemon=True)
        self._file_offsets: Dict[str, int] = {}

        # 初次加载图片
        self._resize_job = None
        self.load_image(self.default_image_path)

        # 绑定窗口大小变更事件，节流后处理
        self.root.bind("<Configure>", self._on_configure)
        # 消息缓冲：将短时间内的多条输出合并为一次显示
        self._msg_buffer: list[str] = []
        self._buffer_job: Optional[str] = None

    def _on_configure(self, event):
        # 节流 resize 事件，避免过度频繁重绘
        if self._resize_job:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(120, self._handle_resize)

    def _handle_resize(self):
        # 更新文本换行长度和重新加载图片以适应新尺寸
        try:
            # left_frame 宽度减去 padding
            left_w = max(100, self.left_frame.winfo_width() - 40)
            self.msg_label.config(wraplength=left_w)

            # 重新加载并缩放图片根据 canvas 当前大小
            self.load_image(self.default_image_path)
        except Exception:
            pass

    def load_image(self, path: Path):
        try:
            if Image is None or ImageTk is None:
                return
            if not path or not path.exists():
                return
            img = Image.open(path).convert("RGBA")
            # 获取 canvas 当前尺寸
            try:
                c_w = max(10, self.canvas.winfo_width())
                c_h = max(10, self.canvas.winfo_height())
            except Exception:
                c_w, c_h = 300, 500

            # 使用 canvas 大小作为缩放目标，保留一定边距
            target_w = max(50, c_w - 10)
            target_h = max(50, c_h - 10)
            img.thumbnail((target_w, target_h), Image.LANCZOS)
            self.tk_image = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            # 居中绘制
            w = max(0, (c_w - self.tk_image.width()) // 2)
            h = max(0, (c_h - self.tk_image.height()) // 2)
            self.canvas.create_image(w, h, anchor="nw", image=self.tk_image)
        except Exception:
            pass

    def start(self):
        """启动 UI 与后台轮询线程。"""
        # 初始化已存在日志文件的偏移，避免加载历史消息
        try:
            self._initialize_file_offsets()
        except Exception:
            pass

        self._tail_thread.start()
        # 使用 after 定期刷新（确保线程安全通过 queue 或 after 调用）
        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self.root.mainloop()

    def stop(self):
        self._stop_event.set()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _tail_logs_loop(self):
        # 轮询 logs 目录下的所有 .log 文件
        while not self._stop_event.is_set():
            try:
                if not self.logs_dir.exists():
                    time.sleep(0.5)
                    continue

                for file in self.logs_dir.glob("*_history.log"):
                    path = str(file)
                    # 如果这是首次发现该文件（启动后新增），将偏移设置为文件末尾并跳过读取
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

                                    # 仅处理机器人发送的回复（nickname 为 812 或 qq 为 812）
                                    nickname = data.get("nickname") or data.get("qq")
                                    if nickname in ("812", 812, "812") or data.get("qq") in ("812",):
                                        msg = data.get("message")
                                        if msg:
                                            # 更新主线程：将消息添加到缓冲，短暂延迟后合并显示
                                            self.root.after(0, self._append_to_buffer, msg)
                    except FileNotFoundError:
                        continue
                    except Exception:
                        continue

            except Exception:
                pass

            time.sleep(0.6)

    def _initialize_file_offsets(self):
        """Set offsets for existing history log files to their current EOF so we don't load old messages."""
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

    def update_message(self, text: str):
        # 简单替换 Label 内容
        # 保证文本不为空
        if not text:
            return
        # 处理 HTML 或多行的展示形式
        display_text = text.strip()
        # 限制长度以免溢出（保留足够上下文）
        if len(display_text) > 500:
            display_text = display_text[:500] + "..."
        self.msg_label.config(text=display_text)

    def _append_to_buffer(self, msg: str):
        try:
            self._msg_buffer.append(msg)
            # 重置节流任务
            if self._buffer_job:
                try:
                    self.root.after_cancel(self._buffer_job)
                except Exception:
                    pass
            # 延迟合并显示（300ms）
            self._buffer_job = self.root.after(300, self._flush_buffer)
        except Exception:
            pass

    def _flush_buffer(self):
        try:
            if not self._msg_buffer:
                self._buffer_job = None
                return
            # 合并缓冲中的多条消息，每条新消息占一行
            combined = "\n".join(self._msg_buffer)
            self.update_message(combined)
            self._msg_buffer.clear()
            self._buffer_job = None
        except Exception:
            pass


_panel_instance: Optional[VisualPanel] = None


def start_panel(assets_dir: Optional[str] = None, logs_dir: Optional[str] = None):
    """以独立子进程启动本模块的 GUI，避免在非主线程创建 Tkinter 根窗口。

    传入 `assets_dir` 和 `logs_dir` 将作为命令行参数传递给子进程。
    返回子进程的 Popen 对象（如果启动成功）。
    """
    script_path = Path(__file__).resolve()
    args = [sys.executable, str(script_path)]
    if assets_dir:
        args.append(str(assets_dir))
    if logs_dir:
        args.append(str(logs_dir))

    try:
        # 启动子进程，不等待
        # 在 Windows 上避免弹出控制台窗口：creationflags 可选
        creationflags = 0
        if os.name == "nt":
            # 0x08000000 = CREATE_NO_WINDOW would hide console; avoid if you want to see errors
            creationflags = 0
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
        return proc
    except Exception:
        return None


if __name__ == "__main__":
    # 作为独立程序运行，允许通过命令行参数传入 assets_dir 和 logs_dir
    p = Path(__file__).parent
    assets = p / "assests"
    logs = p / "logs"
    if len(sys.argv) >= 2:
        assets = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        logs = Path(sys.argv[2])

    panel = VisualPanel(assets_dir=str(assets), logs_dir=str(logs))
    panel.start()
