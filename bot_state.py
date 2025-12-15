# 配置：特殊监控账号
MASTER_UIN = "3196611630"
MARIA_UIN = "1634483575"
ADMIN_UINS = {MASTER_UIN, MARIA_UIN}
_sleeping = False
def set_sleep(flag: bool):
    global _sleeping
    _sleeping = bool(flag)


def is_sleeping() -> bool:
    return _sleeping


from functools import wraps
from typing import Iterable, Optional

def ignore_if_sleeping(allow_uins: Optional[Iterable[str]] = None, user_attr: str = "user_id"):
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
            if is_sleeping():
                uid = getattr(msg, user_attr, None)
                if uid is None or str(uid) not in allow_set:
                    return  # 睡眠且非放行用户，直接返回不处理
            return await func(*args, **kwargs)
        return wrapper
    return decorator