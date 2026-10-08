"""AstrBot API 兼容层（运行于 NcatBot 5.x）。

把 AstrBot 插件依赖的 ``astrbot.api.*`` 符号在 NcatBot 之上做最小模拟，
使本插件的主体业务逻辑（Steam 监控、渲染、持久化）几乎无需改动即可运行。
"""

from .star import Star, Context
from .event import (
    filter,
    AstrMessageEvent,
    MessageChain,
    EventMessageType,
    PermissionType,
    set_admin_whitelist,
)
from .message_components import Plain, Image
from .web import error_response, json_response, request
from .command_management import list_commands, update_command_permission
from .logger import logger

__all__ = [
    "Star",
    "Context",
    "filter",
    "AstrMessageEvent",
    "MessageChain",
    "EventMessageType",
    "PermissionType",
    "set_admin_whitelist",
    "Plain",
    "Image",
    "error_response",
    "json_response",
    "request",
    "list_commands",
    "update_command_permission",
    "logger",
]
