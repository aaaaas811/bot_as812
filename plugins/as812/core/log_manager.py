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
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
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
    
    def load_personal_log(self, group_id: str, user_qq: str) -> Tuple[List[str], str, str, str]:
        """
        加载个人日志
        返回: (聊天记录列表, 用户信息字符串, 个性总结字符串, 日志文件路径)
        """
        log_path = self.get_personal_log_path(group_id, user_qq)
        
        personal_history = []
        user_info_str = ""
        personality_summary = ""
        
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 解析基本信息
                if "该用户的基本信息：" in content:
                    start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                    end = content.find("\n\n该用户的个性总结：", start)
                    if end == -1:
                        end = content.find("\n\n过往聊天记录：", start)
                    user_info_str = content[start:end].strip()
                
                # 解析个性总结
                if "该用户的个性总结：" in content:
                    start = content.find("该用户的个性总结：") + len("该用户的个性总结：")
                    end = content.find("\n\n过往聊天记录：", start)
                    if end == -1:
                        end = len(content)
                    personality_summary = content[start:end].strip()
                
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
            initial_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n\n过往聊天记录：\n"
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(initial_content)
            except Exception as e:
                _log.error(f"创建个人日志失败: {e}")
        
        return personal_history, user_info_str, personality_summary, log_path
    
    def append_to_personal_log(self, log_path: str, content: str) -> bool:
        """向个人日志追加内容"""
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            return True
        except Exception as e:
            _log.error(f"追加个人日志失败: {e}")
            return False
    
    def update_personal_log_header(self, log_path: str, new_user_info: str, new_personality_summary: str = "") -> bool:
        """更新个人日志头部信息"""
        try:
            if not os.path.exists(log_path):
                return False
            
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 更新用户信息
            if "该用户的基本信息：" in content:
                start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                end = content.find("\n\n该用户的个性总结：", start)
                if end == -1:
                    end = content.find("\n\n过往聊天记录：", start)
                old_user_info = content[start:end].strip()
                content = content.replace(f"该用户的基本信息：{old_user_info}", f"该用户的基本信息：{new_user_info}")
            
            # 更新个性总结（如果提供）
            if new_personality_summary and "该用户的个性总结：" in content:
                start = content.find("该用户的个性总结：") + len("该用户的个性总结：")
                end = content.find("\n\n过往聊天记录：", start)
                if end == -1:
                    end = len(content)
                old_summary = content[start:end].strip()
                content = content.replace(f"该用户的个性总结：{old_summary}", f"该用户的个性总结：{new_personality_summary}")
            
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
            
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            
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