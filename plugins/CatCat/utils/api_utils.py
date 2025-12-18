from ncatbot.utils.logger import get_log
import aiohttp
import json
import os
_log = get_log()


async def call_deepseek_chat_api(api_key, messages):
    url = "https://api.deepseek.com/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    data = {
        "model": "deepseek-chat",
        "thinking": {
            "type": "enabled"
        },
        "frequency_penalty": 1.0,
        "presence_penalty": 0.7,
        "messages": messages,
        "temperature": 1.5,
        "max_tokens": 256,
        "stream": False
    }

    try:
        async with aiohttp.ClientSession() as session:
            # log messages file (ensure directory exists)
            log_path = "plugins/CatCat/logs/deepseek_api/messages.log"
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.write("\n")
            except Exception as e:
                _log.error(f"写入 deepseek_api 日志失败: {e}")
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    try:
                        return result['choices'][0]['message']['content']
                    except KeyError:
                        raise KeyError(f"提取回复时出错，回复内容：{result}")
                else:
                    error_text = await response.text()
                    _log.error(f"API调用失败：状态码 {response.status}，响应内容：{error_text}")
    except aiohttp.ClientError as e:
        _log.error(f"网络请求出错：{str(e)}")
    except Exception as e:
        _log.error(f"未知错误：{str(e)}")