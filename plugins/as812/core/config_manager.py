"""配置管理器"""
import yaml
import os
from typing import Dict, Any, Optional
from ncatbot.utils.logger import get_log

_log = get_log()


class ConfigManager:
    """配置管理器类"""
    
    def __init__(self, config_path: str = "plugins/as812/config/config.yaml"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
            else:
                _log.warning(f"配置文件不存在: {self.config_path}")
                self.config = {}
        except Exception as e:
            _log.error(f"加载配置文件失败: {e}")
            self.config = {}
    
    def save_config(self) -> bool:
        """保存配置文件"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, default_flow_style=False)
            return True
        except Exception as e:
            _log.error(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """设置配置项并保存"""
        self.config[key] = value
        return self.save_config()
    
    def get_api_key(self) -> Optional[str]:
        """获取API密钥"""
        return self.get("api_key")
    
    def get_active_group_id(self) -> Optional[str]:
        """获取主动回复群ID"""
        return self.get("active_group_id")
    
    def get_super_user(self) -> Optional[str]:
        """获取超级用户ID"""
        return self.get("super_user")
    
    def get_bt_uin(self) -> Optional[str]:
        """获取机器人QQ号"""
        return self.get("bt_uin")
    
    def get_pause_multipliers(self) -> tuple[float, float]:
        """获取暂停乘数"""
        pause_multiplier = float(self.get("pause_multiplier", 0.01))
        line_pause_multiplier = float(self.get("line_pause_multiplier", 0.02))
        return pause_multiplier, line_pause_multiplier
    
    def get_active_reply_config(self) -> tuple[int, int, float]:
        """获取主动回复配置"""
        base_delay = int(self.get("active_reply_delay", 900))
        current_delay = int(self.get("current_active_delay", 0))
        random_range = float(self.get("random_range", 0.2))
        return base_delay, current_delay, random_range
    
    def update_active_delay(self, new_delay: int) -> bool:
        """更新当前主动回复延迟"""
        return self.set("current_active_delay", new_delay)


class PromptManager:
    """提示词管理器"""
    
    def __init__(self, prompt_path: str = "plugins/as812/config/cat_prompt.txt"):
        self.prompt_path = prompt_path
    
    def load_prompt(self) -> str:
        """加载提示词"""
        try:
            if os.path.exists(self.prompt_path):
                with open(self.prompt_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            else:
                _log.warning(f"提示词文件不存在: {self.prompt_path}")
                return ""
        except Exception as e:
            _log.error(f"加载提示词失败: {e}")
            return ""
    
    def save_prompt(self, prompt: str) -> bool:
        """保存提示词"""
        try:
            os.makedirs(os.path.dirname(self.prompt_path), exist_ok=True)
            with open(self.prompt_path, "w", encoding="utf-8") as f:
                f.write(prompt)
            return True
        except Exception as e:
            _log.error(f"保存提示词失败: {e}")
            return False