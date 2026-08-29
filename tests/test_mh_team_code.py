import sys
from types import ModuleType, SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock


class _Registrar:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: lambda func: func


class _Plugin:
    pass


ncatbot_core = ModuleType("ncatbot.core")
ncatbot_core.registrar = SimpleNamespace(qq=_Registrar())
ncatbot_event_qq = ModuleType("ncatbot.event.qq")
ncatbot_event_qq.GroupMessageEvent = object
ncatbot_plugin = ModuleType("ncatbot.plugin")
ncatbot_plugin.NcatBotPlugin = _Plugin
ncatbot_utils = ModuleType("ncatbot.utils")
ncatbot_utils.get_log = lambda *_args: SimpleNamespace(
    info=lambda *_: None,
    warning=lambda *_: None,
    error=lambda *_: None,
)
bot_state = ModuleType("bot_state")
bot_state.ignore_if_sleeping = lambda: lambda func: func
analyze = ModuleType("plugins.mh.analyze")
analyze.MonsterAnalyzer = object
aiohttp = ModuleType("aiohttp")

sys.modules.update(
    {
        "ncatbot.core": ncatbot_core,
        "ncatbot.event.qq": ncatbot_event_qq,
        "ncatbot.plugin": ncatbot_plugin,
        "ncatbot.utils": ncatbot_utils,
        "bot_state": bot_state,
        "plugins.mh.analyze": analyze,
        "aiohttp": aiohttp,
    }
)

from plugins.mh.mh import mh


def make_plugin():
    plugin = mh.__new__(mh)
    plugin.mhw = []
    plugin.mhr = []
    plugin._save_team_codes = Mock()
    plugin.api = SimpleNamespace(
        qq=SimpleNamespace(post_group_msg=AsyncMock())
    )
    return plugin


class TeamCodeRecognitionTests(IsolatedAsyncioTestCase):
    async def test_pure_numbers_are_not_recorded_as_team_codes(self):
        plugin = make_plugin()

        await plugin.on_group_message(
            SimpleNamespace(raw_message="123456789012", group_id=100)
        )

        self.assertEqual([], plugin.mhw)
        plugin.api.qq.post_group_msg.assert_not_awaited()

    async def test_pure_letters_are_not_recorded_as_team_codes(self):
        plugin = make_plugin()

        await plugin.on_group_message(
            SimpleNamespace(raw_message="abcdefghijklmnop", group_id=100)
        )

        self.assertEqual([], plugin.mhr)
        plugin.api.qq.post_group_msg.assert_not_awaited()

    async def test_alphanumeric_team_code_is_still_recorded(self):
        plugin = make_plugin()

        await plugin.on_group_message(
            SimpleNamespace(raw_message="ABCD1234EFGH", group_id=100)
        )

        self.assertEqual(["ABCD1234EFGH"], plugin.mhw)
        plugin.api.qq.post_group_msg.assert_awaited_once()
