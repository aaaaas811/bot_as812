from ncatbot.plugin_system import NcatBotPlugin, filter_registry
from ncatbot.utils import get_log
from ncatbot.core import GroupMessage
from ncatbot.core import MessageChain, Image
import re
import json
import os
import sys
import bot_state
import aiohttp
import asyncio
from pathlib import Path
from .analyze import MonsterAnalyzer
LOG = get_log("mh")
class mh(NcatBotPlugin):
    name = "mh" 
    version = "0.0.3" 
    description = "mh插件，用于ncatbot的怪物猎人集会码管理与怪物信息查询" 
    author = "as811"
    
    # 初始化：集会码
    is_mhw_team_code = re.compile(r'^[A-Za-z0-9!#$%&+\-=?@^_`~]{12}$')
    is_mhr_team_code = re.compile(r'^[A-Za-z0-9!#$%&+\-=?@^_`~]{8}$')
    mhw=list()
    mhr=list()
    analyzer = None

    async def on_load(self):
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        try:
            data_dir = os.path.dirname(__file__)
            self.analyzer = MonsterAnalyzer(data_dir)
            # 创建图片缓存目录
            self.image_cache_dir = Path("plugins/mh/image_cache")
            self.image_cache_dir.mkdir(parents=True, exist_ok=True)
            print("怪物数据加载成功")
        except Exception as e:
            print(f"怪物数据加载失败: {e}，请确保已运行爬虫脚本以获取数据")

    async def _download_image(self, url: str) -> Path:
        """下载图片到缓存目录"""
        try:
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()
            cache_path = self.image_cache_dir / f"{url_hash}.png"
            
            if cache_path.exists():
                return cache_path
            
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(cache_path, 'wb') as f:
                            f.write(await response.read())
                        return cache_path
        except Exception as e:
            LOG.error(f"下载图片失败 {url}: {e}")
        return None

    @filter_registry.group_filter
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, msg: GroupMessage):
        text = msg.raw_message
        text = text.replace("&amp;", "&") 
        if text == "/helpMH":
                menu_text = \
                "直接发送集会码即可记录喵~\n" \
                "/查询 获取集会列表\n" \
                "/删除mhw 删除最近一个 MHW 集会码\n" \
                "/删除mhr 删除最近一个 MHR 集会码\n" \
                "/清空 清空所有集会码\n"\
                "🔻以下功能暂时仅限wilds🔻\n" \
                "/爬取ws 更新最新数据\n" \
                "/怪物列表 列出已收录的怪物名称\n" \
                "/简介 怪物名字 查询该怪物的信息\n" \
                "/弱点 怪物名字 查询该怪物的弱点简析\n" \
                "/肉质 怪物名字 查询该怪物的肉质表" 
                await msg.reply(text = menu_text, at = False)
        if self.is_mhw_team_code.match(text):
            self.mhw.append(text)
            await self.api.post_group_msg(group_id=msg.group_id,text=f"收到 MHW 集会码：\n{text}\n输入 /查询 获取集会列表喵~") 
        if self.is_mhr_team_code.match(text):
                self.mhr.append(text)
                await self.api.post_group_msg(group_id=msg.group_id,text=f"收到 MHR 集会码：\n{text}\n输入 /查询 获取集会列表喵~") 
        if text == "/查询":
            mhw_codes = "\n".join(self.mhw) if len(self.mhw) > 0 else "暂无 MHW 集会码"
            mhr_codes = "\n".join(self.mhr) if len(self.mhr) > 0 else "暂无 MHR 集会码"
            await self.api.post_group_msg(group_id=msg.group_id,text=f"MHW集会码：\n{mhw_codes}\nMHR 集会码：\n{mhr_codes} ")
        if text == "/删除mhw":
            if len(self.mhw) == 0:
                await self.api.post_group_msg(group_id=msg.group_id,text="没有可删除的 MHW 集会码喵~")
                return
            await self.api.post_group_msg(group_id=msg.group_id,text="已删除一个 MHW 集会码"+self.mhw[-1]+"喵~")
            self.mhw.pop()
        if text == "/删除mhr":
            if len(self.mhr) == 0:
                await self.api.post_group_msg(group_id=msg.group_id,text="没有可删除的 MHR 集会码喵~")
                return
            await self.api.post_group_msg(group_id=msg.group_id,text="已删除一个 MHR 集会码"+self.mhr[-1]+"喵~")
            self.mhr.pop()
        if text == "/清空":
            self.mhw.clear()
            self.mhr.clear()
            await self.api.post_group_msg(group_id=msg.group_id,text="已清空所有集会码喵~")
        if text == "/爬取ws":
            # 动态调用爬虫主函数（可用 subprocess 或 import 调用 main）
            os.system(f"{sys.executable} plugins/mh/mhws_Wiki_Crawler/src/mhws_crawler.py")
            self.analyzer = MonsterAnalyzer(os.path.dirname(__file__))
            await self.api.post_group_msg(group_id=msg.group_id, text="已爬取并更新ws肉质表数据")
            return
        if text.strip() == "/怪物列表":
            names = [m.get('name','') for m in self.analyzer.monster_list if m.get('name','')]
            reply = ' '.join(names)
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        if text.startswith("/简介 "):
            monster_name = text[3:].strip()
            reply = self.analyzer.get_monster_intro(monster_name)
            # 分离图片和文本
            lines = reply.split('\n')
            image_url = None
            text_lines = []
            for line in lines:
                if line.startswith("图片: "):
                    image_url = line[4:].strip()
                else:
                    text_lines.append(line)
            text_reply = '\n'.join(text_lines)
            
            # 构建消息链
            msg_chain = []
            
            # 添加图片（如果有）
            if image_url and image_url != "":
                cache_path = await self._download_image(image_url)
                if cache_path:
                    msg_chain.append(Image(str(cache_path)))
            
            # 添加文本
            if text_reply.strip():
                msg_chain.append(text_reply)
            
            # 发送消息
            if msg_chain:
                try:
                    await self.api.post_group_msg(group_id=msg.group_id, rtf=MessageChain(msg_chain))
                except Exception as e:
                    LOG.error(f"发送消息失败: {e}")
                    # 如果有图片，删除缓存文件并重试
                    if cache_path and cache_path.exists():
                        try:
                            cache_path.unlink()  # 删除文件
                            LOG.info(f"已删除缓存图片: {cache_path}")
                            # 重新下载图片
                            cache_path = await self._download_image(image_url)
                            if cache_path:
                                msg_chain[0] = Image(str(cache_path))  # 更新消息链中的图片
                                await self.api.post_group_msg(group_id=msg.group_id, rtf=MessageChain(msg_chain))
                            else:
                                # 如果重新下载失败，只发送文本
                                await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
                        except Exception as retry_e:
                            LOG.error(f"重试发送失败: {retry_e}")
                            # 重试失败，只发送文本
                            await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
                    else:
                        # 没有图片或文件不存在，只发送文本
                        await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
            return
        if text.startswith("/弱点 "):
            monster_name = text[len("/弱点 "):].strip()
            reply = self.analyzer.get_monster_weakness(monster_name)
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        if text.startswith("/肉质 "):
            monster_name = text[len("/肉质 "):].strip()
            reply = self.analyzer.get_monster_meat(monster_name)
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        