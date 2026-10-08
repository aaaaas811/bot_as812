"""Cross-plugin utility imports must not register as812's event handlers."""

import subprocess
import sys
import unittest
from pathlib import Path


class As812ImportTests(unittest.TestCase):
    def test_utility_import_keeps_handlers_owned_by_as812(self):
        script = """
import sdk_compat
from pathlib import Path
from ncatbot.core.registry.context import set_current_plugin
from ncatbot.core.registry.registrar import _pending_handlers
from ncatbot.plugin.loader.importer import ModuleImporter
from ncatbot.plugin.manifest import PluginManifest

importer = ModuleImporter()
importer.add_plugin_root('plugins')
set_current_plugin('_31966_plugin')
from as812.core.config_manager import ConfigManager
assert not _pending_handlers.get('_31966_plugin'), 'Utility import registered as812 handlers under another plugin'

set_current_plugin('as812')
module = importer.load_module(PluginManifest.from_toml(Path('plugins/as812/manifest.toml')))
handlers = _pending_handlers.get('as812', [])
assert handlers, 'as812 entry did not register handlers'
assert all(h.__module__ == 'as812.main' for h in handlers)
assert importer.find_plugin_class(module, 'as812').name == 'as812'
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
