"""SDK compatibility bootstrap for plugin loader path mode."""

from pathlib import Path
import runpy

# Reuse the root compatibility logic.
runpy.run_path(str(Path(__file__).resolve().parents[1] / "sdk_compat.py"))
