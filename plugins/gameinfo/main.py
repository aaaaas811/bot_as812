import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiohttp
import yaml

import sdk_compat  # noqa: F401
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray
from ncatbot.types.qq import ForwardConstructor
from ncatbot.utils.logger import get_log

_log = get_log()

CST = timezone(timedelta(hours=8))

MIX_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

ROOT_CONFIG = Path(__file__).parent.parent.parent / "config.yaml"


class GameInfo(NcatBotPlugin):
    name = "GameInfo"
    version = "1.0.0"
    author = "as811"
    description = "获取B站指定UP主当日视频并合并转发到特定群"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._config_path = Path(__file__).parent / "config" / "config.yaml"
        self._data_dir = Path(__file__).parent.parent.parent / "data" / "gameinfo"
        self._sent_path = self._data_dir / "sent_videos.json"
        self._config: dict = {}
        self._session: aiohttp.ClientSession | None = None
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_keys_time: float = 0.0
        self._bili_cookies: dict[str, str] = {}

    # ---- lifecycle ----

    async def on_load(self):
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_config()
        self._load_bili_credentials()
        self._session = aiohttp.ClientSession()

        interval = self._config.get("check_interval", 0)
        if interval > 0:
            self.add_scheduled_task(
                name="gameinfo_check",
                interval=f"{interval}m",
                callback=self._scheduled_check,
            )
            _log.info("[gameinfo] 定时检查已注册，间隔 %s 分钟", interval)

        if self._config.get("send_on_load", False):
            asyncio.create_task(self._check_and_send())

        _log.info(
            "[gameinfo] 插件已加载，监控 %s 个UP主，目标 %s 个群",
            len(self._get_uids()),
            len(self._get_target_groups()),
        )

    async def on_close(self):
        if self._session:
            await self._session.close()

    # ---- config helpers ----

    def _load_config(self):
        if self._config_path.exists():
            raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
            self._config = raw

    def _load_bili_credentials(self):
        """从根 config.yaml 读取 B站 adapter 的登录凭据。"""
        if not ROOT_CONFIG.exists():
            return
        try:
            root = yaml.safe_load(ROOT_CONFIG.read_text(encoding="utf-8")) or {}
        except Exception:
            return
        for adapter in root.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            if adapter.get("platform") == "bilibili":
                cfg = adapter.get("config", {}) or {}
                sessdata = cfg.get("sessdata", "")
                dedeuserid = str(cfg.get("dedeuserid", ""))
                bili_jct = cfg.get("bili_jct", "")
                if sessdata:
                    self._bili_cookies["SESSDATA"] = sessdata
                if dedeuserid:
                    self._bili_cookies["DedeUserID"] = dedeuserid
                if bili_jct:
                    self._bili_cookies["bili_jct"] = bili_jct
                break

    def _get_uids(self) -> list[int]:
        uids = self._config.get("uids", []) or []
        result: list[int] = []
        for u in uids:
            try:
                result.append(int(u))
            except (TypeError, ValueError):
                _log.warning("[gameinfo] 忽略非法 UID: %s", u)
        return result

    def _get_target_groups(self) -> list[int]:
        groups = self._config.get("target_groups", []) or []
        result: list[int] = []
        for g in groups:
            try:
                result.append(int(g))
            except (TypeError, ValueError):
                _log.warning("[gameinfo] 忽略非法群号: %s", g)
        return result

    # ---- sent_videos persistence ----

    def _load_sent_videos(self) -> dict:
        if self._sent_path.exists():
            try:
                return json.loads(self._sent_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_sent_videos(self, data: dict):
        self._sent_path.parent.mkdir(parents=True, exist_ok=True)
        self._sent_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- WBI signing ----

    async def _fetch_wbi_keys(self) -> tuple[str, str]:
        now = time.time()
        if self._wbi_keys and (now - self._wbi_keys_time) < 3600:
            return self._wbi_keys

        try:
            async with self._session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
                cookies=self._bili_cookies,
            ) as resp:
                data = await resp.json()
                wbi_img = data.get("data", {}).get("wbi_img", {})
                # 新版 API 返回 img_url / sub_url，旧版返回 img_key / sub_key
                img = wbi_img.get("img_key") or wbi_img.get("img_url", "")
                sub = wbi_img.get("sub_key") or wbi_img.get("sub_url", "")
                if img and sub:
                    # URL 格式: https://i0.hdslb.com/bfs/wbi/xxx.png → 提取 key
                    if "/" in img:
                        img = img.rsplit("/", 1)[-1].split(".", 1)[0]
                    if "/" in sub:
                        sub = sub.rsplit("/", 1)[-1].split(".", 1)[0]
                    self._wbi_keys = (img, sub)
                    self._wbi_keys_time = now
                    _log.info("[gameinfo] WBI 密钥已更新")
                    return self._wbi_keys
        except Exception as e:
            _log.warning("[gameinfo] 获取 WBI 密钥失败: %s", e)

        if self._wbi_keys:
            return self._wbi_keys
        raise RuntimeError("无法获取 Bilibili WBI 签名密钥")

    @staticmethod
    def _sign_wbi(params: dict, img_key: str, sub_key: str) -> dict:
        combined = img_key + sub_key
        mixed = "".join(combined[i] for i in MIX_TABLE)[:32]

        params["wts"] = int(time.time())
        sorted_items = sorted(params.items(), key=lambda x: x[0])
        query = urllib.parse.urlencode(sorted_items)
        w_rid = hashlib.md5((query + mixed).encode()).hexdigest()
        params["w_rid"] = w_rid
        return params

    # ---- Bilibili API calls ----

    async def _get_user_info(self, uid: int) -> dict:
        try:
            async with self._session.get(
                "https://api.bilibili.com/x/space/acc/info",
                params={"mid": str(uid)},
                headers={"User-Agent": UA, "Referer": "https://space.bilibili.com/"},
                cookies=self._bili_cookies,
            ) as resp:
                data = await resp.json()
        except Exception as e:
            _log.error("[gameinfo] 获取用户信息失败 uid=%s: %s", uid, e)
            return {"name": f"UID{uid}", "face": ""}

        if data.get("code") != 0:
            return {"name": f"UID{uid}", "face": ""}

        info = data.get("data", {})
        return {"name": info.get("name", f"UID{uid}"), "face": info.get("face", "")}

    async def _get_user_videos(self, uid: int) -> list[dict]:
        try:
            img_key, sub_key = await self._fetch_wbi_keys()
        except RuntimeError as e:
            _log.error("[gameinfo] %s", e)
            return []

        params = self._sign_wbi(
            {"mid": str(uid), "ps": "50", "pn": "1"}, img_key, sub_key
        )

        try:
            async with self._session.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                params=params,
                headers={"User-Agent": UA, "Referer": "https://space.bilibili.com/"},
                cookies=self._bili_cookies,
            ) as resp:
                data = await resp.json()
        except Exception as e:
            _log.error("[gameinfo] 获取视频列表失败 uid=%s: %s", uid, e)
            return []

        if data.get("code") != 0:
            _log.warning(
                "[gameinfo] B站API异常 uid=%s code=%s msg=%s",
                uid,
                data.get("code"),
                data.get("message", ""),
            )
            return []

        vlist = data.get("data", {}).get("list", {}).get("vlist", [])
        if not vlist:
            return []

        today_start = (
            datetime.now(CST)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        today_end = today_start + 86400

        today_videos: list[dict] = []
        for v in vlist:
            pubdate = v.get("created", 0)
            if today_start <= pubdate < today_end:
                today_videos.append(
                    {
                        "bvid": v.get("bvid", ""),
                        "aid": v.get("aid", 0),
                        "title": v.get("title", ""),
                        "description": v.get("description", ""),
                        "pic": v.get("pic", ""),
                        "pubdate": pubdate,
                        "length": v.get("length", ""),
                        "play": v.get("play", 0),
                        "comment": v.get("comment", 0),
                    }
                )

        return today_videos

    # ---- build forward message ----

    def _build_forward(self, all_videos: dict):
        """构造嵌套合并转发：外层按 UP 主分组，每个 UP 主内层是该 UP 主的视频列表。"""
        today_str = datetime.now(CST).strftime("%Y-%m-%d")

        outer = ForwardConstructor(user_id="bilibili", nickname="B站UP主动态")
        outer.attach_text(
            f"今日 ({today_str}) 的游戏资讯就由812呈上！(目前包括：IGN中国，PlayStation，游戏动力ATK,机核网)"
        )

        for uid, data in all_videos.items():
            info = data["info"]
            name = info["name"]
            node_uid = f"b_{uid}"

            # 为每个 UP 主构造内层合并转发
            inner = ForwardConstructor(user_id=node_uid, nickname=name)
            for video in data["videos"]:
                pub_time = datetime.fromtimestamp(video["pubdate"], tz=CST).strftime(
                    "%H:%M"
                )
                text = (
                    f"【{video['title']}】\n"
                    f"BV号: {video['bvid']}\n"
                    f"发布时间: {pub_time}\n"
                    f"时长: {video['length']}\n"
                    f"链接: https://www.bilibili.com/video/{video['bvid']}"
                )

                msg = MessageArray()
                msg.add_text(text)
                if video["pic"]:
                    msg.add_image(video["pic"])

                inner.attach_message(msg, user_id=node_uid, nickname=name)

            # 将内层转发作为一个节点挂到外层
            outer.attach_forward(inner.build(), user_id=node_uid, nickname=name)

        return outer.build()

    # ---- core logic ----

    async def _check_and_send(
        self,
        source_event: GroupMessageEvent | None = None,
        *,
        full_report: bool = False,
    ):
        """拉取视频并转发。

        full_report=True  (/gameinfo): 发送到触发指令的群，返回当日全部视频。
        full_report=False (定时检查): 发送到配置的目标群，仅返回新视频。
        """
        uids = self._get_uids()
        target_groups = self._get_target_groups()

        if not uids:
            msg = "[gameinfo] 未配置监控 UID，请检查 config.yaml"
            if source_event:
                await self.api.qq.post_group_msg(source_event.group_id, text=msg)
            return

        # 确定发送目标群列表
        if full_report and source_event:
            send_to: list[int] = [source_event.group_id]
        else:
            send_to = target_groups

        if not send_to:
            msg = "[gameinfo] 未配置目标群，请检查 config.yaml"
            if source_event:
                await self.api.qq.post_group_msg(source_event.group_id, text=msg)
            return

        sent_videos = self._load_sent_videos()
        all_result: dict = {}
        total_count = 0

        for uid in uids:
            videos = await self._get_user_videos(uid)
            if not videos:
                continue

            if full_report:
                # /gameinfo: 返回当日全部视频，不检查去重
                selected = videos
            else:
                # 定时检查: 只返回尚未发送的视频
                sent_set: set[str] = set(sent_videos.get(str(uid), []))
                selected = [v for v in videos if v["bvid"] not in sent_set]

            if not selected:
                continue

            user_info = await self._get_user_info(uid)
            all_result[uid] = {"info": user_info, "videos": selected}

            if not full_report:
                uid_key = str(uid)
                if uid_key not in sent_videos:
                    sent_videos[uid_key] = []
                sent_videos[uid_key].extend(v["bvid"] for v in selected)

            total_count += len(selected)

        if total_count == 0:
            msg = "今日暂无UP主发布视频"
            if source_event:
                await self.api.qq.post_group_msg(source_event.group_id, text=msg)
            return

        if not full_report:
            self._save_sent_videos(sent_videos)

        forward = self._build_forward(all_result)

        for gid in send_to:
            try:
                await self.api.qq.post_group_forward_msg(gid, forward)
                _log.info("[gameinfo] 已转发到群 %s，共 %s 个视频", gid, total_count)
            except Exception as e:
                _log.error("[gameinfo] 转发到群 %s 失败: %s", gid, e)

    # ---- triggers ----

    @registrar.qq.on_group_message()
    async def _on_group_msg(self, event: GroupMessageEvent):
        text = self._extract_text(event)
        if text == "/gameinfo":
            _log.info("[gameinfo] 收到 /gameinfo 指令，群=%s 用户=%s", event.group_id, event.user_id)
            await self._check_and_send(event, full_report=True)

    async def _scheduled_check(self):
        _log.info("[gameinfo] 定时检查触发")
        await self._check_and_send()

    @staticmethod
    def _extract_text(msg: GroupMessageEvent) -> str:
        raw = getattr(msg, "raw_message", None)
        if raw:
            cleaned = re.sub(r"\[CQ:[^\]]+\]", "", str(raw)).strip()
            if cleaned:
                return cleaned

        text = ""
        for seg in getattr(msg, "message", []):
            try:
                mtype = seg["type"]
            except Exception:
                mtype = getattr(seg, "msg_seg_type", None)
            if mtype == "text":
                try:
                    txt = seg.get("data", {}).get("text")
                except Exception:
                    txt = getattr(seg, "text", None)
                if txt:
                    text += txt
        return text.strip()
