# main.py

import asyncio
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core.message import GroupMessage, PrivateMessage
from ncatbot.utils.logger import get_log

from .AiChat import gene_response

import yaml
import bot_state

_log = get_log()

bot = CompatibleEnrollment  # 兼容回调函数注册器

api_key = ""
cat_prompt = ""
super_user = ""


class CatCat(BasePlugin):
    name = "CatCat"  # 插件名称
    version = "1.0.6"  # 插件版本


    @bot.group_event
    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, msg: GroupMessage):
        # 定义的回调函数
        if msg.raw_message == "测试CatCat":
            await self.api.post_group_msg(msg.group_id, text="NCatBot插件CatCat测试成功喵")

    @bot.group_event
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, msg: GroupMessage):
        _log.info(f"{msg.sender.nickname}({msg.sender.user_id}): {msg.raw_message[:10]}")
        response = await gene_response(api_key, msg, cat_prompt)
        # await self.api.post_private_msg(super_user, text=f"CatCat回复：{response}")
        if response:
            await self.api.post_group_msg(msg.group_id, response)

    @bot.private_event
    @bot_state.ignore_if_sleeping()
    async def on_private_message(self, msg: PrivateMessage):
        global cat_prompt
        if msg.user_id != super_user:  # 修改判断条件
            return
        if msg.raw_message == "prompt":
            await self.api.post_private_msg(msg.sender.user_id, text=cat_prompt)
        elif msg.raw_message[:10] == "set_prompt":
            cat_prompt = msg.raw_message[10:]
            with open("plugins/CatCat/config/cat_prompt.txt", "w", encoding="utf-8") as f:
                f.write(cat_prompt.strip())
            await self.api.post_private_msg(msg.sender.user_id, text="设置成功")

    async def on_load(self):
        print("插件加载中……")
        # 从 config/config.yaml 中读取配置
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
            global api_key
            api_key = config_data["api_key"]
            global super_user
            super_user = config_data["manager_id"]

        with open("plugins/CatCat/config/cat_prompt.txt", "r", encoding="utf-8") as f:
            global cat_prompt
            cat_prompt = f.read()

        # 插件加载时执行的操作, 可缺省
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        # 启动后台定时任务：定期触发 gene_response（无需群消息）
        try:
            self._periodic_task = asyncio.create_task(self._periodic_trigger())
        except Exception as e:
            _log.error(f"启动 CatCat 定时任务失败: {e}")

    async def _periodic_trigger(self):
        # 定时唤醒，调用 gene_response; gene_response 内部会根据历史判断是否真正回复
        # 这里使用较短的轮询间隔以便及时触发（实际发送由 message_delay 控制）
        interval = 5
        # 尝试从配置读取更合适的轮询或间隔值
        try:
            with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                interval = int(cfg.get("poll_interval", interval))
        except Exception:
            pass
        while True:
            try:
                # 如果 super_user 未设置，尝试跳过
                if super_user:
                    response = await gene_response(api_key, msg=None, cat_prompt=cat_prompt, group_id=super_user)
                    if response:
                        await self.api.post_group_msg(super_user, response)
            except Exception as e:
                _log.error(f"CatCat 定时触发出错: {e}")
            await asyncio.sleep(interval)
