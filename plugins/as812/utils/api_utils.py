"""简化的API工具函数：支持兼容 OpenAI 的 HTTP 模型与本地 Ollama 调用"""
import aiohttp
from pathlib import Path
from typing import Optional

import yaml
from ncatbot.utils.logger import get_log

_log = get_log()

DEFAULT_HTTP_BASE_URL = "http://172.22.2.242:3010/v1"
DEFAULT_HTTP_MODEL = "Qwen3.5-Plus"


def _get_http_chat_config() -> tuple[str, str]:
    """读取 HTTP 聊天模型的 base_url 与 model 配置。"""
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    try:
        if not cfg_path.exists():
            return DEFAULT_HTTP_BASE_URL, DEFAULT_HTTP_MODEL

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        base_url = str(cfg.get("api_base_url", DEFAULT_HTTP_BASE_URL)).strip()
        model = str(cfg.get("api_model", DEFAULT_HTTP_MODEL)).strip()
        return base_url or DEFAULT_HTTP_BASE_URL, model or DEFAULT_HTTP_MODEL
    except Exception as e:
        _log.warning(f"读取 HTTP 模型配置失败，使用默认值: {e}")
        return DEFAULT_HTTP_BASE_URL, DEFAULT_HTTP_MODEL

# 尝试导入 ollama SDK（AsyncClient）用于本地模型 qwen3:8b
try:
    from ollama import AsyncClient
    _has_ollama = True
except Exception:
    AsyncClient = None  # type: ignore
    _has_ollama = False


async def call_deepseek_chat_api(api_key: str, messages: list) -> Optional[str]:
    """调用兼容 OpenAI 的 HTTP Chat API。"""
    if not api_key:
        _log.error("API密钥为空")
        return None

    base_url, model_name = _get_http_chat_config()
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.3,
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
                    _log.error(f"HTTP Chat API错误: {response.status} - {error_text}")
                    return None
    except Exception as e:
        _log.error(f"调用HTTP Chat API失败: {e}")
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
    "temperature": 0.3,      # 温度，控制随机性（0-2）
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


async def call_image_recognition(api_key: str, image_base64: str) -> Optional[str]:
    """调用第三方识图接口（优先使用 zai-sdk 的知谱云示例），返回识别结果文本。

    - image_base64: 图片的 base64 文本（不包含 data: 前缀）
    - 如果没有可用 SDK，则返回提示性文本以便模型继续处理。
    """
    if not image_base64:
        return ""

    # 尝试使用 zai-sdk（知谱云）
    try:
        try:
            from zai import ZhipuAiClient
        except Exception:
            ZhipuAiClient = None

        if ZhipuAiClient is not None and api_key:
            def _sync_call():
                try:
                    client = ZhipuAiClient(api_key=api_key)
                    # 请求外部识图模型，强制要求返回 1-2 句的自然语言描述（不要列点）
                    resp = client.chat.completions.create(
                        model="glm-4.6v-flash",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": image_base64}},
                                    {"type": "text", "text": (
                                        "请用一到两句话自然地描述这张图片，避免列点或表格，"
                                    )}
                                ]
                            }
                        ],
                        thinking={"type": "enabled"}
                    )
                    # 兼容不同 SDK 返回格式，尽量提取可读文本
                    try:
                        # 支持 dict 风格返回
                        if isinstance(resp, dict):
                            choices = resp.get('choices') or []
                            if choices:
                                msg = choices[0].get('message') or choices[0]
                                # message 可能是 dict with content or simple string
                                if isinstance(msg, dict):
                                    return msg.get('content') or msg.get('text') or str(msg)
                                return str(msg)
                        # 支持对象风格返回
                        if getattr(resp, 'choices', None):
                            ch = getattr(resp, 'choices')
                            first = ch[0]
                            # first may have .message.content
                            try:
                                return first.message.content
                            except Exception:
                                try:
                                    return first.get('message', {}).get('content')
                                except Exception:
                                    return str(first)
                        return str(resp)
                    except Exception:
                        return str(resp)
                except Exception as e:
                    _log.error(f"zai 识图请求失败: {e}")
                    return None

            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _sync_call)
            try:
                # 如果 result 是对象，尝试提取 content
                if isinstance(result, dict):
                    return result.get('content') or result.get('message') or str(result)
                return getattr(result, 'content', None) or str(result)
            except Exception:
                return str(result)

    except Exception:
        _log.exception("尝试使用 zai-sdk 识图时出错")

    # 后备：无法调用外部识图服务时，返回占位文本
    return "[识图不可用：未配置识图服务]"
