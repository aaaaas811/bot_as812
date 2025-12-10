# 全局 bot 状态模块，提供简单的睡眠标志接口
_sleeping = False


def set_sleep(flag: bool):
    global _sleeping
    _sleeping = bool(flag)


def is_sleeping() -> bool:
    return _sleeping
