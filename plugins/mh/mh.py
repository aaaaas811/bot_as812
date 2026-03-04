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
from datetime import datetime
from .analyze import MonsterAnalyzer
LOG = get_log("mh")
class mh(NcatBotPlugin):
    name = "mh" 
    version = "0.0.3" 
    description = "mh插件，用于ncatbot的怪物猎人集会码管理与怪物信息查询" 
    author = "as811"
    meat_background_opacity = 0.10
    
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

    def _build_meat_table_payload(self, monster_name: str, source: str):
        """构建肉质表图片所需的数据结构。"""
        if not self.analyzer:
            return None, "怪物数据未初始化"

        data = self.analyzer.meat_data.get(source, {}).get(monster_name)
        if not data:
            return None, "未找到该怪物的肉质数据"

        def _fmt_value(value) -> str:
            if value is None:
                return "-"
            text = str(value).strip()
            if text == "":
                return "-"
            try:
                num = float(text)
                if num.is_integer():
                    return str(int(num))
                return f"{num:g}"
            except Exception:
                return text

        state_map = {}
        for part in data:
            part_name = str(part.get("部位", "")).strip()
            if not part_name:
                continue

            state = str(part.get("列1", "")).strip() or "正常"
            if state in ["伤口", "弱点"]:
                continue

            values = [
                _fmt_value(part.get("斩", part.get("列2", ""))),
                _fmt_value(part.get("打", part.get("列3", ""))),
                _fmt_value(part.get("弹", part.get("列4", ""))),
                _fmt_value(part.get("火", part.get("列5", ""))),
                _fmt_value(part.get("水", part.get("列6", ""))),
                _fmt_value(part.get("雷", part.get("列7", ""))),
                _fmt_value(part.get("冰", part.get("列8", ""))),
                _fmt_value(part.get("龙", part.get("列9", "")))
            ]

            if all(v == "-" for v in values):
                continue

            state_map.setdefault(state, []).append([part_name] + values)

        if not state_map:
            return None, "未找到可显示的肉质数据（或仅含 伤口/弱点）"

        ordered_states = sorted(state_map.keys(), key=lambda s: (s != "正常", s))
        payload = {
            "monster_name": monster_name,
            "source": source,
            "headers": ["部位", "斩", "打", "弹", "火", "水", "雷", "冰", "龙"],
            "sections": [{"state": st, "rows": state_map[st]} for st in ordered_states]
        }
        return payload, None

    def _find_monster_image_url(self, monster_name: str, source: str) -> str:
        if not self.analyzer:
            return ""

        for m in (self.analyzer.monster_list or []):
            if m.get('name') == monster_name and m.get('source') == source:
                return str(m.get('image', '')).strip()

        for m in (self.analyzer.monster_list or []):
            if m.get('name') == monster_name:
                return str(m.get('image', '')).strip()

        return ""

    def _render_meat_table_image(self, payload: dict):
        """将肉质表数据渲染为 PNG。"""
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps
        except Exception:
            LOG.error("Pillow 未安装，无法渲染肉质 PNG")
            return None

        def _load_font(size: int):
            candidates = [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/System/Library/Fonts/PingFang.ttc"
            ]
            for path in candidates:
                try:
                    if os.path.exists(path):
                        return ImageFont.truetype(path, size=size)
                except Exception:
                    continue
            return ImageFont.load_default()

        title_font = _load_font(30)
        section_font = _load_font(22)
        header_font = _load_font(20)
        body_font = _load_font(20)

        headers = payload["headers"]
        sections = payload["sections"]
        monster_name = payload["monster_name"]
        source = payload["source"]
        bg_image_path = str(payload.get("background_image_path", "")).strip()
        bg_opacity = payload.get("background_opacity", self.meat_background_opacity)
        try:
            bg_opacity = max(0.0, min(1.0, float(bg_opacity)))
        except Exception:
            bg_opacity = self.meat_background_opacity

        measure_canvas = PILImage.new("RGB", (1, 1), "white")
        measure = ImageDraw.Draw(measure_canvas)

        def _text_size(text: str, font):
            bbox = measure.textbbox((0, 0), str(text), font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]

        table_rows = []
        for sec in sections:
            table_rows.extend(sec["rows"])

        col_widths = []
        for idx, head in enumerate(headers):
            max_w = _text_size(head, header_font)[0]
            for row in table_rows:
                if idx < len(row):
                    max_w = max(max_w, _text_size(row[idx], body_font)[0])
            if idx == 0:
                max_w = max(max_w, 140)
            else:
                max_w = max(max_w, 64)
            col_widths.append(max_w + 28)

        margin = 28
        section_gap = 12
        row_h = max(_text_size("测试", body_font)[1], _text_size("99", body_font)[1]) + 16
        header_h = max(_text_size("部位", header_font)[1], _text_size("99", header_font)[1]) + 18
        state_h = _text_size("状态：正常", section_font)[1] + 16
        title_h = _text_size(f"{monster_name} 肉质表", title_font)[1] + 10
        sub_h = _text_size(f"数据源：{source}", body_font)[1] + 6

        table_w = sum(col_widths)
        image_w = margin * 2 + table_w

        image_h = margin + title_h + sub_h + 12
        for sec in sections:
            image_h += state_h + header_h + row_h * len(sec["rows"]) + section_gap
        image_h += margin

        image = PILImage.new("RGB", (image_w, image_h), (255, 255, 255))
        if bg_image_path and bg_opacity > 0 and os.path.exists(bg_image_path):
            try:
                try:
                    resample = PILImage.Resampling.LANCZOS
                except AttributeError:
                    resample = PILImage.LANCZOS

                background = PILImage.open(bg_image_path).convert("RGBA")
                background = ImageOps.fit(background, (image_w, image_h), method=resample)
                alpha = background.getchannel("A").point(lambda a: int(a * bg_opacity))
                background.putalpha(alpha)

                base = PILImage.new("RGBA", (image_w, image_h), (255, 255, 255, 255))
                base.alpha_composite(background)
                image = base.convert("RGB")
            except Exception as e:
                LOG.error(f"肉质图背景处理失败: {e}")

        draw = ImageDraw.Draw(image)

        line_color = (60, 60, 60)
        header_bg = (238, 238, 238)
        state_bg = (228, 238, 248)
        text_color = (20, 20, 20)

        y = margin
        title = f"{monster_name} 肉质表"
        draw.text((margin, y), title, fill=text_color, font=title_font)
        y += title_h
        draw.text((margin, y), f"数据源：{source}", fill=(90, 90, 90), font=body_font)
        y += sub_h + 12

        def _draw_table_row(row_values, top, height, font, fill_color=None):
            x = margin
            for i, cell in enumerate(row_values):
                w = col_widths[i]
                draw.rectangle([x, top, x + w, top + height], outline=line_color, fill=fill_color, width=1)
                txt = str(cell)
                txt_w, txt_h = _text_size(txt, font)
                draw.text((x + (w - txt_w) / 2, top + (height - txt_h) / 2), txt, fill=text_color, font=font)
                x += w

        for sec in sections:
            draw.rectangle([margin, y, margin + table_w, y + state_h], outline=line_color, fill=state_bg, width=1)
            state_text = f"状态：{sec['state']}"
            draw.text((margin + 12, y + (state_h - _text_size(state_text, section_font)[1]) / 2), state_text, fill=text_color, font=section_font)
            y += state_h

            _draw_table_row(headers, y, header_h, header_font, fill_color=header_bg)
            y += header_h

            for row in sec["rows"]:
                _draw_table_row(row, y, row_h, body_font)
                y += row_h

            y += section_gap

        safe_name = re.sub(r'[^\w\u4e00-\u9fa5-]+', '_', monster_name)
        if not safe_name:
            safe_name = "monster"
        filename = f"meat_{source}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        output_path = self.image_cache_dir / filename
        image.save(output_path)
        return output_path

    async def _send_meat_table_image(self, msg: GroupMessage, monster_name: str, source: str, tip_text: str = ""):
        """发送肉质 PNG，失败时回退到文本。"""
        payload, err = self._build_meat_table_payload(monster_name, source)
        if err:
            reply = f"{tip_text}\n{err}" if tip_text else err
            await self.api.post_group_msg(group_id=msg.group_id, text=reply)
            return

        background_url = self._find_monster_image_url(monster_name, source)
        background_path = None
        if background_url:
            background_path = await self._download_image(background_url)
        payload["background_image_path"] = str(background_path) if background_path else ""
        payload["background_opacity"] = self.meat_background_opacity

        image_path = await asyncio.to_thread(self._render_meat_table_image, payload)
        fallback_text = self.analyzer.get_monster_meat(monster_name, source=source)
        if tip_text:
            fallback_text = f"{tip_text}\n{fallback_text}"

        if not image_path:
            await self.api.post_group_msg(group_id=msg.group_id, text=fallback_text)
            return

        msg_chain = [Image(str(image_path))]
        if tip_text:
            msg_chain.append(tip_text)

        try:
            await self.api.post_group_msg(group_id=msg.group_id, rtf=MessageChain(msg_chain))
        except Exception as e:
            LOG.error(f"发送肉质 PNG 失败: {e}")
            await self.api.post_group_msg(group_id=msg.group_id, text=fallback_text)

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
            await self._send_meat_table_image(msg, monster_name, source='mhws')
            return
        if text.startswith("/wi肉质 "):
            monster_name = text[len("/wi肉质 "):].strip()
            await self._send_meat_table_image(msg, monster_name, source='mhwi')
            return
        # 向后兼容旧命令 /肉质 —— 映射到 mhws 并给出提示
        if text.startswith("/肉质 "):
            monster_name = text[len("/肉质 "):].strip()
            tip = "(已使用默认数据源 mhws，如需 mhwi 请使用 /wi肉质 )"
            await self._send_meat_table_image(msg, monster_name, source='mhws', tip_text=tip)
            return
        