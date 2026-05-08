"""Bot bootstrap entry for NcatBot 5.x.

Root entry only starts the framework; business logic is implemented as plugins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# 如果项目根目录下存在 `.venv`，且当前解释器不是该虚拟环境的 python，
# 则使用该虚拟环境的解释器重新 exec 本进程，确保无论在什么虚拟环境下
# 调用 main.py 都会切换到项目内的 .venv（适用于 Windows 和类 Unix）。
def _maybe_reexec_in_project_venv() -> None:
    try:
        project_dir = Path(__file__).resolve().parent
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

import sdk_compat  # noqa: F401
from ncatbot.app import BotClient


bot = BotClient()


if __name__ == "__main__":
    bot.run()

