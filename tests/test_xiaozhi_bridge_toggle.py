import sys
from types import SimpleNamespace
from types import ModuleType
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


class _Registrar:
    def on_private_message(self):
        return lambda func: func


class _Plugin:
    pass


ncatbot_core = ModuleType("ncatbot.core")
ncatbot_core.registrar = SimpleNamespace(qq=_Registrar())
ncatbot_event_qq = ModuleType("ncatbot.event.qq")
ncatbot_event_qq.PrivateMessageEvent = object
ncatbot_plugin = ModuleType("ncatbot.plugin")
ncatbot_plugin.NcatBotPlugin = _Plugin
ncatbot_logger = ModuleType("ncatbot.utils.logger")
ncatbot_logger.get_log = lambda: SimpleNamespace(
    info=lambda *_: None,
    warning=lambda *_: None,
    error=lambda *_: None,
)

connection = ModuleType("plugins.as812_xiaozhi_bridge.connection")
connection.ConnectionManager = object
connection.ConnectionError = type("ConnectionError", (Exception,), {})
connection.ResponseTimeout = type("ResponseTimeout", (Exception,), {})
yaml = ModuleType("yaml")
yaml.safe_load = lambda _stream: {}

sys.modules.update(
    {
        "ncatbot.core": ncatbot_core,
        "ncatbot.event.qq": ncatbot_event_qq,
        "ncatbot.plugin": ncatbot_plugin,
        "ncatbot.utils.logger": ncatbot_logger,
        "plugins.as812_xiaozhi_bridge.connection": connection,
        "yaml": yaml,
    }
)

from plugins.as812_xiaozhi_bridge.main import XiaozhiBridge


def make_plugin():
    plugin = XiaozhiBridge.__new__(XiaozhiBridge)
    plugin._config = {
        "messaging": {"super_user": "10001", "allowed_users": []}
    }
    plugin._conn_manager = SimpleNamespace(
        send_message=AsyncMock(return_value="小智回复"),
        close_all=AsyncMock(),
    )
    plugin._qq_post_private_msg = AsyncMock()
    plugin._send_private_response = AsyncMock()
    return plugin


def private_message(text):
    return SimpleNamespace(
        user_id=10001,
        raw_message=text,
        sender=SimpleNamespace(nickname="测试用户"),
    )


class XiaozhiBridgeToggleTests(IsolatedAsyncioTestCase):
    async def test_private_messages_do_not_reach_xiaozhi_by_default(self):
        plugin = make_plugin()
        plugin._enabled = False

        await plugin.on_private_message(private_message("你好"))

        plugin._conn_manager.send_message.assert_not_awaited()
        plugin._qq_post_private_msg.assert_not_awaited()

    async def test_enable_command_allows_following_private_messages(self):
        plugin = make_plugin()
        plugin._enabled = False

        await plugin.on_private_message(private_message("开启小智"))
        plugin._qq_post_private_msg.assert_awaited_once_with(
            10001, text="小智桥接已开启"
        )

        plugin._qq_post_private_msg.reset_mock()
        await plugin.on_private_message(private_message("你好"))

        plugin._conn_manager.send_message.assert_awaited_once()
        plugin._send_private_response.assert_awaited_once_with(10001, "小智回复")

    async def test_disable_command_stops_messages_and_closes_connections(self):
        plugin = make_plugin()
        plugin._enabled = True

        await plugin.on_private_message(private_message("关闭小智"))

        plugin._conn_manager.close_all.assert_awaited_once_with()
        plugin._qq_post_private_msg.assert_awaited_once_with(
            10001, text="小智桥接已关闭"
        )

        plugin._qq_post_private_msg.reset_mock()
        await plugin.on_private_message(private_message("你好"))

        plugin._conn_manager.send_message.assert_not_awaited()
        plugin._qq_post_private_msg.assert_not_awaited()
