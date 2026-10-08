"""AstrBot 事件/命令系统在 NcatBot 5.x 上的兼容层。

核心思路（与 AstrBot 插件的 async-generator 处理模型兼容）：

- AstrBot 的 handler 是 ``async def`` + ``yield event.plain_result(...)`` 的
  **异步生成器**，框架会逐个消费并发送 yield 出来的结果。
- NcatBot 要求 handler 必须是真正的协程函数（``asyncio.iscoroutinefunction``），
  且通过 ``@registrar.on_*`` 注册。
- 因此本层把每个 AstrBot 命令 handler 包装成一个**普通协程**（drain wrapper）并
  注册到 ``registrar.on_message()``；wrapper 内部 ``async for`` 消费原异步生成器，
  并把每个 yield 出的结果发送出去。
- 原方法作为 async-generator 保留为类属性，因此插件内部
  ``async for r in self.some_async_gen(...)`` 的调用仍然成立。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import shlex
from typing import Any, Callable, List, Optional, Tuple

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import MessageArray, PlainText
from ncatbot.types import Image as NCImage

__all__ = [
    "filter",
    "AstrMessageEvent",
    "MessageChain",
    "EventMessageType",
    "PermissionType",
]

_POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD
_KEYWORD = inspect.Parameter.KEYWORD_ONLY


class PermissionType:
    ADMIN = "admin"
    MEMBER = "member"
    OWNER = "owner"
    ROOT = "root"


class EventMessageType:
    ALL = "all"
    GROUP = "group"
    PRIVATE = "private"


# 可通过 config 追加的超级管理员 QQ 号（可选）
_ADMIN_WHITELIST: set[str] = set()


def set_admin_whitelist(users) -> None:
    global _ADMIN_WHITELIST
    _ADMIN_WHITELIST = {str(u) for u in (users or []) if u}


def _resolve_permission(pt: Optional[str], entity) -> bool:
    """根据 permission_type 判断发送者是否有权限。"""
    if pt in (None, PermissionType.MEMBER):
        return True
    uid = str(getattr(entity, "user_id", "") or "")
    if pt == PermissionType.ROOT:
        return uid in _ADMIN_WHITELIST
    sender = getattr(entity, "sender", None)
    role = getattr(sender, "role", "") or ""
    if role in ("owner", "admin"):
        return True
    return uid in _ADMIN_WHITELIST


def _tokenize(text: str) -> List[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _strip_command_body(message: str) -> str:
    """去掉命令前导的 '/'（兼容 '.' 与 '。'）。"""
    text = (message or "").strip()
    for prefix in ("/", ".", "。", "／"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _match_command(message: str, names: Tuple[str, ...]) -> Optional[str]:
    """匹配命令前缀（AstrBot 风格：/steam on、/在干嘛 ...）。"""
    if not names:
        return None
    body = _strip_command_body(message)
    if not body:
        return None
    tokens = _tokenize(body)
    for name in names:
        want = [w for w in _tokenize(name) if w]
        if tokens[:len(want)] == want:
            return name
    return None


def _command_rest_tokens(message: str, command_name: str) -> List[str]:
    body = _strip_command_body(message)
    tokens = _tokenize(body)
    want = [w for w in _tokenize(command_name) if w]
    return tokens[len(want):]


def _convert(value: str, ann: Any) -> Any:
    if ann is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if ann is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if ann is bool:
        return str(value).lower() in ("true", "1", "yes")
    return value


def _bind_command_args(func: Callable, command_name: str, message: str) -> dict:
    """按 handler 签名把命令剩余文本绑定为关键字参数。

    与 AstrBot ``filter.command`` 的字符串参数语义尽量一致：
    - 单个 str/无注解参数 → 绑定整段剩余文本；
    - 多个参数 → 按空白分词逐项绑定，类型按注解转换。
    """
    sig = inspect.signature(func)
    params = [
        p
        for p in sig.parameters.values()
        if p.name not in ("self", "event", "cls")
        and p.kind in (_POSITIONAL, _KEYWORD)
    ]
    if not params:
        return {}
    rest_tokens = _command_rest_tokens(message, command_name)
    rest_text = " ".join(rest_tokens)

    # 只有一个参数且不是 int/float → 绑定整段剩余文本（供 query 等使用）
    if len(params) == 1 and params[0].annotation in (str, inspect.Parameter.empty):
        return {params[0].name: _convert(rest_text, params[0].annotation)}

    result: dict = {}
    for i, p in enumerate(params):
        if i < len(rest_tokens):
            result[p.name] = _convert(rest_tokens[i], p.annotation)
        else:
            if p.default is not inspect.Parameter.empty:
                result[p.name] = p.default
            else:
                result[p.name] = ""
    return result


class Out:
    """AstrBot ``event.plain_result / image_result / make_result / chain_result`` 的产物。"""

    __slots__ = ("text", "image", "image_b64", "chain")

    def __init__(self, text: Optional[str] = None, image: Optional[str] = None,
                 image_b64: Optional[str] = None, chain: Optional[list] = None):
        self.text = text
        self.image = image
        self.image_b64 = image_b64
        self.chain = chain

    def base64_image(self, b64: str) -> "Out":
        self.image_b64 = b64
        return self

    def message(self, text: str) -> "Out":
        self.text = text
        return self

    def __repr__(self) -> str:
        return f"Out(text={self.text!r}, image={self.image!r}, b64={bool(self.image_b64)})"


class MessageChain(list):
    """AstrBot ``MessageChain``：一个可迭代的段容器。"""

    def __init__(self, *args):
        super().__init__(*args)


def _local_to_base64(path: str) -> Optional[str]:
    import base64
    import os

    try:
        p = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return "base64://" + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None
    return None


def _image_segment(img: Any) -> NCImage:
    """把 compat Image / str / 本地路径转成 NcatBot Image 段。"""
    if isinstance(img, NCImage):
        return img
    file = getattr(img, "file", None)
    if isinstance(img, str):
        file = img
    if not file:
        return NCImage(file="")
    # 本地文件路径优先转 base64，保证可发送
    if isinstance(file, str) and not file.startswith(("http://", "https://", "base64://")):
        b64 = _local_to_base64(file)
        if b64:
            return NCImage(file=b64)
    return NCImage(file=file)


def _chain_to_messagearray(chain) -> MessageArray:
    arr = MessageArray()
    for seg in chain or []:
        if isinstance(seg, str):
            arr.add_text(seg)
        elif getattr(seg, "text", None) is not None and not hasattr(seg, "file"):
            arr.add_text(getattr(seg, "text"))
        else:
            arr.add_image(_image_segment(seg))
    return arr


class AstrMessageEvent:
    """把 NcatBot 事件实体包装成 AstrBot ``AstrMessageEvent`` 的最小接口。"""

    def __init__(self, entity, plugin):
        self._entity = entity
        self._plugin = plugin
        self._platform_id = "qq"

    @property
    def entity(self):
        return self._entity

    @property
    def is_global_admin(self) -> bool:
        uid = str(getattr(self._entity, "user_id", "") or "")
        return uid in _ADMIN_WHITELIST

    @property
    def is_group(self) -> bool:
        return isinstance(self._entity, GroupMessageEvent)

    def get_group_id(self) -> str:
        gid = getattr(self._entity, "group_id", None)
        return str(gid) if gid else ""

    def get_message_str(self) -> str:
        raw = getattr(self._entity, "raw_message", None)
        if raw:
            return str(raw)
        msg = getattr(self._entity, "message", None)
        return getattr(msg, "text", "") or ""

    @property
    def message_str(self) -> str:
        return self.get_message_str()

    def get_session_id(self) -> str:
        gid = self.get_group_id()
        if gid:
            return gid
        return str(getattr(self._entity, "user_id", "") or "")

    def get_platform_id(self) -> str:
        return self._platform_id

    @property
    def unified_msg_origin(self) -> str:
        if self.is_group:
            return f"{self._platform_id}:GroupMessage:0_{self.get_group_id()}"
        return f"{self._platform_id}:PrivateMessage:0_{self.get_session_id()}"

    def is_at_user(self) -> bool:
        return bool(getattr(self._entity, "message", None) and
                    getattr(self._entity.message, "is_at", lambda *_: False)(
                        getattr(self._entity, "user_id", None)))

    def stop_event(self) -> None:
        data = getattr(self._entity, "_data", None)
        if data is not None:
            try:
                data._propagation_stopped = True
            except Exception:
                pass

    # ---- 结果构造 ----

    def plain_result(self, text: str) -> Out:
        return Out(text=text)

    def image_result(self, path: str) -> Out:
        return Out(image=path)

    def chain_result(self, chain) -> Out:
        return Out(chain=chain)

    def make_result(self) -> Out:
        return Out()

    # ---- 发送 ----

    async def send(self, result: Optional[Out]) -> None:
        if result is None:
            return
        msg = MessageArray()
        if result.text:
            msg.add_text(result.text)
        if result.chain:
            msg = msg + _chain_to_messagearray(result.chain)
        if result.image_b64:
            msg.add_image(NCImage(file="base64://" + result.image_b64))
        elif result.image:
            msg.add_image(_image_segment(result.image))
        if not msg:
            return
        await self._post(msg)

    async def _post(self, msg: MessageArray) -> None:
        api = getattr(self._plugin, "api", None)
        if api is None:
            return
        qq = getattr(api, "qq", None)
        if qq is None:
            return
        try:
            if self.is_group:
                await qq.post_group_array_msg(group_id=self.get_group_id(), msg=msg)
            else:
                await qq.post_private_array_msg(user_id=self.get_session_id(), msg=msg)
        except Exception:
            from ..src.shared.logging import logger as _log
            _log.exception("发送 AstrBot 兼容消息失败 (session=%s)", self.unified_msg_origin)

    async def reply(self, text: Optional[str] = None) -> None:
        await self.send(self.plain_result(text or ""))


def _make_drain_wrapper(func: Callable, names: Tuple[str, ...], is_all: bool) -> Callable:
    async def wrapper(self, event):
        astr = AstrMessageEvent(event, self)
        perm = getattr(func, "__astrbot_permission__", None)
        if not _resolve_permission(perm, event):
            return
        if not is_all:
            matched = _match_command(astr.message_str, names)
            if not matched:
                return
            args = _bind_command_args(func, matched, astr.message_str)
            gen = func(self, astr, **args)
        else:
            gen = func(self, astr)
        async for result in gen:
            await astr.send(result)

    # 保证 __qualname__ 含 "."，使得 flush_pending 能注入 plugin_instance
    wrapper.__qualname__ = "_astrbot_drain." + func.__name__
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _register_command(func: Callable, names: Tuple[str, ...]) -> Callable:
    wrapper = _make_drain_wrapper(func, names, is_all=False)
    # 注册到所有消息（群+私聊），由 wrapper 自行做前缀匹配与权限校验
    registrar.on_message()(wrapper)
    return func  # 类属性保留原始 async-generator，内部 async for 仍可用


def _register_all(func: Callable) -> Callable:
    wrapper = _make_drain_wrapper(func, (None,), is_all=True)
    registrar.on_message()(wrapper)
    return func


class _Filter:
    """AstrBot ``filter`` 装饰器的兼容实现。"""

    PermissionType = PermissionType
    EventMessageType = EventMessageType

    def command(self, *names: str) -> Callable:
        def deco(func: Callable) -> Callable:
            return _register_command(func, tuple(names))
        return deco

    def permission_type(self, pt) -> Callable:
        def deco(func: Callable) -> Callable:
            func.__astrbot_permission__ = pt
            return func
        return deco

    def event_message_type(self, et) -> Callable:
        def deco(func: Callable) -> Callable:
            return _register_all(func)
        return deco


filter = _Filter()
