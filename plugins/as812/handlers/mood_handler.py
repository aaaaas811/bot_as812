"""心情处理器"""
import yaml
import time
import json
import os
from typing import Optional
from ncatbot.utils.logger import get_log
from ..core.config_manager import ConfigManager

_log = get_log()


class MoodHandler:
    """心情处理器类"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    async def is_bot_muted(self, api, group_id: int) -> bool:
        """检查机器人是否被禁言"""
        try:
            # 从根目录 config.yaml 获取 bt_uin
            with open("config.yaml", "r", encoding="utf-8") as f:
                root_config = yaml.safe_load(f)
            bt_uin = root_config.get("bt_uin")
            if not bt_uin:
                _log.warning("未找到 bt_uin 配置")
                return False
            
            shut_list = await api.get_group_shut_list(group_id=group_id)
            # 尝试访问数据
            members = None
            if hasattr(shut_list, 'members'):
                members = shut_list.members
            elif hasattr(shut_list, 'data'):
                members = shut_list.data
            elif hasattr(shut_list, 'raw_data') and 'data' in shut_list.raw_data:
                members = shut_list.raw_data['data']
            elif hasattr(shut_list, 'response') and hasattr(shut_list.response, 'data'):
                members = shut_list.response.data
            else:
                _log.warning(f"无法找到禁言数据: {type(shut_list)}")
                return False
            
            if not isinstance(members, list):
                _log.warning(f"members 不是列表: {type(members)}")
                return False
            
            for member in members:
                if isinstance(member, dict) and member.get('uin') == str(bt_uin):
                    shut_up_time = member.get('shutUpTime', 0)
                    _log.debug(f"找到机器人成员，shutUpTime={shut_up_time}, current_time={time.time()}")
                    if shut_up_time > time.time():
                        _log.info(f"812 {bt_uin} 被禁言至 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(shut_up_time))}")
                        return True
                elif hasattr(member, 'user_id') and str(member.user_id) == str(bt_uin):
                    shut_up_time = getattr(member, 'shut_up_timestamp', 0)
                    _log.debug(f"找到机器人成员，shut_up_timestamp={shut_up_time}, current_time={time.time()}")
                    if shut_up_time > time.time():
                        _log.info(f"812 {bt_uin} 被禁言至 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(shut_up_time))}")
                        return True
        except Exception as e:
            _log.warning(f"检查禁言状态失败: {e}")
        return False
    
    async def process_mood_on_message(self, api, group_id: int) -> None:
        """消息到达时的钩子。取消计数逻辑，仅确保心情文件存在。"""
        try:
            gid = str(group_id)
            # 确保心情文件存在（初始化为空心情）
            state = self.load_mood_state(gid)
            if not state.get("mood"):
                # 不覆盖已存在的心情，仅在首次创建时写入空字符串或默认值
                self.save_mood_state(gid, {"mood": state.get("mood", "")})
        except Exception as e:
            _log.warning(f"process_mood_on_message 失败: {e}")

    def _mood_state_path(self, gid: str) -> str:
        d = "plugins/as812/logs"
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return os.path.join(d, f"{gid}_mood.json")

    def load_mood_state(self, gid: str) -> dict:
        p = self._mood_state_path(gid)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 兼容旧格式，提取 mood 字段
                    if isinstance(data, dict):
                        return {"mood": data.get("mood", "")}
                    return {"mood": str(data) if data is not None else ""}
            except Exception:
                return {"mood": ""}
        return {"mood": ""}

    def save_mood_state(self, gid: str, state: dict):
        p = self._mood_state_path(gid)
        try:
            # 仅保存 mood 字段，保持文件简单
            out = {}
            if isinstance(state, dict):
                out["mood"] = state.get("mood", "")
            else:
                out["mood"] = str(state)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        except Exception as e:
            _log.warning(f"保存心情状态失败: {e}")

    def maybe_insert_mood_instruction(self, chat_history, gid: str):
        """保留接口兼容性：当前不再通过计数插入心情生成指令。

        使用者应当在构建 prompt 时调用 `get_current_mood_system_prompt` 将当前心情作为一条 `system` 提示加入。
        返回原始 chat_history 且标记为未插入。
        """
        try:
            # 读取本地配置以返回 base_name（兼容调用方期望的返回值）
            local_cfg = {}
            base_name = "as812（bot）"
            cfg_path = "plugins/as812/config/config.yaml"
            try:
                if os.path.exists(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        local_cfg = yaml.safe_load(f) or {}
                        base_name = local_cfg.get("bot_base_name", base_name)
            except Exception:
                pass
            return chat_history, False, (local_cfg if isinstance(local_cfg, dict) else {}), base_name
        except Exception as e:
            _log.warning(f"maybe_insert_mood_instruction 异常: {e}")
            return chat_history, False, {}, "as812（bot）"


    def get_current_mood_system_prompt(self, gid: str) -> dict:
        """返回一条 system 提示，内容为当前机器人心情（从日志文件读取）。

        返回格式：{"role": "system", "content": "当前的机器人心情为：xxx"}
        """
        try:
            state = self.load_mood_state(str(gid))
            mood = state.get("mood", "")
            if mood:
                return {"role": "system", "content": f"当前的机器人心情为：{mood}"}
            else:
                return {"role": "system", "content": "当前的机器人心情未设置。"}
        except Exception:
            return {"role": "system", "content": "当前的机器人心情未设置。"}
    
    async def _update_group_card(self, api, group_id: int, mood: str) -> None:
        """更新群名片"""
        try:
            # 获取机器人QQ
            with open("config.yaml", "r", encoding="utf-8") as f:
                root_config = yaml.safe_load(f)
            bt_uin = root_config.get("bt_uin")
            
            if not bt_uin:
                _log.warning("未找到 bt_uin 配置，无法更新群名片")
                return
            
            # 构建新的群名片
            new_card = f"812(bot)({mood})"
            
            # 更新群名片
            await api.set_group_card(
                group_id=group_id,
                user_id=int(bt_uin),
                card=new_card
            )
            _log.info(f"已更新群名片为: {new_card}")
            
        except Exception as e:
            _log.warning(f"更新群名片失败: {e}")