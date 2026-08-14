from ..utils.api_utils import call_deepseek_chat_api, call_local_chat_api, call_image_recognition
from ncatbot.utils.logger import get_log
import asyncio
import re
import json
import os
import io
import base64
import aiohttp
_log = get_log()

# 跨插件共享的回复阻塞锁：key=group_id, value=asyncio.Lock
# 当 LLM 正在为某个群生成回复时，同群的其他触发源（被动、主动、戳一戳）将被跳过
_reply_locks: dict[str, asyncio.Lock] = {}


def get_reply_lock(group_id: str) -> asyncio.Lock:
    """获取或创建群组对应的回复阻塞锁（跨插件共享）"""
    if group_id not in _reply_locks:
        _reply_locks[group_id] = asyncio.Lock()
    return _reply_locks[group_id]


async def _fetch_image_b64(u: str) -> list[str]:
    """将图片 URL/本地路径/base64 转为 data URL 列表（GIF 会抽样拆帧）。"""
    def _ext_to_mime(path_or_url: str) -> str:
        low = (path_or_url or "").lower()
        if ".gif" in low:
            return "image/gif"
        if ".png" in low:
            return "image/png"
        if ".webp" in low:
            return "image/webp"
        if ".jpeg" in low or ".jpg" in low:
            return "image/jpeg"
        return "image/jpeg"
    def _gif_to_frame_data_urls(data: bytes, max_frames: int = 4) -> list[str]:
        """将 GIF 均匀抽样拆帧，转成 PNG data URL 列表。"""
        try:
            from PIL import Image
            urls: list[str] = []
            with Image.open(io.BytesIO(data)) as im:
                n_frames = max(1, int(getattr(im, "n_frames", 1) or 1))
                sample_count = min(max_frames, n_frames)
                if sample_count == 1:
                    frame_indexes = [0]
                else:
                    step = (n_frames - 1) / (sample_count - 1)
                    frame_indexes = sorted({int(round(i * step)) for i in range(sample_count)})
                for frame_idx in frame_indexes:
                    im.seek(frame_idx)
                    rgb = im.convert("RGB")
                    out = io.BytesIO()
                    rgb.save(out, format="PNG")
                    b64 = base64.b64encode(out.getvalue()).decode("utf-8")
                    urls.append(f"data:image/png;base64,{b64}")
            return urls
        except Exception:
            return []
    def _bytes_to_data_urls(data: bytes, mime_hint: str = "image/jpeg") -> list[str]:
        if not data:
            return []
        if "gif" in (mime_hint or "").lower():
            frames = _gif_to_frame_data_urls(data)
            if frames:
                return frames
        b64 = base64.b64encode(data).decode("utf-8")
        return [f"data:{mime_hint or 'image/jpeg'};base64,{b64}"]
    u = u or ''
    u = u.strip()
    if not u:
        return []
    # 已经是 data URL，直接返回。
    if u.startswith('data:image'):
        return [u]
    # 兼容 base64:// 前缀。
    if u.startswith('base64://'):
        raw = u[len('base64://'):]
        if raw:
            return [f"data:image/jpeg;base64,{raw}"]
    # 本地文件（必须先于 base64 判断：Windows 长路径也会被误判为 base64）
    try:
        base = os.path.join(os.path.dirname(__file__), '..', 'assests')
        fp = os.path.join(base, u) if not os.path.isabs(u) else u
        if os.path.exists(fp):
            with open(fp, 'rb') as f:
                data = f.read()
                return _bytes_to_data_urls(data, _ext_to_mime(fp))
    except Exception:
        return []
    # 已是 base64（较长且无 http 开头），直接返回
    if len(u) > 100 and not u.startswith('http') and not u.startswith('/'):
        return [f"data:image/jpeg;base64,{u}"]
    # HTTP 下载
    if u.startswith('http'):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(u, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        ctype = (resp.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
                        mime = ctype if ctype.startswith('image/') else _ext_to_mime(u)
                        return _bytes_to_data_urls(data, mime)
        except Exception:
            return []
    return []

async def cat_cat_response(api_key, chat_history, prompt, image_api_key=None, rag_context="", get_image_cb=None):
    try:
        # prompt 可能包含 persona 描述；我们将其作为 system persona 使用（若无则使用默认简洁指令）
        persona = prompt or "你是群聊机器人812，使用中文，简洁回复。"
        
        instruction = "请根据上下文判断是否需要回复当前用户的消息。优先回复当前用户消息，避免忽略用户提问。不直接输出识图结果。回复要自然口语化，像真人聊天，避免模板化开头（如“好的呢”“没问题”“收到”），不要机械复述用户的话。"
        responsetimes = "每行只说一句话。根据问题确定回复多少行。尽量不超过五行。偶尔可以只回一句很短的话或一个语气词，不必每次都说满。##之后的内容表示特殊行为，不算做回复内容。不要复读。"
        
        # 构建消息列表：固定前缀部分在前（最大化缓存命中），可变部分在后
        messages = [{"role": "system", "content": persona}]

        if instruction:
            messages.append({"role": "system", "content": instruction})
        if responsetimes:
            messages.append({"role": "system", "content": responsetimes})

        # 表情包列表（固定内容，加入缓存前缀）
        try:
            assets_dir = os.path.join(os.path.dirname(__file__), "..", "assests")
            emoji_names = []
            if os.path.isdir(assets_dir):
                for fn in os.listdir(assets_dir):
                    fp = os.path.join(assets_dir, fn)
                    if os.path.isfile(fp):
                        name, ext = os.path.splitext(fn)
                        if ext.lower() in ('.png', '.jpg', '.jpeg'):
                            emoji_names.append(name)
            if emoji_names:
                emoji_str = '、'.join(sorted(set(emoji_names)))
                messages.append({"role": "system", "content": f"目前表情包列表：{emoji_str}"})
            else:
                messages.append({"role": "system", "content": "目前表情包列表：无"})
        except Exception:
            _log.exception("读取表情包目录失败")

        # 特殊行为规则（固定内容，加入缓存前缀）
        try:
            spath = os.path.join(os.path.dirname(__file__), "spacial_actions.txt")
            if os.path.exists(spath):
                with open(spath, 'r', encoding='utf-8') as f:
                    for raw in f:
                        line = raw.strip()
                        if not line:
                            continue
                        messages.append({"role": "system", "content": line})
        except Exception:
            _log.exception("读取特殊行为文件失败")

        # 工具调用说明（固定内容，加入缓存前缀）
        tool_instr = (
            "重要：当系统消息列出了图片索引（如\"图片[0]: ...\"）且用户的消息涉及图片内容时，"
            "你必须输出单独一行 JSON 来请求识图："
            "{\"tool_call\": {\"name\": \"vision_recognize\", \"image_index\": <图片索引>}}。"
            "不要自行猜测图片内容，也不要回复\"看不清\"——请先调用工具获取识图结果。"
            "如果没有图片索引或用户消息与图片无关，则直接给出回复文本。"
        )
        messages.append({"role": "system", "content": tool_instr})

        # --- 以上为固定前缀（可被 LLM 缓存），以下为每次请求可变的部分 ---

        # RAG 上下文（按需注入，内容可变）
        if rag_context:
            messages.append({"role": "system", "content": rag_context})

        # 聊天历史与当前消息（内容可变）
        if chat_history and isinstance(chat_history[0], dict):
            messages.extend(chat_history)
        else:
            # 兜底：非结构化历史按文本行追加（当前所有调用方均传入结构化 dict，此分支仅为防御）
            for line in chat_history or []:
                messages.append({"role": "user", "content": str(line)})

        # 将内部的 tool 角色消息转换为对外 API 可接受的 assistant 角色
        def _prepare_for_api(orig_msgs):
            out = []
            for m in orig_msgs:
                if m.get('role') == 'tool':
                    # 转为 assistant，删除 name 字段以保持兼容
                    out.append({"role": "assistant", "content": m.get('content', '')})
                else:
                    # 直接传递其它字段（assume serializable）
                    out.append(m)
            return out

        # 发送请求并检测是否为工具调用（最多一次循环：工具调用后再询问模型）
        async def _send_and_check(msgs):
            send_msgs = _prepare_for_api(msgs)
            # 优先本地模型
            if api_key and (str(api_key).lower() == 'local' or str(api_key).startswith('local:')):
                model_name = None
                if str(api_key).startswith('local:'):
                    model_name = str(api_key).split(':', 1)[1]
                return await call_local_chat_api(model_name, send_msgs)
            else:
                return await call_deepseek_chat_api(api_key, send_msgs)

        response = await _send_and_check(messages)
        if not response:
            return ""

        # 检查模型是否请求工具调用（寻找 tool_call JSON）
        m = re.search(r"\{\s*\"tool_call\"\s*:\s*\{.*?\}\s*\}", response)
        if not m:
            return response.strip('"')

        try:
            tool_json = m.group(0)
            obj = json.loads(tool_json)
            tc = obj.get('tool_call', {})
            if tc.get('name') == 'vision_recognize':
                raw_idx = tc.get('image_index', 0)
                # 兼容 image_index 为列表的情况（如 [0]）
                if isinstance(raw_idx, list):
                    raw_idx = raw_idx[0] if raw_idx else 0
                idx = int(raw_idx)

                # 从 messages 中寻找被列出的图片文件标识（build_chat_history 以 system 行列出）
                # 注：QQ 图片 URL（gchat.qpic.cn 的 rkey）会过期，统一走 NapCat get_image 取图
                img_file = None
                for msg in messages:
                    try:
                        if msg.get('role') == 'system' and msg.get('content', '').startswith('当前消息包含图片/表情片段'):
                            # content 中每行形如: 图片[0]: {url} / 文件[0]: {file}
                            lines = msg['content'].splitlines()
                            for line in lines:
                                if line.strip().startswith(f"文件[{idx}]:"):
                                    img_file = line.split(':', 1)[1].strip()
                                    break
                            # 旧格式无 文件 行时退回 图片 行（此时内容即本地路径或可用 URL）
                            if not img_file:
                                for line in lines:
                                    if line.strip().startswith(f"图片[{idx}]:"):
                                        img_file = line.split(':', 1)[1].strip()
                                        break
                            if img_file:
                                break
                    except Exception:
                        continue

                # 无法找到图片文件标识，则返回空结果
                if not img_file:
                    _log.info("[识图] 未找到图片文件标识")
                    tool_result = "[识图失败：未找到对应图片]"
                else:
                    _log.info(f"[识图] file={img_file} cb={'有' if get_image_cb else '无'}")
                    img_inputs = []
                    if get_image_cb:
                        try:
                            local_path = await get_image_cb(img_file)
                            if local_path:
                                img_inputs = await _fetch_image_b64(str(local_path))
                                _log.info(f"[识图] get_image 取图: {'成功' if img_inputs else '失败'}")
                        except Exception as e:
                            _log.warning(f"按文件标识取图失败: {e}")
                    # 非 NapCat 文件标识时（如 http URL），直接走下载
                    if not img_inputs and img_file.startswith(('http', 'base64://', 'data:image')):
                        img_inputs = await _fetch_image_b64(img_file)
                    if img_inputs:
                        tool_result = await call_image_recognition(image_api_key or api_key, img_inputs)
                        _log.info(f"[识图] MIMO 识别: {str(tool_result)[:80]}")
                    else:
                        tool_result = "[识图失败：无法获取图片数据]"

                # 将识图结果注入对话：作为 system 内容以便模型在生成回复时参考
                # 同时保留 tool 记录用于审计或后续处理
                try:
                    # 指令明确要求：将识图信息自然地融入回复中，不要复读识图列表，不要以“图片识别结果”开头
                    sys_msg = (
                        "==================================\n"
                        "识图信息（仅供参考）：\n" + str(tool_result) +
                        "\n【重要】不要直输出识图信息，而是根据当前人设，以自然语言输出，可适当概括。" +
                        "\n=================================="
                    )
                    messages.append({"role": "system", "content": sys_msg})
                except Exception:
                    pass

                messages.append({"role": "tool", "name": "vision_recognize", "content": tool_result})
                # 重新调用模型，让模型把识图结果作为上下文一并考虑
                response2 = await _send_and_check(messages)
                # 若模型没有返回可用回复，则使用简短自然语言的回退总结
                if not response2 or re.search(r"\{\s*\"tool_call\"\s*:\s*\{.*?\}\s*\}", response2):
                    summary = str(tool_result).strip().replace('\n', '；')
                    if not summary:
                        return "看不清图片的内容"
                    if len(summary) > 120:
                        summary = summary[:120].rstrip() + '...'
                    return f"{summary}"
                return response2.strip('"')
        except Exception:
            _log.exception('处理工具调用失败')
            return ""
    except Exception as e:
        print(f"as812响应生成错误: {str(e)}")
