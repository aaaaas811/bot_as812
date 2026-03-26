"""Project-local compatibility patch for ncatbot SDK export regressions."""

from __future__ import annotations


def patch_ncatbot_sdk() -> None:
    try:
        import ncatbot.utils as _utils
    except Exception:
        return

    if not hasattr(_utils, "run_coroutine"):
        try:
            from ncatbot.utils.thread_pool import run_coroutine as _run_coroutine

            _utils.run_coroutine = _run_coroutine
        except Exception:
            pass

    try:
        from ncatbot.adapter.napcat.constants import (
            INSTALL_SCRIPT_URL,
            LINUX_NAPCAT_DIR,
            NAPCAT_WEBUI_SALT,
            PYPI_URL,
            WINDOWS_NAPCAT_DIR,
        )

        _consts = {
            "INSTALL_SCRIPT_URL": INSTALL_SCRIPT_URL,
            "WINDOWS_NAPCAT_DIR": WINDOWS_NAPCAT_DIR,
            "LINUX_NAPCAT_DIR": LINUX_NAPCAT_DIR,
            "PYPI_URL": PYPI_URL,
            "NAPCAT_WEBUI_SALT": NAPCAT_WEBUI_SALT,
        }

        for _name, _value in _consts.items():
            if not hasattr(_utils, _name):
                setattr(_utils, _name, _value)
    except Exception:
        pass

    try:
        import ncatbot.core as _core
        from ncatbot.core.event import (
            BaseMessageEvent,
            GroupMessageEvent,
            MessageArray,
            MessageSentEvent,
            MetaEvent,
            NoticeEvent,
            PrivateMessageEvent,
            RequestEvent,
        )
        from ncatbot.core.event.message_segment import Image

        _legacy_exports = {
            "BaseMessageEvent": BaseMessageEvent,
            "GroupMessageEvent": GroupMessageEvent,
            "PrivateMessageEvent": PrivateMessageEvent,
            "MessageSentEvent": MessageSentEvent,
            "NoticeEvent": NoticeEvent,
            "RequestEvent": RequestEvent,
            "MetaEvent": MetaEvent,
            "MessageArray": MessageArray,
            "MessageChain": MessageArray,
            "Image": Image,
            "BaseMessage": BaseMessageEvent,
            "GroupMessage": GroupMessageEvent,
            "PrivateMessage": PrivateMessageEvent,
        }

        for _name, _value in _legacy_exports.items():
            if not hasattr(_core, _name):
                setattr(_core, _name, _value)
    except Exception:
        pass

    try:
        import ncatbot.core as _core
        from ncatbot.core.client import BotClient

        if not hasattr(_core, "BotClient"):
            _core.BotClient = BotClient
    except Exception:
        pass

    try:
        import ncatbot.plugin as _plugin

        if not hasattr(_plugin, "CompatibleEnrollment"):
            from ncatbot.plugin.compatible_enrollment import CompatibleEnrollment

            _plugin.CompatibleEnrollment = CompatibleEnrollment

        if not hasattr(_plugin, "Event"):
            from ncatbot.core.dispatcher import Event

            _plugin.Event = Event
    except Exception:
        pass

    # 6) Legacy API shim: self.api.post_group_msg(...) -> self.api.qq.post_group_msg(...)
    try:
        from ncatbot.api.client import BotAPIClient

        if not hasattr(BotAPIClient, "_legacy_qq_shim_installed"):
            _orig_getattr = getattr(BotAPIClient, "__getattr__", None)

            def _legacy_getattr(self, name):
                if _orig_getattr is not None:
                    try:
                        return _orig_getattr(self, name)
                    except Exception:
                        pass

                qq_client = getattr(self, "_platforms", {}).get("qq")
                if qq_client is not None and hasattr(qq_client, name):
                    return getattr(qq_client, name)
                raise AttributeError(f"BotAPIClient has no attribute '{name}'")

            BotAPIClient.__getattr__ = _legacy_getattr
            BotAPIClient._legacy_qq_shim_installed = True
    except Exception:
        pass


patch_ncatbot_sdk()
