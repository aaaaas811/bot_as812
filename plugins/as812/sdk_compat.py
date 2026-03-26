"""SDK compatibility bootstrap for as812 plugin."""

from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[2] / "sdk_compat.py"))
