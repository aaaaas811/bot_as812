"""简化的API工具函数"""
import aiohttp
import json
from typing import Optional
from ncatbot.utils.logger import get_log

_log = get_log()

async def call_deepseek_chat_api(api_key: str, messages: list) -> Optional[str]:
    """调用DeepSeek API"""
    if not api_key:
        _log.error("API密钥为空")
        return None
    
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 1.3,
        "max_tokens": 2000,
        "stream": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("choices", [{}])[0].get("message", {}).get("content", "")
                else:
                    error_text = await response.text()
                    _log.error(f"DeepSeek API错误: {response.status} - {error_text}")
                    return None
    except Exception as e:
        _log.error(f"调用DeepSeek API失败: {e}")
        return None

async def call_local_chat_api(model_name: Optional[str] = None, messages: list = None) -> Optional[str]:
    """调用本地模型API（简化版）"""
    _log.warning("本地模型功能已禁用，返回测试响应")
    
    # 模拟响应
    if messages and len(messages) > 0:
        last_message = messages[-1].get("content", "") if isinstance(messages[-1], dict) else str(messages[-1])
        
        # 简单的回复逻辑
        if "你好" in last_message or "hi" in last_message.lower():
            return "你好呀！我是812~"
        elif "天气" in last_message:
            return "今天天气不错呢~"
        elif "?" in last_message or "？" in last_message:
            return "这个问题很有趣呢~"
        else:
            return "嗯嗯，我在听呢~"
    return "你好，我是812~"
