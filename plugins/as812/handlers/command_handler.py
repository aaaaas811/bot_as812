"""命令处理器"""
import os
from typing import Dict, Any
from ncatbot.utils.logger import get_log
from ..core.config_manager import ConfigManager, PromptManager
from ..core.log_manager import LogManager
from ..personality_summary import summarize_personality

_log = get_log()


class CommandHandler:
    """命令处理器类"""
    
    def __init__(self, config_manager: ConfigManager, prompt_manager: PromptManager, log_manager: LogManager):
        self.config_manager = config_manager
        self.prompt_manager = prompt_manager
        self.log_manager = log_manager
    
    async def handle_private_command(self, api, user_id: int, message: str) -> None:
        """处理私聊命令"""
        if message == "view_config":
            await self._handle_view_config(api, user_id)
        elif message.startswith("set_prompt"):
            await self._handle_set_prompt(api, user_id, message)
        elif message.startswith("set_"):
            await self._handle_set_config(api, user_id, message)
        elif message == "prompt":
            await self._handle_show_prompt(api, user_id)
        elif message == "manual_summary":
            await self._handle_manual_summary(api, user_id)
        elif message.startswith("reset_summary "):
            await self._handle_reset_summary(api, user_id, message)
    
    async def _handle_view_config(self, api, user_id: int) -> None:
        """查看配置"""
        config = self.config_manager.config
        config_lines = []
        for key, value in config.items():
            if key not in ["api_key", "cat_prompt"]:
                config_lines.append(f"{key}: {value}")
        config_text = "\n".join(config_lines)
        await api.post_private_msg(user_id, text=f"当前配置（除api_key和cat_prompt外）：\n{config_text}")
    
    async def _handle_set_prompt(self, api, user_id: int, message: str) -> None:
        """设置提示词"""
        value = message[10:].strip()
        if self.prompt_manager.save_prompt(value):
            await api.post_private_msg(user_id, text="设置成功")
        else:
            await api.post_private_msg(user_id, text="设置失败")
    
    async def _handle_set_config(self, api, user_id: int, message: str) -> None:
        """设置配置项"""
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式错误，请使用 set_<key> <value>")
            return
        
        key = parts[0][4:]  # 去掉"set_"
        value = parts[1]
        
        if key in self.config_manager.config and key != "api_key":
            # 尝试转换类型
            if key in ["active_group_id", "super_user"]:
                self.config_manager.config[key] = str(value)
            else:
                self.config_manager.config[key] = value
            
            if self.config_manager.save_config():
                await api.post_private_msg(user_id, text=f"{key} 设置为 {value} 成功")
            else:
                await api.post_private_msg(user_id, text=f"{key} 设置失败")
        else:
            await api.post_private_msg(user_id, text=f"未知配置项: {key}")
    
    async def _handle_show_prompt(self, api, user_id: int) -> None:
        """显示提示词"""
        cat_prompt = self.prompt_manager.load_prompt()
        await api.post_private_msg(user_id, text=cat_prompt)
    
    async def _handle_manual_summary(self, api, user_id: int) -> None:
        """手动总结用户信息"""
        await api.post_private_msg(user_id, text="开始手动总结用户信息...")
        
        summary_threshold = self.config_manager.get("summary_threshold", 25)
        processed_count = 0
        skipped_count = 0
        
        # 遍历所有群组目录
        logs_dir = "plugins/as812/logs"
        if os.path.exists(logs_dir):
            for group_dir in os.listdir(logs_dir):
                group_path = os.path.join(logs_dir, group_dir)
                if os.path.isdir(group_path) and not group_dir.endswith("_history.log"):
                    gid = group_dir
                    
                    # 遍历该群的所有用户日志
                    for user_file in os.listdir(group_path):
                        if user_file.endswith(".log"):
                            user_qq = user_file[:-4]  # 去掉.log扩展名
                            user_log_path = os.path.join(group_path, user_file)
                            
                            try:
                                # 加载用户数据
                                personal_history, user_info_str, personality_summary, personal_log_file = \
                                    self.log_manager.load_personal_log(gid, user_qq)
                                
                                # 检查是否需要总结
                                if len(personal_history) >= summary_threshold:
                                    api_key = self.config_manager.get_api_key()
                                    if api_key:
                                        await summarize_personality(user_log_path, api_key, user_info_str)
                                        processed_count += 1
                                        _log.info(f"已总结用户 {user_qq} 在群 {gid} 的信息")
                                    else:
                                        _log.warning("API密钥未配置，无法总结")
                                else:
                                    skipped_count += 1
                                    
                            except Exception as e:
                                _log.error(f"处理用户 {user_qq} 在群 {gid} 时出错: {e}")
                                await api.post_private_msg(user_id, text=f"处理用户 {user_qq} 时出错: {e}")
        
        await api.post_private_msg(user_id, text=f"手动总结完成！\n已处理: {processed_count} 个用户\n跳过: {skipped_count} 个用户")
    
    async def _handle_reset_summary(self, api, user_id: int, message: str) -> None:
        """重置用户个性总结"""
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await api.post_private_msg(user_id, text="格式错误，请使用 reset_summary <qq号>")
            return
        
        target_qq = parts[1].strip()
        reset_count = 0
        
        # 遍历所有群组目录
        logs_dir = "plugins/as812/logs"
        if os.path.exists(logs_dir):
            for group_dir in os.listdir(logs_dir):
                group_path = os.path.join(logs_dir, group_dir)
                if os.path.isdir(group_path) and not group_dir.endswith("_history.log"):
                    gid = group_dir
                    user_log_path = os.path.join(group_path, f"{target_qq}.log")
                    
                    if os.path.exists(user_log_path):
                        try:
                            # 读取文件内容
                            with open(user_log_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            
                            # 解析基本信息
                            user_info_str = ""
                            if "该用户的基本信息：" in content:
                                start = content.find("该用户的基本信息：") + len("该用户的基本信息：")
                                end = content.find("\n\n该用户的个性总结：", start)
                                if end == -1:
                                    end = content.find("\n\n过往聊天记录：", start)
                                user_info_str = content[start:end].strip()
                            
                            # 重置个性总结为空
                            new_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n\n过往聊天记录：\n"
                            
                            # 如果有聊天记录，保留它们
                            if "过往聊天记录：" in content:
                                records_start = content.find("过往聊天记录：") + len("过往聊天记录：")
                                records = content[records_start:].strip()
                                if records:
                                    new_content += records + "\n"
                            
                            with open(user_log_path, "w", encoding="utf-8") as f:
                                f.write(new_content)
                            
                            reset_count += 1
                            _log.info(f"已重置用户 {target_qq} 在群 {gid} 的个性总结")
                            
                        except Exception as e:
                            _log.error(f"重置用户 {target_qq} 在群 {gid} 时出错: {e}")
                            await api.post_private_msg(user_id, text=f"重置用户 {target_qq} 时出错: {e}")
        
        if reset_count > 0:
            await api.post_private_msg(user_id, text=f"已重置用户 {target_qq} 的个性总结")
        else:
            await api.post_private_msg(user_id, text=f"未找到用户 {target_qq} 的日志文件")