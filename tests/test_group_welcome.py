import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "_31966_plugin"))


class _DecoratorRegistrar:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: lambda func: func


class _Registrar(_DecoratorRegistrar):
    qq = _DecoratorRegistrar()


class _NcatBotPlugin:
    pass


sys.modules.setdefault(
    "ncatbot.core",
    SimpleNamespace(registrar=_Registrar()),
)
sys.modules.setdefault(
    "ncatbot.event.qq",
    SimpleNamespace(
        GroupIncreaseEvent=object,
        GroupMessageEvent=object,
        NoticeEvent=object,
        PrivateMessageEvent=object,
    ),
)
sys.modules.setdefault("ncatbot.plugin", SimpleNamespace(NcatBotPlugin=_NcatBotPlugin))
sys.modules.setdefault("uapi", SimpleNamespace(UapiClient=object))
sys.modules.setdefault("uapi.errors", SimpleNamespace(UapiError=Exception))
sys.modules.setdefault(
    "as812.core.config_manager", SimpleNamespace(ConfigManager=object)
)
sys.modules.setdefault("as812.core.log_manager", SimpleNamespace(LogManager=object))
sys.modules.setdefault("as812.models.message_models", SimpleNamespace(BotResponse=object))

from plugins._31966_plugin.plugin import PluginPlugin


class GroupWelcomeTest(unittest.IsolatedAsyncioTestCase):
    async def test_target_group_does_not_receive_welcome(self):
        post_group_msg = AsyncMock()
        plugin = SimpleNamespace(
            api=SimpleNamespace(qq=SimpleNamespace(post_group_msg=post_group_msg))
        )
        event = SimpleNamespace(group_id=616492313)

        await PluginPlugin.on_group_member_join.__wrapped__(plugin, event)

        post_group_msg.assert_not_awaited()

    async def test_other_group_still_receives_welcome(self):
        post_group_msg = AsyncMock()
        plugin = SimpleNamespace(
            api=SimpleNamespace(qq=SimpleNamespace(post_group_msg=post_group_msg))
        )
        event = SimpleNamespace(group_id=123456789)

        await PluginPlugin.on_group_member_join.__wrapped__(plugin, event)

        post_group_msg.assert_awaited_once_with(
            group_id=123456789,
            text="新天尊玩什么太刀",
        )


if __name__ == "__main__":
    unittest.main()
