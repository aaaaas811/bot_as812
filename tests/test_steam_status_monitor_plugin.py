import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from ncatbot.testing import PluginTestHarness, group_message
from ncatbot.utils import get_config_manager


PLUGIN_DIR = Path(__file__).parents[1] / "plugins"


class SteamStatusMonitorPluginTest(IsolatedAsyncioTestCase):
    async def test_loads_as_ncatbot_plugin(self):
        """Removing the NcatBot entry point or manifest must break plugin loading."""
        async with PluginTestHarness(
            plugin_names=["steam_status_monitor"],
            plugins_dir=PLUGIN_DIR,
        ) as harness:
            self.assertIn("steam_status_monitor", harness.loaded_plugins)
            self.assertIsNotNone(harness.get_plugin("steam_status_monitor"))

            await harness.inject(
                group_message("/steam help", group_id="10001", user_id="20002")
            )
            await harness.settle(0.5)
            (
                harness.on("qq")
                .assert_api("send_group_msg")
                .called()
                .with_text("Steam状态监控插件指令")
            )

    async def test_ncatbot_root_can_use_admin_commands(self):
        """Dropping the configured root from admin checks must deny this command."""
        async with PluginTestHarness(
            plugin_names=["steam_status_monitor"],
            plugins_dir=PLUGIN_DIR,
        ) as harness:
            root_id = str(get_config_manager().root)
            await harness.inject(
                group_message("/steam fonts", group_id="10001", user_id=root_id)
            )
            await harness.settle(0.5)
            harness.on("qq").assert_api("send_group_msg").called()

    async def test_unload_waits_for_plugin_background_tasks(self):
        """Every plugin-owned task must be cancelled and awaited on unload."""
        finalized = asyncio.Event()
        tracked_task = None

        async with PluginTestHarness(
            plugin_names=["steam_status_monitor"],
            plugins_dir=PLUGIN_DIR,
        ) as harness:
            plugin = harness.get_plugin("steam_status_monitor")

            async def wait_forever():
                try:
                    await asyncio.Event().wait()
                finally:
                    finalized.set()

            tracked_task = plugin._track_task(wait_forever())
            await asyncio.sleep(0)

        self.assertTrue(finalized.is_set())
        self.assertTrue(tracked_task.done())

    async def test_steam_set_persists_file_config(self):
        """A successful /steam set command must survive plugin reloads."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            async with PluginTestHarness(
                plugin_names=["steam_status_monitor"],
                plugins_dir=PLUGIN_DIR,
            ) as harness:
                plugin = harness.get_plugin("steam_status_monitor")
                plugin.config = {"retry_times": 3}
                root_id = str(get_config_manager().root)

                with patch(
                    "steam_status_monitor.src.plugin.steam_status_monitor.CONFIG_PATH",
                    config_path,
                ):
                    await harness.inject(
                        group_message(
                            "/steam set retry_times 7",
                            group_id="10001",
                            user_id=root_id,
                        )
                    )
                    await harness.settle(0.5)

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(7, saved["retry_times"])

    async def test_group_admin_cannot_run_global_clear(self):
        """A group administrator must not be treated as the bot-wide root."""
        async with PluginTestHarness(
            plugin_names=["steam_status_monitor"],
            plugins_dir=PLUGIN_DIR,
        ) as harness:
            await harness.inject(
                group_message(
                    "/steam clear_allids",
                    group_id="10001",
                    user_id="30003",
                    sender={
                        "user_id": "30003",
                        "nickname": "群管理员",
                        "card": "群管理员",
                        "role": "admin",
                    },
                )
            )
            await harness.settle(0.5)
            harness.on("qq").assert_api("send_group_msg").not_called()
