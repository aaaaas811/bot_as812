"""AstrBot Web API 符号的最小占位。

NcatBot 5.x 没有 AstrBot 的 Plugin Pages / ``context.register_web_api`` 机制，
因此相关的 web API 处理器不会被注册调用；这里仅提供占位符号以满足导入。
"""


class _Request:
    @property
    def query(self):
        return {}

    @property
    def path_params(self):
        return {}

    async def json(self, default=None):
        return default if default is not None else {}


request = _Request()


def json_response(payload, *args, **kwargs):
    return {"ok": True, "data": payload}


def error_response(message, status_code=500, *args, **kwargs):
    return {"ok": False, "status_code": status_code, "message": str(message)}
