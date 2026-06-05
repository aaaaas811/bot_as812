# 配置：特殊监控账号
MASTER_UIN = "3196611630"
MARIA_UIN = "1634483575"
HUNGRY_UIN = "249638876"
ADMIN_UINS = {MASTER_UIN, MARIA_UIN, HUNGRY_UIN}

_sleeping = False
_debug_mode = False
_debug_group = "1042029905"


def set_sleep(flag: bool):
    global _sleeping
    _sleeping = bool(flag)


def is_sleeping() -> bool:
    return _sleeping


def set_debug_mode(flag: bool):
    global _debug_mode
    _debug_mode = bool(flag)


def is_debug_mode() -> bool:
    return _debug_mode


def get_debug_group() -> str:
    return _debug_group


from functools import wraps
from typing import Iterable, Optional


def ignore_if_sleeping(allow_uins: Optional[Iterable[str]] = None, user_attr: str = "user_id", allow_group_admins: bool = False):
    """
    装饰器：若处于睡眠态则阻止处理；allow_uins 列表中的 user_id 始终放行。
    user_attr 指定消息对象中用于比较的属性名（默认 user_id，GroupMessage/PrivateMessage 均适用）。
    """
    allow_set = set(map(str, allow_uins)) if allow_uins else set()

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 尝试从参数中找到消息对象以获取 user_id
            msg = None
            for a in list(args) + list(kwargs.values()):
                if hasattr(a, user_attr):
                    msg = a
                    break

            # 调试模式：只允许指定群活跃
            if _debug_mode and msg is not None:
                gid = getattr(msg, "group_id", None)
                if gid is not None and str(gid) != _debug_group:
                    return

            if is_sleeping():
                uid = getattr(msg, user_attr, None)
                # 首先按显式白名单判断
                if uid is not None and str(uid) in allow_set:
                    return await func(*args, **kwargs)

                # 如果允许群管理员放行，且消息对象包含群内角色信息，则按角色判断
                if allow_group_admins and msg is not None:
                    # 常见实现：GroupMessage 包含 sender 对象，且有 role 属性（'owner'|'admin'|'member'）
                    sender = getattr(msg, "sender", None)
                    role = None
                    if sender is not None:
                        role = getattr(sender, "role", None)
                    # 有些实现可能把角色放在 msg.role 或 msg.sender.role_name 等，这里做容错
                    if role is None:
                        role = getattr(msg, "role", None)
                    if role is not None and str(role).lower() in {"admin", "owner"}:
                        return await func(*args, **kwargs)

                # 否则阻止处理
                return
            return await func(*args, **kwargs)
        return wrapper
    return decorator