import logging
import os

import aiohttp
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types.qq import ForwardConstructor

from .client import LectureClient, LectureError
from .formatter import format_lectures

LOG = logging.getLogger(__name__)


class SEULectures(NcatBotPlugin):
    name = "seu_lectures"
    version = "1.0.0"

    async def on_load(self):
        self.client = LectureClient(os.environ.get("SEU_USERNAME", ""), os.environ.get("SEU_PASSWORD", ""),
                                    network=os.environ.get("SEU_NETWORK", "auto"))

    async def on_close(self):
        await self.client.close()

    @registrar.qq.on_command("/讲座")
    async def lectures(self, event: GroupMessageEvent | PrivateMessageEvent):
        try:
            texts = format_lectures(await self.client.fetch())
        except LectureError as exc:
            await event.reply(str(exc))
            return
        except TimeoutError:
            await event.reply("讲座查询超时，请稍后重试。")
            return
        except aiohttp.ClientError:
            await event.reply("暂时无法连接学校讲座系统，请稍后重试。")
            return
        try:
            # Split large results without dropping lectures.
            for offset in range(0, len(texts), 50):
                forward = ForwardConstructor(user_id=str(event.self_id), nickname="SEU 讲座助手")
                for text in texts[offset:offset + 50]:
                    forward.attach_text(text)
                if isinstance(event, GroupMessageEvent):
                    await self.api.qq.post_group_forward_msg(event.group_id, forward.build())
                else:
                    await self.api.qq.post_private_forward_msg(event.user_id, forward.build())
        except Exception as exc:
            LOG.warning("[seu_lectures] forward failed: %s", type(exc).__name__)
            await event.reply("讲座聊天记录发送失败，请稍后重试。")
