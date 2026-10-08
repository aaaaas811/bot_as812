"""Load and persist user-facing preferences for the as812 desktop panel."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_QUICK_COMMANDS = [
    {"label": "怪物列表", "command": "/怪物列表", "color": "#6366f1"},
    {"label": "撤回记录", "command": "/撤回记录", "color": "#8b5cf6"},
    {"label": "RAG 状态", "command": "/rag_stats", "color": "#0ea5e9"},
    {"label": "MH 帮助", "command": "/helpMH", "color": "#f59e0b"},
    {"label": "崛起怪物", "command": "/rs怪物列表", "color": "#10b981"},
]

DEFAULT_PANEL_PREFERENCES = {
    "theme": "dark",
    "window": {"width": 1080, "height": 700},
    "font_scale": 1.0,
    "sidebar_visible": True,
    "quick_commands": DEFAULT_QUICK_COMMANDS,
}

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid_number(value: Any, minimum: float, maximum: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and minimum <= value <= maximum


def normalize_panel_preferences(data: Any) -> dict[str, Any]:
    """Return a complete, safe preference mapping from untrusted JSON data."""
    result = copy.deepcopy(DEFAULT_PANEL_PREFERENCES)
    if not isinstance(data, dict):
        return result

    if data.get("theme") in {"dark", "light"}:
        result["theme"] = data["theme"]

    window = data.get("window")
    if isinstance(window, dict):
        width = window.get("width")
        height = window.get("height")
        if _valid_number(width, 720, 2560) and _valid_number(height, 480, 1600):
            result["window"] = {"width": int(width), "height": int(height)}

    scale = data.get("font_scale")
    if _valid_number(scale, 0.8, 1.5):
        result["font_scale"] = round(float(scale), 2)

    if isinstance(data.get("sidebar_visible"), bool):
        result["sidebar_visible"] = data["sidebar_visible"]

    commands = data.get("quick_commands")
    if isinstance(commands, list):
        valid_commands = []
        for item in commands[:12]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()[:16]
            command = str(item.get("command", "")).strip()[:200]
            color = str(item.get("color", "")).strip()
            if label and command and _HEX_COLOR.fullmatch(color):
                valid_commands.append({"label": label, "command": command, "color": color})
        if valid_commands:
            result["quick_commands"] = valid_commands

    return result


def load_panel_preferences(path: Path) -> dict[str, Any]:
    """Load preferences, falling back to defaults for missing or malformed files."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = None
    return normalize_panel_preferences(data)


def save_panel_preferences(path: Path, preferences: Any) -> dict[str, Any]:
    """Normalize and atomically save preferences. Returns the saved mapping."""
    normalized = normalize_panel_preferences(preferences)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
    return normalized
