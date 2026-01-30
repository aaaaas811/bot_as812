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

    - 默认模型为 `qwen3:8b`。
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

    try:
        client = AsyncClient()
        if stream:
            # 流式响应：按块拼接并返回完整文本
            content_parts = []
            # AsyncClient.chat(..., stream=True) 返回的是异步可迭代项
            async for part in await client.chat(model=model_name, messages=messages, stream=True):
                # part 可能是 dict 或对象，这里尽量兼容两种访问方式
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
            resp = await client.chat(model=model_name, messages=messages)
            # 尝试从响应对象/字典中抽取文本
            try:
                # dict 风格
                content = resp.get('message', {}).get('content', '') if isinstance(resp, dict) else None
            except Exception:
                content = None
            if not content:
                try:
                    # 对象风格
                    content = getattr(resp, 'message', None).content  # type: ignore
                except Exception:
                    content = str(resp)
            return content
    except Exception as e:
        _log.error(f"调用本地 Ollama 模型失败: {e}")
        return None
