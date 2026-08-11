"""日志管理器"""
import json
import os
from typing import List, Dict, Any, Optional, Tuple
from ncatbot.utils.logger import get_log
from ..models.message_models import ChatMessage, BotResponse

_log = get_log()


class LogManager:
    """日志管理器类"""
    
    def __init__(self, base_log_dir: str = "plugins/as812/logs"):
        self.base_log_dir = base_log_dir
        os.makedirs(base_log_dir, exist_ok=True)
    
    def get_group_history_path(self, group_id: str) -> str:
        """获取群历史日志文件路径"""
        return os.path.join(self.base_log_dir, f"{group_id}_history.log")
    
    def get_personal_log_path(self, group_id: str, user_qq: str) -> str:
        """获取个人日志文件路径"""
        group_dir = os.path.join(self.base_log_dir, str(group_id))
        os.makedirs(group_dir, exist_ok=True)
        return os.path.join(group_dir, f"{user_qq}.log")

    def get_revoked_log_path(self, group_id: str) -> str:
        """获取撤回消息记录文件路径"""
        return os.path.join(self.base_log_dir, f"{group_id}_revoked.log")

    def find_message_by_id(self, group_id: str, message_id: str) -> Dict[str, Any] | None:
        """按 message_id 在群历史中查找消息记录（撤回后用于恢复内容）。

        从最新往旧找，命中即返回；找不到返回 None。
        """
        target = str(message_id)
        log_path = self.get_group_history_path(group_id)
        if not os.path.exists(log_path):
            return None
        try:
            content = self._read_text_with_fallback(log_path)
            for line in reversed(content.splitlines()):
                try:
                    msg = json.loads(line.strip())
                    if str(msg.get("message_id", "")) == target:
                        return msg
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            _log.error(f"按 ID 查找消息失败: {e}")
        return None

    def save_revoked_message(self, group_id: str, record: Dict[str, Any], keep: int = 20) -> bool:
        """记录一条被撤回的消息（JSONL 追加），并裁剪为最近 keep 条。"""
        try:
            path = self.get_revoked_log_path(group_id)
            records = self.load_revoked_messages(group_id, limit=keep)
            records.append(record)
            records = records[-keep:]
            with open(path, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            _log.error(f"保存撤回消息记录失败: {e}")
            return False

    def load_revoked_messages(self, group_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """加载最近 limit 条被撤回的消息记录（时间从旧到新）。"""
        if limit <= 0:
            return []
        path = self.get_revoked_log_path(group_id)
        if not os.path.exists(path):
            return []
        records = []
        try:
            content = self._read_text_with_fallback(path)
            for line in reversed(content.splitlines()):
                try:
                    records.append(json.loads(line.strip()))
                    if len(records) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            _log.error(f"加载撤回消息记录失败: {e}")
        return list(reversed(records))

    def _read_text_with_fallback(self, file_path: str) -> str:
        """读取文本文件，优先 UTF-8，失败时回退到常见中文编码。"""
        with open(file_path, "rb") as f:
            raw = f.read()

        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                text = raw.decode(encoding)
                if encoding != "utf-8":
                    _log.warning(f"检测到非 UTF-8 文件，已使用 {encoding} 读取: {file_path}")
                return text
            except UnicodeDecodeError:
                continue

        _log.warning(f"文件编码异常，已使用替换模式读取: {file_path}")
        return raw.decode("utf-8", errors="replace")
    
    def save_group_message(self, group_id: str, message: ChatMessage) -> bool:
        """保存群消息到群历史"""
        try:
            log_path = self.get_group_history_path(group_id)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            _log.error(f"保存群消息失败: {e}")
            return False
    
    def save_bot_response(self, group_id: str, response: BotResponse) -> bool:
        """保存机器人回复到群历史"""
        try:
            log_path = self.get_group_history_path(group_id)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(response.to_dict(), ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            _log.error(f"保存机器人回复失败: {e}")
            return False
    
    def load_group_history(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """加载群历史记录"""
        log_path = self.get_group_history_path(group_id)
        if not os.path.exists(log_path):
            return []
        
        messages = []
        try:
            content = self._read_text_with_fallback(log_path)
            lines = content.splitlines()
            for line in reversed(lines):
                if len(messages) >= limit:
                    break
                try:
                    message_data = json.loads(line.strip())
                    messages.append(message_data)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            _log.error(f"加载群历史失败: {e}")
        
        return messages
    
    def load_personal_log(self, group_id: str, user_qq: str) -> Tuple[List[str], str, str]:
        """
        加载个人日志
        返回: (聊天记录列表, 用户信息字符串, 日志文件路径)
        """
        log_path = self.get_personal_log_path(group_id, user_qq)

        personal_history = []
        user_info_str = ""

        if os.path.exists(log_path):
            try:
                content = self._read_text_with_fallback(log_path)

                # 解析基本信息
                if "该用户的基本信息：" in content:
                    start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                    end = content.find("\n\n过往聊天记录：", start)
                    if end == -1:
                        end = len(content)
                    user_info_str = content[start:end].strip()

                # 解析聊天记录
                if "过往聊天记录：" in content:
                    records_start = content.find("过往聊天记录：") + len("过往聊天记录：")
                    records = content[records_start:].strip().split("\n")
                    personal_history = [line.strip() for line in records if line.strip()]

            except Exception as e:
                _log.error(f"加载个人日志失败: {e}")
        else:
            # 首次创建个人日志
            user_info_str = f"QQ昵称: 未知, QQ号: {user_qq}, 群昵称: , 群权限: , 群头衔: "
            initial_content = f"该用户的基本信息：{user_info_str}\n\n过往聊天记录：\n"
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(initial_content)
            except Exception as e:
                _log.error(f"创建个人日志失败: {e}")

        return personal_history, user_info_str, log_path
    
    def append_to_personal_log(self, log_path: str, content: str) -> bool:
        """向个人日志追加内容"""
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            return True
        except Exception as e:
            _log.error(f"追加个人日志失败: {e}")
            return False
    
    def update_personal_log_header(self, log_path: str, new_user_info: str) -> bool:
        """更新个人日志头部信息"""
        try:
            if not os.path.exists(log_path):
                return False

            content = self._read_text_with_fallback(log_path)

            # 更新用户信息
            if "该用户的基本信息：" in content:
                start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                end = content.find("\n\n过往聊天记录：", start)
                if end == -1:
                    end = len(content)
                old_user_info = content[start:end].strip()
                content = content.replace(f"该用户的基本信息：{old_user_info}", f"该用户的基本信息：{new_user_info}")

            with open(log_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        except Exception as e:
            _log.error(f"更新个人日志头部失败: {e}")
            return False
    
    def clear_personal_chat_history(self, log_path: str) -> bool:
        """清空个人聊天记录部分"""
        try:
            if not os.path.exists(log_path):
                return False

            content = self._read_text_with_fallback(log_path)
            
            # 分割内容，保留头部，清空聊天记录
            parts = content.split("\n\n过往聊天记录：\n")
            if len(parts) == 2:
                header = parts[0] + "\n\n过往聊天记录：\n"
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(header)
                return True
            
            return False
            
        except Exception as e:
            _log.error(f"清空个人聊天记录失败: {e}")
            return False