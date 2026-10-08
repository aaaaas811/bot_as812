"""AstrBot ``Star`` 基类与 ``Context`` 的 NcatBot 兼容实现。"""

from __future__ import annotations

from ncatbot.plugin import NcatBotPlugin

from .event import _chain_to_messagearray


def _split_session(session) -> tuple[str, str]:
    """返回 (kind, target_id)。kind ∈ {group, private}。"""
    text = str(session or "").strip()
    if not text:
        return "group", ""
    # 形如 "platform:GroupMessage:0_12345" 或 "platform:PrivateMessage:0_67890"
    parts = text.split(":", 2)
    body = parts[2] if len(parts) == 3 else text
    if "_" in body:
        body = body.rsplit("_", 1)[-1]
    kind = "private" if "private" in text.lower() or "friend" in text.lower() else "group"
    return kind, body


class _PlatformMeta:
    name = "qq"


class _StubPlatform:
    """QQ 官方机器人平台占位；让 QQ 指令面板同步优雅降级。"""

    appid = ""
    secret = ""

    def meta(self) -> _PlatformMeta:
        return _PlatformMeta()


class Context:
    """模拟 AstrBot ``Context``，把 send_message 转发为 NcatBot 消息发送。"""

    def __init__(self, plugin):
        self._plugin = plugin

    @property
    def plugin(self):
        return self._plugin

    async def send_message(self, session, chain) -> None:
        plugin = self._plugin
        api = getattr(plugin, "api", None)
        qq = getattr(api, "qq", None) if api is not None else None
        if qq is None:
            return
        msg = _chain_to_messagearray(chain)
        if not msg:
            return
        kind, target = _split_session(session)
        try:
            if kind == "private" and target:
                await qq.post_private_array_msg(user_id=target, msg=msg)
            elif target:
                await qq.post_group_array_msg(group_id=target, msg=msg)
        except Exception:
            from ..src.shared.logging import logger as _log
            _log.exception("发送消息失败 (session=%s)", session)

    def get_using_provider(self):
        """AstrBot LLM 翻译在 ncatbot 下不可用 → 返回 None（调用方优雅降级）。"""
        return None

    def get_platform_inst(self, platform_id=None) -> _StubPlatform:
        return _StubPlatform()

    def get_platform(self, name=None) -> _StubPlatform:
        return _StubPlatform()

    def register_web_api(self, *args, **kwargs) -> None:
        """AstrBot Plugin Pages 在 ncatbot 下无对应注册点，静默跳过。"""
        return None


class Star(NcatBotPlugin):
    """AstrBot ``Star`` 的 NcatBot 兼容基类：直接复用 NcatBotPlugin。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
