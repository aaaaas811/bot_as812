"""Bot bootstrap entry for NcatBot 5.x.

Root entry only starts the framework; business logic is implemented as plugins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


# 如果项目根目录下存在 `.venv`，且当前解释器不是该虚拟环境的 python，
# 则使用该虚拟环境的解释器重新 exec 本进程，确保无论在什么虚拟环境下
# 调用 main.py 都会切换到项目内的 .venv（适用于 Windows 和类 Unix）。
def _maybe_reexec_in_project_venv() -> None:
    try:
        project_dir = PROJECT_ROOT
    except Exception:
        return

    venv_dir = project_dir / ".venv"
    if not venv_dir.exists():
        return

    if sys.platform.startswith("win"):
        target_py = venv_dir / "Scripts" / "python.exe"
    else:
        target_py = venv_dir / "bin" / "python"

    if not target_py.exists():
        return

    try:
        current = Path(sys.executable).resolve()
        target = target_py.resolve()
    except Exception:
        return

    if current == target:
        return

    # 使用 execv 以替换当前进程（保留 sys.argv）
    os.execv(str(target), [str(target)] + sys.argv)


_maybe_reexec_in_project_venv()


if __name__ == "__main__":
    # Runtime patch: ncatbot 4.4.1.post1 缺少 confirm 导出
    # 在导入 ncatbot 之前确保 confirm 存在于 ncatbot.utils 中
    _utils_init = (
        PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "ncatbot" / "utils" / "__init__.py"
    )
    if _utils_init.exists():
        _content = _utils_init.read_text(encoding="utf-8")
        if "def confirm(" not in _content:
            # 在 thread_pool import 行之后插入 confirm 函数
            _marker = "from ncatbot.utils.thread_pool import run_coroutine, ThreadPool"
            _insert_pos = _content.find(_marker)
            if _insert_pos != -1:
                _line_end = _content.find("\n", _insert_pos) + 1
                _patch = (
                    "\n"
                    "def confirm(prompt: str, default: bool = False) -> bool:\n"
                    '    """CLI yes/no 确认（运行时补丁）。"""\n'
                    '    suffix = " [Y/n]: " if default else " [y/N]: "\n'
                    "    try:\n"
                    "        answer = input(prompt + suffix).strip().lower()\n"
                    "    except EOFError:\n"
                    "        return default\n"
                    "    if not answer:\n"
                    "        return default\n"
                    "    return answer in (\"y\", \"yes\")\n"
                )
                _content = _content[:_line_end] + _patch + _content[_line_end:]
                _utils_init.write_text(_content, encoding="utf-8")
                print("[startup] applied ncatbot runtime patch (missing confirm)")

import sdk_compat  # noqa: F401
import bot_state
from ncatbot.app import BotClient

# --t 调试模式：只在 1042029905 群活跃
if "--t" in sys.argv:
    bot_state.set_debug_mode(True)
    print(f"[startup] 调试模式已开启，仅群 {bot_state.get_debug_group()} 活跃")

bot = BotClient()


if __name__ == "__main__":
    bot.run()

