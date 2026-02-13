from ncatbot.plugin import BasePlugin, CompatibleEnrollment, Event
from ncatbot.plugin_system import NcatBotPlugin, filter_registry
from ncatbot.core import GroupMessage, PrivateMessage, MessageChain, Image, BaseMessage
from ncatbot.utils.logger import get_log
import bot_state
import requests
import random
import time
import hashlib
import os
import base64
import asyncio
from pathlib import Path
from uapi import UapiClient
from uapi.errors import UapiError

_log = get_log()
global bot_uin
bot_uin = "3024473284"  # 改成你的bot qq号
bot = CompatibleEnrollment  # 兼容回调函数注册器
import re

class Yuri(BasePlugin):
    name = "Yuri"
    version = "1.0"
    author = "as811"
    description = "Yuri图片插件"
    
    ACTIVE_GROUP_ID = 883744030  # 修改为要发送每日金句的群ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_cache_dir = Path("plugins/yuri/image_cache")
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)

    async def on_load(self):
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        
        # 注册定时任务：每隔3小时发布一次，从00:00开始
        time_interval = 3  # 小时
        try:
            for i in range(0, 24, time_interval):
                time_str = f"{i:02d}:00"
                self.add_scheduled_task(
                    self.daily_task,
                    f"daily_task_{i}",
                    time_str,
                )
            print(f"已注册定时任务：每隔{time_interval}小时发布一次")
        except Exception as e:
            print(f"注册定时任务失败: {e}")

    async def daily_task(self):
        """定时任务：随机执行一个指令"""
        await self.execute_random_command()

    def extract_text(self, msg: BaseMessage):
        text = ""
        for message in msg.message:
            try:
                mtype = message["type"]
            except Exception:
                mtype = getattr(message, "msg_seg_type", None)

            if mtype == "text":
                txt = None
                if hasattr(message, "text"):
                    txt = getattr(message, "text")
                else:
                    try:
                        txt = message.get("data", {}).get("text")
                    except Exception:
                        txt = None
                if txt:
                    text += txt
        return text.strip()

    def get_url(self):
        return "https://v1.yurikoto.com/wallpaper?encode=json&type=rand&orientation=rand"

    async def _download_image(self, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.image_cache_dir / f"{url_hash}.png"
        if not cache_path.exists():
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                with open(cache_path, 'wb') as f:
                    f.write(response.content)
            except Exception as e:
                _log.error(f"下载图片失败: {url}, 错误: {e}")
                raise
        # 读取为base64
        with open(cache_path, 'rb') as f:
            image_data = f.read()
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"base64://{b64}"

    async def get_images(self, count: int, msg: BaseMessage):
        images = []
        url = self.get_url()
        for _ in range(count):
            try:
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                if data.get('status') != 'success':
                    raise Exception(f"API返回失败: {data.get('status')}")
                image_url = data['link']
                b64_image = await self._download_image(image_url)
                images.append(b64_image)
                time.sleep(0.08)
            except Exception as e:
                _log.error(f"获取图片失败: {e}")
                break
        return images

    async def get_daily_quote(self) -> str:
        """获取每日金句"""
        try:
            def fetch():
                client = UapiClient("https://uapis.cn")
                return client.poem.get_saying()

            result = await asyncio.to_thread(fetch)
            if isinstance(result, dict):
                text = result.get('text') or str(result)
            elif isinstance(result, str):
                text = result
            else:
                text = str(result)
            return text
        except UapiError as exc:
            return f"每日金句 API 错误: {exc}"
        except Exception as exc:
            return f"获取每日金句失败: {exc}"

    async def get_yuri_words(self) -> str:
        """获取百合台词"""
        try:
            response = requests.get("https://v1.yurikoto.com/sentence?encode=json")
            response.raise_for_status()
            data = response.json()
            if data.get('status') != 'success':
                return f"获取失败: {data.get('status')}"
            content = data['content']
            source = data.get('source', '')
            if source:
                return f"{content}\n—— {source}"
            else:
                return content
        except Exception as e:
            return f"获取失败: {e}"

    async def execute_random_command(self):
        """随机执行一个指令"""
        commands = ['yuri', '一言', 'yuriwords', '名言警句']
        cmd = random.choice(commands)
        if cmd == 'yuri':
            images = await self.get_images(1, None)
            if images:
                await self.api.post_group_msg(int(self.ACTIVE_GROUP_ID), image=images[0])
        elif cmd == '一言':
            quote = await self.get_daily_quote()
            await self.api.post_group_msg(int(self.ACTIVE_GROUP_ID), text=quote)
        elif cmd == 'yuriwords':
            words = await self.get_yuri_words()
            await self.api.post_group_msg(int(self.ACTIVE_GROUP_ID), text=words)
        elif cmd == '名言警句':
            try:
                file_path = Path(__file__).parent.parent.parent / "data" / "rgl.txt"
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                if lines:
                    quote = random.choice(lines)
                    await self.api.post_group_msg(int(self.ACTIVE_GROUP_ID), text=quote)
            except FileNotFoundError:
                pass

    @filter_registry.group_filter
    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, msg: GroupMessage):
        text = self.extract_text(msg)
        if text == "/yuri":
            images = await self.get_images(1, msg)
            if images:
                await self.api.post_group_msg(msg.group_id, image=images[0])
        elif text == "/一言":
            quote = await self.get_daily_quote()
            await self.api.post_group_msg(msg.group_id, text=quote)
        elif text == "/yuriwords":
            words = await self.get_yuri_words()
            await self.api.post_group_msg(msg.group_id, text=words)
        elif text.startswith("/名言警句"):
            try:
                file_path = Path(__file__).parent / "data" / "rgl.txt"
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                if not lines:
                    await msg.reply(text="无话可说")
                    return
                
                # 解析次数
                parts = text.split()
                count = 1
                if len(parts) > 1 and parts[1].isdigit():
                    count = int(parts[1])
                    if count > 10:  # 限制最大次数，避免滥用
                        count = 10
                
                # 发送指定次数的名言警句
                for _ in range(count):
                    quote = random.choice(lines)
                    await self.api.post_group_msg(msg.group_id, text=quote)
                    if count > 1:
                        await asyncio.sleep(0.5)  # 避免发送太快
            except FileNotFoundError:
                await msg.reply(text="文件不存在")