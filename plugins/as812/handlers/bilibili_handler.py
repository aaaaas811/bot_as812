"""Bilibili 事件处理骨架。"""

from __future__ import annotations

from typing import Any

from ncatbot.utils.logger import get_log

_log = get_log()


class BilibiliHandler:
    """as812 的 Bilibili 事件处理骨架。"""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._warned_missing_like_api = False
        self._warned_unregistered_platform = False

    def _get_bili_api(self, api):
        """安全获取 bilibili API 客户端，未注册平台时返回 None。"""
        try:
            return getattr(api, "bilibili", None)
        except Exception as e:
            if not self._warned_unregistered_platform:
                _log.warning("Bilibili 平台未注册，跳过 as812 的 Bilibili 初始化: %s", e)
                self._warned_unregistered_platform = True
            return None

    def _get_bilibili_adapter(self) -> dict[str, Any] | None:
        """从插件配置中读取 bilibili adapter 节点。"""
        adapters = self.config_manager.get("adapters", []) or []
        for adapter in adapters:
            if not isinstance(adapter, dict):
                continue
            adapter_type = str(adapter.get("type", "")).lower()
            platform = str(adapter.get("platform", "")).lower()
            if adapter_type == "bilibili" or platform == "bilibili":
                return adapter
        return None

    def _get_bilibili_config(self) -> dict[str, Any]:
        adapter = self._get_bilibili_adapter()
        if not adapter:
            return {}
        cfg = adapter.get("config", {})
        return cfg if isinstance(cfg, dict) else {}

    def is_enabled(self) -> bool:
        """是否启用 Bilibili 功能。"""
        adapter = self._get_bilibili_adapter()
        if not adapter:
            return False
        return bool(adapter.get("enabled", False))

    def get_dynamic_watch_uids(self) -> list[int]:
        """读取需要监听动态的 UP 主 UID 列表。"""
        cfg = self._get_bilibili_config()
        raw_uids: list[Any] = []

        # 优先读取新版配置：adapters[].config.dynamic_page_watches
        watches = cfg.get("dynamic_page_watches", []) or []
        for item in watches:
            if isinstance(item, dict):
                raw_uids.append(item.get("uid"))
            else:
                raw_uids.append(item)

        # 兼容早期骨架配置：bilibili_dynamic_watch_uids
        if not raw_uids:
            legacy = self.config_manager.get("bilibili_dynamic_watch_uids", []) or []
            raw_uids.extend(legacy)

        result: list[int] = []
        for uid in raw_uids:
            try:
                result.append(int(uid))
            except (TypeError, ValueError):
                _log.warning("忽略非法 Bilibili UID 配置: %s", uid)
        return result

    def get_video_reply_text(self) -> str:
        """新视频动态自动评论文案。"""
        cfg = self._get_bilibili_config()
        text = cfg.get("video_dynamic_reply_text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return "非常好视频，爱来自as812"

    def _is_video_dynamic(self, event: Any) -> bool:
        dynamic_type = str(getattr(event, "dynamic_type", "") or "")
        if dynamic_type == "DYNAMIC_TYPE_AV":
            return True

        data = getattr(event, "_data", None)
        if data is not None and getattr(data, "video", None) is not None:
            return True
        return False

    def _extract_video_id(self, event: Any) -> str | None:
        data = getattr(event, "_data", None)
        video = getattr(data, "video", None) if data is not None else None
        if video is None:
            return None

        bv_id = getattr(video, "bv_id", "")
        if bv_id:
            return str(bv_id)

        av_id = getattr(video, "av_id", "")
        if av_id:
            return str(av_id)

        return None

    async def _try_like_dynamic(self, event: Any) -> None:
        """尝试点赞动态。当前 SDK 可能未提供该能力，失败时仅记录。"""
        api = getattr(event, "api", None)
        if api is None:
            return

        candidate_names = ["like_dynamic", "thumb_dynamic", "upvote_dynamic"]
        method = None
        for name in candidate_names:
            method = getattr(api, name, None)
            if callable(method):
                break

        if method is None:
            if not self._warned_missing_like_api:
                _log.warning("当前 ncatbot Bilibili API 未暴露动态点赞接口，已跳过动态点赞")
                self._warned_missing_like_api = True
            return

        dynamic_id = getattr(event, "dynamic_id", None)
        if not dynamic_id:
            return

        try:
            await method(dynamic_id=dynamic_id)
            _log.info("[Bilibili动态] 点赞成功 dynamic_id=%s", dynamic_id)
        except TypeError:
            await method(dynamic_id)
            _log.info("[Bilibili动态] 点赞成功 dynamic_id=%s", dynamic_id)
        except Exception as e:
            _log.warning("[Bilibili动态] 点赞失败 dynamic_id=%s err=%s", dynamic_id, e)

    async def _reply_video_dynamic(self, event: Any) -> None:
        """检测到新视频动态后，给视频发送评论。"""
        api = getattr(event, "api", None)
        if api is None:
            return

        video_id = self._extract_video_id(event)
        if not video_id:
            _log.warning("[Bilibili动态] 新视频动态缺少视频 ID，跳过评论")
            return

        text = self.get_video_reply_text()
        try:
            await api.send_comment(resource_id=video_id, resource_type="video", text=text)
            _log.info("[Bilibili动态] 已评论视频 %s", video_id)
        except Exception as e:
            _log.warning("[Bilibili动态] 评论视频失败 id=%s err=%s", video_id, e)

    async def on_load(self, api) -> None:
        """加载时注册动态监听（可选）。"""
        if not self.is_enabled():
            _log.info("Bilibili 功能未启用，跳过初始化")
            return

        bili_api = self._get_bili_api(api)
        if bili_api is None:
            return

        uids = self.get_dynamic_watch_uids()
        for uid in uids:
            try:
                await bili_api.add_dynamic_page_watch(uid)
                _log.info("已添加 Bilibili 动态监听: uid=%s", uid)
            except Exception as e:
                _log.warning("添加 Bilibili 动态监听失败 uid=%s: %s", uid, e)

    async def on_unload(self, api) -> None:
        """卸载时清理动态监听（可选）。"""
        if not self.is_enabled():
            return

        bili_api = self._get_bili_api(api)
        if bili_api is None:
            return

        for uid in self.get_dynamic_watch_uids():
            try:
                await bili_api.remove_dynamic_page_watch(uid)
            except Exception:
                # 卸载阶段以稳定退出为主，不抛出异常中断插件卸载
                pass

    async def handle_danmu(self, event) -> None:
        """处理直播间弹幕事件。"""
        if not self.is_enabled():
            return

        text = event.data.message.text if hasattr(event.data, "message") else ""
        _log.info("[Bilibili弹幕] room=%s user=%s text=%s", event.group_id, event.user_id, text[:80])

        # 框架占位：后续可在这里接入关键词回复、指令解析或 AI 响应。

    async def handle_private_message(self, event) -> None:
        """处理 Bilibili 私信事件。"""
        if not self.is_enabled():
            return

        _log.info("[Bilibili私信] user=%s", event.user_id)
        # 框架占位：后续可接入用户绑定、工单入口或帮助菜单。

    async def handle_live_start(self, event) -> None:
        """处理开播通知事件。"""
        if not self.is_enabled():
            return

        _log.info("[Bilibili开播] room=%s", event.group_id)

    async def handle_live_end(self, event) -> None:
        """处理下播通知事件。"""
        if not self.is_enabled():
            return

        _log.info("[Bilibili下播] room=%s", event.group_id)

    async def handle_dynamic_new(self, event) -> None:
        """处理新动态事件。"""
        if not self.is_enabled():
            return

        uid = str(getattr(event, "user_id", "") or "")
        watch_uids = {str(x) for x in self.get_dynamic_watch_uids()}
        if watch_uids and uid not in watch_uids:
            return

        _log.info(
            "[Bilibili新动态] uid=%s type=%s text=%s",
            event.user_id,
            getattr(event, "dynamic_type", "unknown"),
            (getattr(event, "text", "") or "")[:80],
        )

        await self._try_like_dynamic(event)

        if self._is_video_dynamic(event):
            await self._reply_video_dynamic(event)
