"""Bot bootstrap entry for NcatBot 5.x.

Root entry only starts the framework; business logic is implemented as plugins.
"""

from __future__ import annotations

import os
import subprocess
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


# ---- auto-update check (runs on every startup) ----
def _run_update_checks() -> None:
    """Check for NcatBot & NapCat updates and apply if available.

    If ncatbot was updated the process is restarted so the new version is loaded.
    NapCat updates are applied in-place.
    """
    update_script = PROJECT_ROOT / "check_n_update.py"
    if not update_script.exists():
        return

    print("[startup] running auto-update check ...")
    venv_python = sys.executable

    try:
        result = subprocess.run(
            [venv_python, str(update_script)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        print(result.stdout, flush=True)
        if result.stderr:
            print(result.stderr, flush=True)

        # If ncatbot/ncatbot5 was updated, restart so we import the new version
        updated = False
        for line in result.stdout.splitlines():
            if "[ncatbot]" in line.lower() and "updated" in line.lower():
                updated = True
                break
        if updated:
            print("[startup] ncatbot was updated, restarting to load new version ...")
            os.execv(venv_python, [venv_python] + sys.argv)
    except subprocess.TimeoutExpired:
        print("[startup] update check timed out, continuing ...")
    except Exception as e:
        print(f"[startup] update check failed ({e}), continuing ...")


if __name__ == "__main__":
    _run_update_checks()

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
from ncatbot.app import BotClient


bot = BotClient()


if __name__ == "__main__":
    bot.run()

