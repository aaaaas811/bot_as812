"""AstrBot 消息组件兼容层。

在 NcatBot 5.x 上模拟 ``astrbot.api.message_components.Plain / Image`` 的最小接口。
``Plain`` 与 ``Image`` 只是轻量容器，真正发送时由本插件的事件/上下文适配器
转换为 NcatBot ``MessageArray`` 段。
"""

from __future__ import annotations


class Plain:
    """纯文本段。"""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = str(text)


class Image:
    """图片段：支持本地文件路径、URL 与 base64。"""

    __slots__ = ("file", "url", "is_url")

    def __init__(self, file: str | None = None, *, url: str | None = None):
        self.file = file or url or ""
        self.url = url or ""
        self.is_url = bool(url or (file and str(file).startswith(("http://", "https://"))))

    @classmethod
    def fromFileSystem(cls, path: str) -> "Image":
        return cls(file=path)

    @classmethod
    def fromURL(cls, url: str) -> "Image":
        return cls(url=url)

    def __repr__(self) -> str:
        return f"Image(file={self.file!r})"
