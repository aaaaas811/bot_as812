import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch


MODULE_PATH = Path(__file__).parents[1] / "plugins" / "as812" / "handlers" / "command_handler.py"


def load_command_handler():
    package = "_as812_emoji_like_test"
    modules = {}
    for name in (package, f"{package}.handlers", f"{package}.core", "ncatbot", "ncatbot.utils"):
        module = ModuleType(name)
        module.__path__ = []
        modules[name] = module

    config = ModuleType(f"{package}.core.config_manager")
    config.ConfigManager = object
    config.PromptManager = object
    modules[config.__name__] = config

    log_manager = ModuleType(f"{package}.core.log_manager")
    log_manager.LogManager = object
    modules[log_manager.__name__] = log_manager

    logger = ModuleType("ncatbot.utils.logger")
    logger.get_log = lambda: logging.getLogger(__name__)
    modules[logger.__name__] = logger

    spec = importlib.util.spec_from_file_location(f"{package}.handlers.command_handler", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module.CommandHandler


class EmojiLikeTests(unittest.IsolatedAsyncioTestCase):
    async def test_circled_congratulation_reaction(self):
        """Replying with either presentation of ㊗ sends its Unicode code point to QQ."""
        handler = load_command_handler()(None, None, None)

        for emoji in ("㊗", "㊗️"):
            with self.subTest(emoji=emoji):
                api = SimpleNamespace(set_msg_emoji_like=AsyncMock(), post_group_msg=AsyncMock())
                await handler.handle_group_emoji_like(
                    api, "123", "456", f"/贴表情 {emoji}",
                    reply_id="789", message_array=[{"type": "text", "text": f"/贴表情 {emoji}"}],
                )
                api.set_msg_emoji_like.assert_awaited_once_with("789", "12951")
                api.post_group_msg.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
