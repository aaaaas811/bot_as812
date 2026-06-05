"""as812_xiaozhi_bridge 插件 — 将 QQ 私聊桥接到 xiaozhi-esp32-server"""
import sdk_compat  # noqa: F401

import os
import yaml
from pathlib import Path

from ncatbot.core import registrar
from ncatbot.event.qq import PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.utils.logger import get_log

from .connection import ConnectionManager, ConnectionError, ResponseTimeout

_log = get_log()

PLUGIN_DIR = Path(__file__).parent
DEFAULT_CONFIG_PATH = PLUGIN_DIR / "config" / "config.yaml"


class XiaozhiBridge(NcatBotPlugin):
    name = "as812_xiaozhi_bridge"
    version = "0.1.0"

    async def on_load(self):
        self._config = self._load_config()
        self._conn_manager = ConnectionManager(self._config)
        _log.info("[xiaozhi_bridge] 插件已加载")

    async def on_unload(self):
        await self._conn_manager.close_all()
        _log.info("[xiaozhi_bridge] 插件已卸载")

    @registrar.qq.on_private_message()
    async def on_private_message(self, event: PrivateMessageEvent):
        user_id = str(event.user_id)

        if not self._is_authorized(user_id):
            return

        raw_text = (event.raw_message or "").strip()
        if not raw_text:
            return

        # 跳过转述命令，避免与 as812 插件冲突
        if raw_text.startswith("帮我说") or raw_text.startswith("安安帮我说"):
            return

        # 获取发送者昵称
        sender_name = ""
        try:
            sender = getattr(event, "sender", None)
            if sender is not None:
                sender_name = getattr(sender, "nickname", "") or ""
        except Exception:
            pass

        # 添加桥接前缀，让 LLM 知道这是别人通过 bot 转达的消息
        bridged_text = f"[QQ转述] 用户{sender_name}({user_id})对你说：{raw_text}"

        msg_cfg = self._config.get("messaging", {})
        status_reply = msg_cfg.get("status_reply", "")
        if status_reply:
            await self._qq_post_private_msg(event.user_id, text=status_reply)

        try:
            response = await self._conn_manager.send_message(
                user_id, bridged_text,
                sender_id=user_id,
                sender_name=sender_name,
            )
            if response:
                await self._send_private_response(event.user_id, response)
            else:
                await self._qq_post_private_msg(
                    event.user_id, text="小智没有回复内容..."
                )
        except ConnectionError as e:
            _log.warning(f"[xiaozhi_bridge] 连接错误: {e}")
        except ResponseTimeout:
            _log.warning(f"[xiaozhi_bridge] 响应超时 user={user_id}")
            await self._qq_post_private_msg(
                event.user_id, text="xiaozhi响应超时，请稍后再试"
            )
        except Exception as e:
            _log.error(f"[xiaozhi_bridge] 未知错误: {e}")
            await self._qq_post_private_msg(
                event.user_id, text="与xiaozhi通信时发生错误"
            )

    def _is_authorized(self, user_id: str) -> bool:
        msg_cfg = self._config.get("messaging", {})
        super_user = msg_cfg.get("super_user", "")
        allowed = msg_cfg.get("allowed_users", [])
        if allowed:
            return user_id == super_user or user_id in allowed
        return user_id == super_user

    def _load_config(self) -> dict:
        try:
            if os.path.exists(DEFAULT_CONFIG_PATH):
                with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            _log.error(f"[xiaozhi_bridge] 加载配置失败: {e}")
        return {}

    async def _send_private_response(self, user_id: int, text: str):
        """发送长文本回复，超过 2000 字符时分段发送"""
        if len(text) <= 2000:
            await self._qq_post_private_msg(user_id, text=text)
            return

        chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
        for chunk in chunks:
            await self._qq_post_private_msg(user_id, text=chunk)

    async def _qq_post_private_msg(self, user_id, **kwargs):
        """兼容不同 NcatBot SDK 版本的私聊发送"""
        qq_api = getattr(self.api, "qq", None)
        if qq_api is not None and hasattr(qq_api, "post_private_msg"):
            return await qq_api.post_private_msg(user_id, **kwargs)
        if hasattr(self.api, "post_private_msg"):
            return await self.api.post_private_msg(user_id, **kwargs)
        raise AttributeError("当前 SDK 未提供 post_private_msg 接口")
