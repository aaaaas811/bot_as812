"""Expose project bot_state module when plugins are loaded with plugins/ as import root."""

from pathlib import Path
import runpy

_globals = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bot_state.py"))
globals().update(_globals)
