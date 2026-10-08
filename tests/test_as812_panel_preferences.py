import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "plugins" / "as812" / "panel_preferences.py"


def load_module():
    spec = importlib.util.spec_from_file_location("as812_panel_preferences", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PanelPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.panel_preferences = load_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "panel.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_preferences_use_backwards_compatible_defaults(self):
        preferences = self.panel_preferences.load_panel_preferences(self.path)

        self.assertEqual(preferences["theme"], "dark")
        self.assertEqual(preferences["window"], {"width": 1080, "height": 700})
        self.assertEqual(preferences["font_scale"], 1.0)
        self.assertIs(preferences["sidebar_visible"], True)
        self.assertEqual(
            preferences["quick_commands"][0],
            {"label": "怪物列表", "command": "/怪物列表", "color": "#6366f1"},
        )

    def test_custom_preferences_are_normalized_without_losing_valid_actions(self):
        self.path.write_text(
            json.dumps(
                {
                    "theme": "light",
                    "window": {"width": 1440, "height": 900},
                    "font_scale": 1.25,
                    "sidebar_visible": False,
                    "quick_commands": [
                        {"label": "状态", "command": "/status", "color": "#123abc"},
                        {"label": "无效", "command": "", "color": "red"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        preferences = self.panel_preferences.load_panel_preferences(self.path)

        self.assertEqual(
            preferences,
            {
                "theme": "light",
                "window": {"width": 1440, "height": 900},
                "font_scale": 1.25,
                "sidebar_visible": False,
                "quick_commands": [
                    {"label": "状态", "command": "/status", "color": "#123abc"},
                ],
            },
        )

    def test_invalid_preferences_fall_back_and_saved_values_round_trip(self):
        self.path.write_text(
            json.dumps(
                {
                    "theme": "neon",
                    "window": {"width": 120, "height": 99999},
                    "font_scale": 5,
                    "sidebar_visible": "yes",
                    "quick_commands": "not-a-list",
                }
            ),
            encoding="utf-8",
        )

        preferences = self.panel_preferences.load_panel_preferences(self.path)
        self.panel_preferences.save_panel_preferences(self.path, preferences)

        self.assertEqual(
            self.panel_preferences.load_panel_preferences(self.path),
            {
                "theme": "dark",
                "window": {"width": 1080, "height": 700},
                "font_scale": 1.0,
                "sidebar_visible": True,
                "quick_commands": self.panel_preferences.DEFAULT_QUICK_COMMANDS,
            },
        )


if __name__ == "__main__":
    unittest.main()
