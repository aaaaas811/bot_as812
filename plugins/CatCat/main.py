import asyncio
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core.message import GroupMessage, PrivateMessage
from ncatbot.utils.logger import get_log

from .AiChat import gene_response, active_response

import yaml
import bot_state

_log = get_log()

bot = CompatibleEnrollment  # 兼容回调函数注册器

config = {}  # 全局配置字典

class CatCat(BasePlugin):
    name = "CatCat"  # 插件名称
    version = "1.0.6"  # 插件版本


    @bot.group_event
    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, msg: GroupMessage):
        # 定义的回调函数
        if msg.raw_message == "测试CatCat" and msg.user_id == bot_state.MASTER_UIN:
            await self.api.post_group_msg(msg.group_id, text="NCatBot插件CatCat测试成功喵")

    @bot.group_event
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, msg: GroupMessage):
        _log.info(f"{msg.sender.nickname}({msg.sender.user_id}): {msg.raw_message[:10]}")
        response = await gene_response(config["api_key"], msg, config.get("cat_prompt", ""))
        if response:
            await self.api.post_group_msg(msg.group_id, response)
        else:
            # 尝试主动回复
            if msg.group_id == config["active_group_id"]:
                active_resp = await active_response(config["api_key"], config.get("cat_prompt", ""), config["active_group_id"])
                if active_resp:
                    await self.api.post_group_msg(msg.group_id, active_resp)

    @bot.private_event
    @bot_state.ignore_if_sleeping()
    async def on_private_message(self, msg: PrivateMessage):
        global config
        if msg.user_id != config.get("super_user"):  # 修改判断条件
            return
        message = msg.raw_message.strip()
        if message == "view_config":
            # 查看所有配置项，除了api_key和cat_prompt
            config_lines = []
            for key, value in config.items():
                if key not in ["api_key", "cat_prompt"]:
                    config_lines.append(f"{key}: {value}")
            config_text = "\n".join(config_lines)
            await self.api.post_private_msg(msg.sender.user_id, text=f"当前配置（除api_key和cat_prompt外）：\n{config_text}")
        elif message.startswith("set_"):
            # 设置配置项
            parts = message.split(" ", 1)
            if len(parts) < 2:
                await self.api.post_private_msg(msg.sender.user_id, text="格式错误，请使用 set_<key> <value>")
                return
            key = parts[0][4:]  # 去掉"set_"
            value = parts[1]
            if key in config and key != "api_key":
                # 尝试转换类型
                if key in ["active_group_id", "super_user"]:
                    config[key] = str(value)
                elif key in ["active_reply_delay", "context_history", "current_active_delay", "max_history", "max_words", "summary_threshold"]:
                    try:
                        config[key] = int(value)
                    except ValueError:
                        await self.api.post_private_msg(msg.sender.user_id, text=f"{key} 必须是整数")
                        return
                elif key == "random_range":
                    try:
                        config[key] = float(value)
                    except ValueError:
                        await self.api.post_private_msg(msg.sender.user_id, text=f"{key} 必须是浮点数")
                        return
                # 保存到yaml
                with open("plugins/CatCat/config/config.yaml", "w", encoding="utf-8") as f:
                    yaml.safe_dump(config, f, default_flow_style=False)
                await self.api.post_private_msg(msg.sender.user_id, text=f"{key} 设置为 {value} 成功")
            elif key == "cat_prompt":
                # 特殊处理cat_prompt
                with open("plugins/CatCat/config/cat_prompt.txt", "w", encoding="utf-8") as f:
                    f.write(value)
                await self.api.post_private_msg(msg.sender.user_id, text="cat_prompt 设置成功")
            else:
                await self.api.post_private_msg(msg.sender.user_id, text=f"未知配置项: {key}")
        elif message == "prompt":
            # 保留原有功能
            with open("plugins/CatCat/config/cat_prompt.txt", "r", encoding="utf-8") as f:
                cat_prompt = f.read()
            await self.api.post_private_msg(msg.sender.user_id, text=cat_prompt)
        elif message.startswith("set_prompt"):
            # 保留原有set_prompt指令
            value = message[10:].strip()
            with open("plugins/CatCat/config/cat_prompt.txt", "w", encoding="utf-8") as f:
                f.write(value)
            await self.api.post_private_msg(msg.sender.user_id, text="设置成功")

    async def on_load(self):
        print("插件加载中……")
        # 从 config/config.yaml 中读取配置
        global config
        with open("plugins/CatCat/config/config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 读取cat_prompt
        with open("plugins/CatCat/config/cat_prompt.txt", "r", encoding="utf-8") as f:
            config["cat_prompt"] = f.read()

        # 插件加载时执行的操作, 可缺省
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
