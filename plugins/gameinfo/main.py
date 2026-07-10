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
import bot_state
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
        self._last_send_path = self._data_dir / "last_send.json"
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

        # 注册每日 22:22 定时推送
        try:
            self.add_scheduled_task(
                name="gameinfo_daily",
                interval="22:22",
                callback=self._daily_push,
            )
            _log.info("[gameinfo] 每日定时推送已注册，时间：22:22")
        except Exception as e:
            _log.warning("[gameinfo] 注册定时任务失败: %s", e)

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

    # ---- last send time persistence ----

    def _load_last_send(self) -> float:
        if self._last_send_path.exists():
            try:
                data = json.loads(self._last_send_path.read_text(encoding="utf-8"))
                return float(data.get("last_send", 0))
            except Exception:
                return 0.0
        return 0.0

    def _save_last_send(self, ts: float):
        self._last_send_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_send_path.write_text(
            json.dumps({"last_send": ts}, ensure_ascii=False), encoding="utf-8"
        )

    async def _daily_push(self):
        """每日定时推送：发送当日视频到目标群"""
        _log.info("[gameinfo] 触发每日定时推送（22:22）")
        await self._check_and_send()

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

    async def _get_user_videos(
        self, uid: int, start_ts: float | None = None, end_ts: float | None = None
    ) -> list[dict]:
        if start_ts is None or end_ts is None:
            today_start = (
                datetime.now(CST)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            start_ts = start_ts if start_ts is not None else today_start
            end_ts = end_ts if end_ts is not None else today_start + 86400

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

        matched: list[dict] = []
        for v in vlist:
            pubdate = v.get("created", 0)
            if start_ts <= pubdate < end_ts:
                matched.append(
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

        return matched

    # ---- build forward message ----

    def _build_forward(self, all_videos: dict, date_label: str | None = None):
        """构造合并转发：每个视频作为独立节点，节点昵称为 UP 主名称。"""
        if date_label is None:
            date_label = f"今日 ({datetime.now(CST).strftime('%Y-%m-%d')})"

        uid_names = self._config.get("uid_names", {}) or {}
        all_names = list(dict.fromkeys(uid_names.values()))
        names_str = "，".join(all_names) if all_names else "暂无"

        fwd = ForwardConstructor(user_id="bilibili", nickname="B站UP主动态")
        fwd.attach_text(
            f"{date_label} 的游戏资讯就由812呈上！(目前包括：{names_str})"
        )

        for uid, data in all_videos.items():
            info = data["info"]
            name = info["name"]
            node_uid = f"b_{uid}"

            for video in data["videos"]:
                pub_time = datetime.fromtimestamp(video["pubdate"], tz=CST).strftime(
                    "%Y-%m-%d %H:%M"
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
                # if video["pic"]:
                #     msg.add_image(video["pic"])

                fwd.attach_message(msg, user_id=node_uid, nickname=name)

        return fwd.build()

    # ---- core logic ----

    async def _check_and_send(
        self,
        source_event: GroupMessageEvent | None = None,
        *,
        full_report: bool = False,
        start_ts: float | None = None,
        end_ts: float | None = None,
        date_label: str | None = None,
    ):
        """拉取视频并转发。

        full_report=True  (/gameinfo): 发送到触发指令的群，返回当日全部视频。
        full_report=False (定时检查): 发送到配置的目标群，仅返回新视频。
        start_ts/end_ts: 指定时间范围（时间戳）。
        """
        _log.info("[gameinfo] _check_and_send 开始, full_report=%s", full_report)
        uids = self._get_uids()
        target_groups = self._get_target_groups()
        _log.info("[gameinfo] uids=%s, target_groups=%s", uids, target_groups)

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

        # 调试模式：只发送到指定群
        if bot_state.is_debug_mode():
            debug_gid = bot_state.get_debug_group()
            send_to = [g for g in send_to if str(g) == debug_gid]
            _log.info("[gameinfo] 调试模式: send_to=%s (debug_gid=%s)", send_to, debug_gid)
            if not send_to:
                return

        if not send_to:
            msg = "[gameinfo] 未配置目标群，请检查 config.yaml"
            if source_event:
                await self.api.qq.post_group_msg(source_event.group_id, text=msg)
            return

        _log.info("[gameinfo] 加载已发送记录...")
        sent_videos = self._load_sent_videos()
        _log.info("[gameinfo] 已发送记录加载完成, 开始获取视频")
        all_result: dict = {}
        total_count = 0

        for uid in uids:
            _log.info("[gameinfo] 正在获取 UID %s 的视频...", uid)
            try:
                videos = await self._get_user_videos(uid, start_ts, end_ts)
            except Exception as e:
                _log.error("[gameinfo] 获取 UID %s 视频失败: %s", uid, e)
                continue
            _log.info("[gameinfo] UID %s 获取到 %d 个视频", uid, len(videos) if videos else 0)
            if not videos:
                continue

            if full_report:
                # /gameinfo: 返回全部视频，不检查去重，但限制数量避免超时
                selected = videos[:5]
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
            msg = "暂无UP主发布视频"
            if source_event:
                await self.api.qq.post_group_msg(source_event.group_id, text=msg)
            return

        if not full_report:
            self._save_sent_videos(sent_videos)

        forward = self._build_forward(all_result, date_label)
        _log.info("[gameinfo] 转发消息构建完成, 共 %d 个节点, %d 个视频", len(forward.content) if forward.content else 0, total_count)

        for gid in send_to:
            try:
                await self.api.qq.post_group_forward_msg(gid, forward)
                _log.info("[gameinfo] 已转发到群 %s，共 %s 个视频", gid, total_count)
            except Exception as e:
                _log.error("[gameinfo] 转发到群 %s 失败: %s", gid, e)

    # ---- triggers ----

    ALLOWED_USERS: set[int] = {3196611630}

    @staticmethod
    def _is_group_admin(event: GroupMessageEvent) -> bool:
        """检查发送者是否为群主、管理员或特殊允许的账号。"""
        role = getattr(getattr(event, "sender", None), "role", None) or ""
        if role in ("owner", "admin"):
            return True
        try:
            return int(event.user_id) in GameInfo.ALLOWED_USERS
        except (TypeError, ValueError):
            return False

    async def _handle_days_query(self, event: GroupMessageEvent, days_str: str):
        """处理 /gameinfo x 指令，查询最近 x 天的视频。"""
        try:
            days = int(days_str)
        except ValueError:
            await self.api.qq.post_group_msg(event.group_id, text=f"无效的天数: {days_str}")
            return

        if days <= 0:
            await self.api.qq.post_group_msg(event.group_id, text="天数需大于0")
            return

        now = datetime.now(CST)
        start_ts = (now - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        end_ts = now.timestamp()
        date_label = f"最近{days}天"

        _log.info("[gameinfo] 查询最近 %s 天视频，群=%s", days, event.group_id)
        await self._check_and_send(event, full_report=True, start_ts=start_ts, end_ts=end_ts, date_label=date_label)

    async def _handle_add_uid(self, event: GroupMessageEvent, uid_str: str, label: str):
        """处理 /gameinfo add xxx 名称 指令。"""
        try:
            uid = int(uid_str)
        except ValueError:
            await self.api.qq.post_group_msg(event.group_id, text=f"无效的UID: {uid_str}")
            return

        if not self._is_group_admin(event):
            await self.api.qq.post_group_msg(event.group_id, text="仅群主/管理员可使用此指令")
            return

        uids = self._config.get("uids", []) or []
        is_new = uid not in uids
        if is_new:
            uids.append(uid)
            self._config["uids"] = uids

        uid_names = self._config.get("uid_names", {}) or {}
        uid_names[str(uid)] = label
        self._config["uid_names"] = uid_names

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            yaml.dump(self._config, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        self._load_config()

        if is_new:
            await self.api.qq.post_group_msg(
                event.group_id, text=f"已添加UP主: {label} (UID: {uid})"
            )
        else:
            await self.api.qq.post_group_msg(
                event.group_id, text=f"已更新UID {uid} 的备注名为: {label}"
            )
        _log.info("[gameinfo] 用户 %s 设置UID %s 备名: %s", event.user_id, uid, label)

    @registrar.qq.on_group_message()
    async def _on_group_msg(self, event: GroupMessageEvent):
        # 调试模式：只允许指定群
        if bot_state.is_debug_mode() and str(event.group_id) != bot_state.get_debug_group():
            _log.info("[gameinfo] 调试模式过滤: 群=%s (仅允许 %s)", event.group_id, bot_state.get_debug_group())
            return
        text = self._extract_text(event)
        _log.info("[gameinfo] 收到群消息: 群=%s 文本=%r", event.group_id, text)
        if text == "/gameinfo":
            _log.info("[gameinfo] 收到 /gameinfo 指令，群=%s 用户=%s", event.group_id, event.user_id)
            await self._check_and_send(event, full_report=True)
            return

        add_match = re.match(r"^/gameinfo\s+add\s+(\d+)\s+(.+)$", text)
        if add_match:
            _log.info("[gameinfo] 收到 /gameinfo add 指令，群=%s 用户=%s", event.group_id, event.user_id)
            await self._handle_add_uid(event, add_match.group(1), add_match.group(2).strip())
            return

        days_match = re.match(r"^/gameinfo\s+(\d+)$", text)
        if days_match:
            _log.info("[gameinfo] 收到 /gameinfo 天数指令，群=%s 用户=%s", event.group_id, event.user_id)
            await self._handle_days_query(event, days_match.group(1))

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
