"""Public lecture information; shared account booking fields are never shown."""
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))


def parse_time(value):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=SHANGHAI)
        except ValueError:
            pass
    return None


def number(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def booking_status(row, now):
    start, end = parse_time(row.get("YYKSSJ")), parse_time(row.get("YYJSSJ"))
    if start and now < start:
        return "未开放"
    if end and now > end:
        return "预约已截止"
    capacity, booked = number(row.get("HDZRS")), number(row.get("YYRS"))
    if capacity is not None and capacity > 0 and booked is not None and booked >= capacity:
        return "已满"
    return "可预约" if start and end else "状态未知"


def format_lectures(rows, now=None):
    now = next((t for row in rows if (t := parse_time(row.get("XTDQSJ")))),
               now or datetime.now(SHANGHAI))
    current = [row for row in rows if str(row.get("FBZT")) != "-1"
               and not ((end := parse_time(row.get("HDJSSJ"))) and end <= now)]
    current.sort(key=lambda row: (parse_time(row.get("JZSJ")) or datetime.max.replace(tzinfo=SHANGHAI),
                                  str(row.get("JZMC") or "")))
    texts = [f"东南大学 · 当前素质讲座\n共 {len(current)} 场\n数据时间：{now:%Y-%m-%d %H:%M:%S}（北京时间）"
             "\n结果最多缓存 60 秒，预约状态以学校系统为准。"]
    if not current:
        texts.append("暂无尚未结束的讲座。")
    for index, row in enumerate(current, 1):
        capacity, booked = number(row.get("HDZRS")), number(row.get("YYRS"))
        seats = (f"已预约 {booked}/{capacity}，剩余 {max(0, capacity - booked)}"
                 if capacity is not None and capacity > 0 and booked is not None and booked >= 0 else "名额未知")
        start, end = parse_time(row.get("JZSJ")), parse_time(row.get("HDJSSJ"))
        progress = "进行中" if start and end and start <= now < end else ("未开始" if start and now < start else "时间待确认")
        def value(key):
            return str(row.get(key) or "未提供").strip()[:500]
        texts.append(f"{index}. {value('JZMC')}\n讲座状态：{progress}\n预约状态：{booking_status(row, now)}"
                     f"\n时间：{value('JZSJ')} ～ {value('HDJSSJ')}\n地点：{value('JZDD')}"
                     f"\n主讲人：{value('ZJR')}\n系列：{value('JZXL_DISPLAY')}\n主办：{value('ZBF')}"
                     f"\n名额：{seats}\n预约时间：{value('YYKSSJ')} ～ {value('YYJSSJ')}")
    return texts
