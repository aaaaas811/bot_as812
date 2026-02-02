"""简化的API工具函数"""
"""简化的API工具函数：支持 DeepSeek (HTTP) 和本地 Ollama 模型调用"""
import aiohttp
import json
from typing import Optional
from ncatbot.utils.logger import get_log

_log = get_log()

# 尝试导入 ollama SDK（AsyncClient）用于本地模型 qwen3:8b
try:
    from ollama import AsyncClient
    _has_ollama = True
except Exception:
    AsyncClient = None  # type: ignore
    _has_ollama = False


async def call_deepseek_chat_api(api_key: str, messages: list) -> Optional[str]:
    """调用 DeepSeek HTTP API（保留旧实现）"""
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
        "frequency_penalty": 1.3,
        "presence_penalty": 0.8,
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


async def call_local_chat_api(model_name: Optional[str] = None, messages: list = None, stream: bool = False) -> Optional[str]:
    """使用本地 Ollama 服务调用模型并返回字符串响应。

    - 默认模型为 `qwen3`。
    - 使用 `think=False` 来取消链式/深度思考（不再通过 prompt 插入“别想太多”类系统消息）。
    - 使用更低的 `temperature`（更确定的回复）。
    - 使用 AsyncClient 进行异步调用；如果未安装 ollama，则退回到简单的模拟回复。
    """
    if model_name is None:
        model_name = "qwen3:8b"

    if not messages:
        _log.warning("call_local_chat_api: messages 为空")
        return None

    if not _has_ollama:
        _log.warning("未检测到 ollama SDK，使用本地模拟回复")
        return "本地模型不可用，请安装 ollama SDK。"
    options={
    "temperature": 1.3,      # 温度，控制随机性（0-2）
    "top_p": 0.9,           # 核采样参数
    "top_k": 40,            # 保留前 k 个 token
    "repeat_penalty": 1.3,  # 重复惩罚
    "repeat_last_n": 64,            # 检查最近多少个token的重复
    "frequency_penalty": 0.1,       # 频率惩罚（降低常用词概率）
    "presence_penalty": 0.1,        # 存在惩罚（降低已出现词概率）
    "num_predict": 512,     # 最大生成长度
    "stop":None   # 停止词
   }
    try:
        client = AsyncClient()
        if stream:
            content_parts = []
            # 传入 think=False 与较低的 temperature，保留 stream=True
            async for part in await client.chat(
                model=model_name, 
                messages=messages,
                stream=True, 
                think=False,
                options=options,
                keep_alive=-1):
                try:
                    chunk = part.get('message', {}).get('content', '') if isinstance(part, dict) else getattr(part, 'message', None).content
                except Exception:
                    try:
                        chunk = part['message']['content']
                    except Exception:
                        chunk = str(part)
                if chunk:
                    content_parts.append(chunk)
            return ''.join(content_parts)
        else:
            resp = await client.chat(
            model=model_name, 
            messages=messages, 
            think=False,
            options=options,
            keep_alive=-1)
            try:
                content = resp.get('message', {}).get('content', '') if isinstance(resp, dict) else None
            except Exception:
                content = None
            if not content:
                try:
                    content = getattr(resp, 'message', None).content  # type: ignore
                except Exception:
                    content = str(resp)
            return content
    except Exception as e:
        _log.error(f"调用本地 Ollama 模型失败: {e}")
        return None
