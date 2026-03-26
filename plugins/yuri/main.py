import sdk_compat  # noqa: F401
from ncatbot.plugin import NcatBotPlugin
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.utils.logger import get_log
import bot_state
import requests
import random
import hashlib
import os
import base64
import asyncio
from pathlib import Path
from uapi import UapiClient
from uapi.errors import UapiError
from requests.exceptions import SSLError

_log = get_log()
import re


class Yuri(NcatBotPlugin):
    name = "Yuri"
    version = "1.0"
    author = "as811"
    description = "Yuri图片插件"

    ACTIVE_GROUP_ID = 883744030  # 修改为要发送每日金句的群ID

    @registrar.qq.on_group_message()
    async def _v5_group_event_entry(self, event: GroupMessageEvent):
        await self.on_group_event(event)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_cache_dir = Path(__file__).parent / "image_cache"
        self.data_dir = Path(__file__).parent.parent.parent / "data"
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
                    name=f"daily_task_{i}",
                    interval=time_str,
                    callback=self.daily_task,
                )
            print(f"已注册定时任务：每隔{time_interval}小时发布一次")
        except Exception as e:
            print(f"注册定时任务失败: {e}")

    async def daily_task(self):
        """定时任务：随机执行一个指令"""
        await self.execute_random_command()

    def extract_text(self, msg: GroupMessageEvent):
        # Prefer raw_message for command matching, then fallback to segments.
        raw = getattr(msg, "raw_message", None)
        if raw:
            cleaned = re.sub(r"\[CQ:[^\]]+\]", "", str(raw)).strip()
            if cleaned:
                return cleaned

        text = ""
        for message in getattr(msg, "message", []):
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

    def get_backup_url(self):
        return "https://api-images.kanochan.net/api.php?album=yuri&"

    def _safe_get(self, url: str, timeout: int = 10):
        try:
            return requests.get(url, timeout=timeout)
        except SSLError as exc:
            _log.warning(f"HTTPS 证书校验失败，降级重试: {exc}")
            return requests.get(url, timeout=timeout, verify=False)

    def _encode_image_file(self, file_path: Path) -> str:
        with open(file_path, 'rb') as f:
            image_data = f.read()
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f"base64://{b64}"

    def _looks_like_image(self, content: bytes) -> bool:
        if not content:
            return False
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if content.startswith(b"\xff\xd8\xff"):
            return True
        if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
            return True
        if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
            return True
        return False

    def _cache_image_bytes(self, image_data: bytes) -> str:
        if not image_data:
            raise ValueError("图片内容为空")
        content_hash = hashlib.md5(image_data).hexdigest()
        cache_path = self.image_cache_dir / f"{content_hash}.png"
        if not cache_path.exists():
            with open(cache_path, 'wb') as f:
                f.write(image_data)
        return self._encode_image_file(cache_path)

    def _extract_image_url(self, payload):
        if isinstance(payload, str):
            candidate = payload.strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate
            return None

        if isinstance(payload, list):
            for item in payload:
                found = self._extract_image_url(item)
                if found:
                    return found
            return None

        if isinstance(payload, dict):
            for key in ("link", "url", "img", "image", "src"):
                found = self._extract_image_url(payload.get(key))
                if found:
                    return found
            if "data" in payload:
                return self._extract_image_url(payload.get("data"))

        return None

    def _get_local_cache_image(self):
        try:
            cache_files = [
                p for p in self.image_cache_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            ]
        except Exception as e:
            _log.error(f"读取本地缓存失败: {e}")
            return None

        if not cache_files:
            return None

        cache_path = random.choice(cache_files)
        try:
            return self._encode_image_file(cache_path)
        except Exception as e:
            _log.error(f"读取缓存图片失败: {cache_path}, 错误: {e}")
            return None

    async def _fetch_image_by_primary_api(self):
        response = self._safe_get(self.get_url(), timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'success':
            raise Exception(f"主API返回失败: {data.get('status')}")
        image_url = data.get('link')
        if not image_url:
            raise Exception("主API未返回图片链接")
        return await self._download_image(image_url)

    async def _fetch_image_by_backup_api(self):
        response = self._safe_get(self.get_backup_url(), timeout=10)
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "image/" in content_type or self._looks_like_image(response.content):
            return self._cache_image_bytes(response.content)

        image_url = None
        try:
            data = response.json()
            image_url = self._extract_image_url(data)
        except ValueError:
            text = (response.text or "").strip()
            if text.startswith("http://") or text.startswith("https://"):
                image_url = text

        if image_url:
            return await self._download_image(image_url)

        raise Exception("备用API未返回可用图片")

    async def _fetch_image_with_fallback(self):
        try:
            return await self._fetch_image_by_primary_api()
        except Exception as e:
            _log.warning(f"主API获取失败，准备切换备用API: {e}")

        try:
            return await self._fetch_image_by_backup_api()
        except Exception as e:
            _log.warning(f"备用API获取失败，准备使用本地缓存: {e}")

        local_image = self._get_local_cache_image()
        if local_image:
            _log.info("已使用本地 image_cache 图片兜底")
            return local_image

        return None

    async def _download_image(self, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.image_cache_dir / f"{url_hash}.png"
        if not cache_path.exists():
            try:
                response = self._safe_get(url, timeout=10)
                response.raise_for_status()
                with open(cache_path, 'wb') as f:
                    f.write(response.content)
            except Exception as e:
                _log.error(f"下载图片失败: {url}, 错误: {e}")
                raise
        return self._encode_image_file(cache_path)

    async def get_images(self, count: int, msg: GroupMessageEvent | None):
        images = []
        for _ in range(count):
            try:
                b64_image = await self._fetch_image_with_fallback()
                if not b64_image:
                    _log.error("图片获取失败：主API、备用API和本地缓存均不可用")
                    break
                images.append(b64_image)
                await asyncio.sleep(0.08)
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

    async def get_yuri_words(self):
        """获取百合台词"""
        try:
            response = self._safe_get("https://v1.yurikoto.com/sentence?encode=json", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('status') != 'success':
                _log.error(f"获取百合台词失败: status={data.get('status')}")
                return None

            content = data.get('content')
            if not content:
                _log.error("获取百合台词失败: 缺少 content 字段")
                return None

            source = data.get('source', '')
            if source:
                return f"{content}\n—— {source}"
            else:
                return content
        except Exception as e:
            _log.error(f"获取百合台词异常: {e}")
            return None

    async def execute_random_command(self):
        """随机执行一个指令"""
        commands = ['yuri', 'yuriwords', '名言警句']
        cmd = random.choice(commands)
        try:
            if cmd == 'yuri':
                images = await self.get_images(1, None)
                if images:
                    await self.api.qq.post_group_msg(int(self.ACTIVE_GROUP_ID), image=images[0])
                else:
                    await self.api.qq.post_group_msg(
                        int(self.ACTIVE_GROUP_ID),
                        text="百合图片暂时不可用（主API、备用API与本地缓存均失败）"
                    )
            elif cmd == 'yuriwords':
                words = await self.get_yuri_words()
                if words:
                    await self.api.qq.post_group_msg(int(self.ACTIVE_GROUP_ID), text=words)
                else:
                    _log.warning("随机指令 yuriwords 跳过发送：API不可用")
            elif cmd == '名言警句':
                try:
                    file_path = self.data_dir / "rgl.txt"
                    with open(file_path, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f.readlines() if line.strip()]
                    if lines:
                        quote = random.choice(lines)
                        await self.api.qq.post_group_msg(int(self.ACTIVE_GROUP_ID), text=quote)
                except FileNotFoundError:
                    pass
        except Exception as e:
            _log.error(f"随机指令执行失败: cmd={cmd}, error={e}")

    @bot_state.ignore_if_sleeping()
    async def on_group_event(self, msg: GroupMessageEvent):
        text = self.extract_text(msg)
        if text == "/yuri":
            try:
                images = await self.get_images(1, msg)
                if images:
                    await self.api.qq.post_group_msg(msg.group_id, image=images[0])
                else:
                    await self.api.qq.post_group_msg(msg.group_id, text="百合图片暂时不可用（主API、备用API与本地缓存均失败）")
            except Exception as e:
                _log.error(f"/yuri 指令处理失败: {e}")
                await self.api.qq.post_group_msg(msg.group_id, text="百合图片发送失败，请稍后重试")
        elif text == "/一言":
            quote = await self.get_daily_quote()
            await self.api.qq.post_group_msg(msg.group_id, text=quote)
        elif text == "/yuriwords":
            try:
                words = await self.get_yuri_words()
                if words:
                    await self.api.qq.post_group_msg(msg.group_id, text=words)
                else:
                    _log.warning(f"/yuriwords 跳过发送：API不可用, group_id={msg.group_id}")
            except Exception as e:
                _log.error(f"/yuriwords 指令处理失败: {e}")
        elif text.startswith("/名言警句"):
            try:
                file_path = self.data_dir / "rgl.txt"
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                if not lines:
                    await self.api.qq.post_group_msg(msg.group_id, text="无话可说")
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
                    await self.api.qq.post_group_msg(msg.group_id, text=quote)
                    if count > 1:
                        await asyncio.sleep(0.5)  # 避免发送太快
            except FileNotFoundError:
                await self.api.qq.post_group_msg(msg.group_id, text="文件不存在")