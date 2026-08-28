from datetime import datetime


def is_scheduled_sleep_time(current_time: datetime | None = None) -> bool:
    """判断本机时间是否处于每日 00:00-08:00 睡眠时段。"""
    return (current_time or datetime.now()).hour < 8
