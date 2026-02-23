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
    is_mhr_team_code = re.compile(r'^[A-Za-z0-9!#$%&+\-=?@^_`~]{16}$')
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

    def _build_intro_for_source(self, monster_name: str, source: str) -> str:
        """从指定数据源读取怪物 JSON 并构建简介字符串（不发送）。"""
        base_dir = os.path.join(os.path.dirname(__file__), 'data', source)
        json_path = os.path.join(base_dir, f"{monster_name}.json")
        monster_json = None
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    monster_json = json.load(f)
            except Exception:
                monster_json = None

        # 尝试从 analyzer 的 monster_list 找图片和描述（如果存在）
        image_url = ''
        desc = ''
        for m in (self.analyzer.monster_list or []):
            if m.get('name') == monster_name and m.get('source') == source:
                image_url = m.get('image', '') or image_url
                desc = m.get('description', '') or desc
                break

        if monster_json:
            desc = desc or monster_json.get('description', '')
            base_data = monster_json.get('base_data', {})
        else:
            base_data = {}

        lines = [f"图片: {image_url}", f"名称: {monster_name}", f"(数据源: {source})", f"简介: {desc}"]
        if base_data:
            lines.append("基础数据:")
            # 映射常见键到更友好的中文显示
            key_map = {
                'val': '体力',
                'BaseHealth': '基础血量',
                'Species': '怪物种类',
                'HunterRankPoint': '调查点数'
            }
            for k, v in base_data.items():
                # 忽略尺寸/厘米相关的键（例如 mhwi 中可能包含的尺寸范围），不在简介中显示
                try:
                    if isinstance(k, str) and '厘米' in k:
                        continue
                except Exception:
                    pass
                label = key_map.get(k, k)
                lines.append(f"{label}：{v}")

        lines.append(f"输入/ws肉质 {monster_name} 或 /wi肉质 {monster_name} 查看不同数据源的肉质表\n输入/弱点 {monster_name} 查看弱点简析")
        return "\n".join(lines)

    async def _send_intro_reply(self, msg: GroupMessage, reply: str):
        """将简介字符串解析为图片+文本并发送到群。"""
        lines = reply.split('\n')
        image_url = None
        text_lines = []
        for line in lines:
            if line.startswith("图片: "):
                image_url = line[4:].strip()
            else:
                text_lines.append(line)
        text_reply = '\n'.join(text_lines)

        msg_chain = []
        cache_path = None
        if image_url and image_url != "":
            cache_path = await self._download_image(image_url)
            if cache_path:
                msg_chain.append(Image(str(cache_path)))

        if text_reply.strip():
            msg_chain.append(text_reply)

        if msg_chain:
            try:
                await self.api.post_group_msg(group_id=msg.group_id, rtf=MessageChain(msg_chain))
            except Exception as e:
                LOG.error(f"发送消息失败: {e}")
                if cache_path and cache_path.exists():
                    try:
                        cache_path.unlink()
                        LOG.info(f"已删除缓存图片: {cache_path}")
                        cache_path = await self._download_image(image_url)
                        if cache_path:
                            msg_chain[0] = Image(str(cache_path))
                            await self.api.post_group_msg(group_id=msg.group_id, rtf=MessageChain(msg_chain))
                        else:
                            await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
                    except Exception as retry_e:
                        LOG.error(f"重试发送失败: {retry_e}")
                        await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
                else:
                    await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)
        else:
            # 仅文本（或没有内容）
            await self.api.post_group_msg(group_id=msg.group_id, text=text_reply)

    @filter_registry.group_filter
    @bot_state.ignore_if_sleeping()
    async def on_group_message(self, msg: GroupMessage):
        text = msg.raw_message
        text = text.replace("&amp;", "&") 
        if text == "/helpMH" or text == "/helpmh":
            menu_text = \
            "直接发送集会码即可记录喵~\n" \
            "/查询 获取集会列表\n" \
            "/删除mhw 删除最近一个 MHW 集会码\n" \
            "/删除mhr 删除最近一个 MHR 集会码\n" \
            "/清空 清空所有集会码\n"\
            "/爬取ws(wi) 更新最新数据\n" \
            "/怪物列表 列出已收录的怪物名称\n" \
            "/ws(wi)简介 怪物名字 查询该怪物的信息\n" \
            "/ws(wi)弱点 怪物名字 查询该怪物的弱点简析\n" \
            "/ws(wi)肉质 怪物名字 查询 mhws(mhwi) 数据源的肉质表"
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
        if text == "/爬取wi":
            # 动态调用爬虫主函数（可用 subprocess 或 import 调用 main）
            os.system(f"{sys.executable} plugins/mh/mhwi_Wiki_Crawler/src/mhwi_crawler.py")
            self.analyzer = MonsterAnalyzer(os.path.dirname(__file__))
            await self.api.post_group_msg(group_id=msg.group_id, text="已爬取并更新wi肉质表数据")
            return
        if text.strip() == "/怪物列表":
            # 按数据源分组输出，优先显示 mhwi，然后 mhws
            grouped = {}
            for m in (self.analyzer.monster_list or []):
                name = m.get('name','')
                if not name:
                    continue
                src = m.get('source','unknown')
                grouped.setdefault(src, []).append(name)

            parts = []
            for src in ['mhwi', 'mhws']:
                if src in grouped:
                    # 去重但保持原顺序
                    seen = set()
                    uniq = []
                    for n in grouped[src]:
                        if n and n not in seen:
                            seen.add(n)
                            uniq.append(n)
                    parts.append(f"{src}:")
                    parts.append(' '.join(uniq))

            # 如果还有其它来源，按字母序附加
            other_srcs = sorted(k for k in grouped.keys() if k not in ('mhwi','mhws'))
            for src in other_srcs:
                seen = set()
                uniq = []
                for n in grouped[src]:
                    if n and n not in seen:
                        seen.add(n)
                        uniq.append(n)
                parts.append(f"{src}:")
                parts.append(' '.join(uniq))

            reply = '\n'.join(parts) if parts else '暂无已收录的怪物'
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        
        # 支持按数据源查询简介
        if text.startswith("/ws简介 "):
            monster_name = text[len("/ws简介 "):].strip()
            reply = self._build_intro_for_source(monster_name, 'mhws')
            await self._send_intro_reply(msg, reply)
            return
        if text.startswith("/wi简介 "):
            monster_name = text[len("/wi简介 "):].strip()
            reply = self._build_intro_for_source(monster_name, 'mhwi')
            await self._send_intro_reply(msg, reply)
            return
        # 支持按数据源查询弱点
        if text.startswith("/ws弱点 "):
            monster_name = text[len("/ws弱点 "):].strip()
            reply = self.analyzer.get_monster_weakness(monster_name, source='mhws')
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        if text.startswith("/wi弱点 "):
            monster_name = text[len("/wi弱点 "):].strip()
            reply = self.analyzer.get_monster_weakness(monster_name, source='mhwi')
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        # 向后兼容旧命令 /简介 —— 映射到 mhws 并给出提示
        if text.startswith("/简介 "):
            monster_name = text[3:].strip()
            reply = self.analyzer.get_monster_intro(monster_name)
            reply = "(已使用默认数据源 mhws，如需 mhwi 请使用 /wi简介 )\n" + reply
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        # 向后兼容旧命令 /弱点 —— 映射到 mhws 并给出提示
        if text.startswith("/弱点 "):
            monster_name = text[len("/弱点 "):].strip()
            reply = self.analyzer.get_monster_weakness(monster_name, source='mhws')
            reply = "(已使用默认数据源 mhws，如需 mhwi 请使用 /wi弱点 )\n" + reply
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        # 支持两个肉质命令，分别对应 mhws 与 mhwi 数据源
        if text.startswith("/ws肉质 "):
            monster_name = text[len("/ws肉质 "):].strip()
            reply = self.analyzer.get_monster_meat(monster_name, source='mhws')
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        if text.startswith("/wi肉质 "):
            monster_name = text[len("/wi肉质 "):].strip()
            reply = self.analyzer.get_monster_meat(monster_name, source='mhwi')
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        # 向后兼容旧命令 /肉质 —— 映射到 mhws 并给出提示
        if text.startswith("/肉质 "):
            monster_name = text[len("/肉质 "):].strip()
            reply = self.analyzer.get_monster_meat(monster_name, source='mhws')
            reply = "(已使用默认数据源 mhws，如需 mhwi 请使用 /wi肉质 )\n" + reply
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return
        