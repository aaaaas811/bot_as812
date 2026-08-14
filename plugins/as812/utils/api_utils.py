"""简化的API工具函数：支持兼容 OpenAI 的 HTTP 模型与本地 Ollama 调用"""
import aiohttp
from pathlib import Path
from typing import Optional

import yaml
from ncatbot.utils.logger import get_log

_log = get_log()



def _get_http_chat_config() -> tuple[str, str]:
    """读取 HTTP 聊天模型的 base_url 与 model 配置。"""
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    try:

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        base_url = str(cfg.get("api_base_url")).strip()
        model = str(cfg.get("api_model")).strip()
        return base_url, model
    except Exception as e:
        _log.warning(f"读取 HTTP 模型配置失败")
        return None, None

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


async def call_image_recognition(api_key: str, image_inputs: str | list[str]) -> Optional[str]:
    """调用 MIMO 识图接口（Anthropic 兼容端点），支持单图或多图输入。

    - image_inputs: 单个图片 data url/base64，或多个图片 data url/base64 列表。
    - 配置与 mimo-image-recognition-mcp 相同：mimo-v2.5 + token-plan-cn 端点。
    """
    if isinstance(image_inputs, str):
        image_urls = [image_inputs] if image_inputs else []
    else:
        image_urls = [x for x in (image_inputs or []) if x]

    if not image_urls:
        return ""

    # 构建 OpenAI 兼容格式的图片块（与 mimo-image-recognition-mcp 相同）
    image_blocks = [
        {"type": "image_url", "image_url": {"url": url}}
        for url in image_urls
    ]
    image_blocks.append({
        "type": "text",
        "text": "请用一到两句话自然地描述这些图片（它们可能来自同一张 GIF 的多个帧），避免列点或表格。",
    })

    url = "https://api.xiaomimimo.com/v1/chat/completions"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "model": "mimo-v2.5",
        "messages": [{"role": "user", "content": image_blocks}],
        "temperature": 0.2,
        "max_tokens": 1024,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=120) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    _log.error(f"MIMO 识图 API 错误: {resp.status} - {err_text[:200]}")
                    return "[识图失败：服务返回错误]"
                result = await resp.json()
                # OpenAI 格式：choices[0].message.content
                try:
                    choices = result.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or {}
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            return content.strip() if content.strip() else "[识图失败：服务未返回文本]"
                        # content 可能是列表（多模态返回）
                        text_parts = [
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        text = "".join(text_parts).strip()
                        return text if text else "[识图失败：服务未返回文本]"
                except Exception:
                    pass
                return "[识图失败：无法解析响应]"
    except Exception as e:
        _log.error(f"调用 MIMO 识图 API 失败: {e}")
        return "[识图失败：无法连接识图服务]"
