from ..utils.api_utils import call_deepseek_chat_api, call_local_chat_api, call_image_recognition
from ncatbot.utils.logger import get_log
import re
import json
import os
import aiohttp
_log = get_log()
# 每次回复输入的内容为：
# bot人设
# 回复规则
# 用户个人信息
# 历史记录（格式化后）
# 当前消息
def format_group_chat(messages):
    # 将每条历史拆成独立的 message，解析新格式：
    # 可接受的行格式例子：
    #   166658.6419105 manager(10101)[][member][效绿]: init catcat
    #   166658.6430702 何山(7894652)[小何][admin][]: @812 你是谁,
    # 或者带有前置分值：
    #   0.852 166658.6419105 manager(10101)[][member][效绿]: init catcat
    out = []
    # 正则：可选分值，时间戳，昵称(qq)，三个方括号字段，冒号后消息
    pattern = re.compile(r"^\s*(?:(?P<score>\d+\.\d+)\s+)?(?P<ts>\d+(?:\.\d+)?)\s+(?P<nick>[^()\[]+)\((?P<qq>\d+)\)\[(?P<card>[^\]]*)\]\[(?P<role>[^\]]*)\]\[(?P<title>[^\]]*)\]\s*:\s*(?P<msg>.*)$")
    for i, message in enumerate(messages):
        try:
            line = message.strip()
            content = None
            # 如果是 JSON 行，先解析
            try:
                obj = json.loads(line)
                nick = obj.get('nickname', '').strip()
                qq = str(obj.get('qq', '')).strip()
                card = str(obj.get('card', '')).strip()
                role = str(obj.get('role', '')).strip()
                title = str(obj.get('title', '')).strip()
                msg = str(obj.get('message', '')).strip()
                content = f"QQ昵称: {nick}, QQ号: {qq}, 群昵称: {card}, 群权限: {role}, 群头衔: {title}: {msg}"
            except Exception:
                # 不是 JSON，再尝试正则匹配旧/新文本格式
                m = pattern.match(line)
                if m:
                    nick = m.group('nick').strip()
                    qq = m.group('qq').strip()
                    card = m.group('card').strip()
                    role = m.group('role').strip()
                    title = m.group('title').strip()
                    msg = m.group('msg').strip()
                    content = f"QQ昵称: {nick}, QQ号: {qq}, 群昵称: {card}, 群权限: {role}, 群头衔: {title}: {msg}"
                else:
                    # 回退：如果不匹配新格式，尝试按旧规则处理（去掉首个 token）
                    parts = line.split()
                    content = ' '.join(parts[1:]) if len(parts) > 1 else line

            if content:
                # 除了最后一个，其他都设为system
                msg_role = "system" if i < len(messages) - 1 else "user"
                out.append({"role": msg_role, "content": content})
        except Exception:
            continue
    return out


async def cat_cat_response(api_key, chat_history, prompt, image_api_key=None):
    try:
        # prompt 可能包含 persona 描述；我们将其作为 system persona 使用（若无则使用默认简洁指令）
        persona = prompt or "你是群聊机器人812，使用中文，简洁回复。"
        
        instruction = "**重要**请根据上下文判断是否需要回复当前用户的消息。优先回复当前用户消息，避免忽略用户提问。"
        responsetimes = "**重要**每行只说一句话。根据问题确定回复多少行。尽量不超过五行。##之后的内容表示特殊行为，不算做回复内容。不要复读。"
        
        messages = [{"role": "system", "content": persona}]
        # 读取特殊行为文件（每行一个特殊行为），将每行作为 system 内容追加

        # 仅在存在对应提示文本时加入到 messages
        if instruction:
            messages.append({"role": "system", "content": instruction})
        if responsetimes:
            messages.append({"role": "system", "content": responsetimes})
        try:
            # 在 messages 中加入当前 assests 根目录下的表情包列表（作为 system 行）
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
            pass
        # 如果chat_history已经是字典列表，直接使用
        if chat_history and isinstance(chat_history[0], dict):
            messages.extend(chat_history)
        else:
            # 兼容旧格式
            messages.extend(format_group_chat(chat_history))

        # 在消息中加入工具调用说明：当需要识图时，模型应输出单独一行 JSON 格式的工具调用，例如：
        # {"tool_call": {"name": "vision_recognize", "image_index": 0}}
        # 如果模型希望识别图片，请仅输出该 JSON 行，不要输出其它文本。
        tool_instr = (
            "如果需要对消息中的图片进行识别，请输出单独一行 JSON："
            "{\"tool_call\": {\"name\": \"vision_recognize\", \"image_index\": <图片索引>}}。"
            "否则直接给出回复文本。"
        )
        messages.append({"role": "system", "content": tool_instr})

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
        import re, json

        m = re.search(r"\{\s*\"tool_call\"\s*:\s*\{.*?\}\s*\}", response)
        if not m:
            return response.strip('"')

        try:
            tool_json = m.group(0)
            obj = json.loads(tool_json)
            tc = obj.get('tool_call', {})
            if tc.get('name') == 'vision_recognize':
                idx = int(tc.get('image_index', 0))

                # 从 messages 中寻找被列出的图片 url（我们在 build_chat_history 中以 system 行列出）
                img_url = None
                for msg in messages:
                    try:
                        if msg.get('role') == 'system' and msg.get('content', '').startswith('当前消息包含图片/表情片段'):
                            # content 中每行形如: 图片[0]: {url}
                            lines = msg['content'].splitlines()
                            for line in lines:
                                if line.strip().startswith(f"图片[{idx}]:"):
                                    img_url = line.split(':', 1)[1].strip()
                                    break
                            if img_url:
                                break
                    except Exception:
                        continue

                # 无法找到图片 URL，则返回空结果
                if not img_url:
                    tool_result = "[识图失败：未找到对应图片]"
                else:
                    # 获取图片数据：支持 http(s) 下载或本地文件读取或直接 base64 字符串
                    async def _fetch_image_b64(u: str) -> str:
                        u = u or ''
                        u = u.strip()
                        # 已是 base64（较长且无 http 开头），直接返回
                        if len(u) > 100 and not u.startswith('http') and not u.startswith('/'):
                            return u
                        # HTTP 下载
                        if u.startswith('http'):
                            try:
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(u, timeout=15) as resp:
                                        if resp.status == 200:
                                            data = await resp.read()
                                            import base64
                                            return base64.b64encode(data).decode('utf-8')
                            except Exception:
                                return ''
                        # 本地文件
                        try:
                            # 相对路径优先到 assests 目录
                            base = os.path.join(os.path.dirname(__file__), '..', 'assests')
                            fp = os.path.join(base, u) if not os.path.isabs(u) else u
                            if os.path.exists(fp):
                                with open(fp, 'rb') as f:
                                    import base64
                                    return base64.b64encode(f.read()).decode('utf-8')
                        except Exception:
                            return ''
                        return ''

                    img_b64 = await _fetch_image_b64(img_url)
                    if img_b64:
                        tool_result = await call_image_recognition(image_api_key or api_key, img_b64)
                    else:
                        tool_result = "[识图失败：无法获取图片数据]"

                # 将识图结果注入对话：作为 system 内容以便模型在生成回复时参考
                # 同时保留 tool 记录用于审计或后续处理
                try:
                        # 指令明确要求：将识图信息自然地融入回复中，不要复读识图列表，不要以“图片识别结果”开头
                    sys_msg = (
                        "==================================\n" +
                        "识图信息（仅供参考）：\n" + str(tool_result) +
                        "\n【重要】不要输出识图信息，而是根据当前人设，以自然语言输出，可适当概括。"+
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
            return response.strip('"')
    except Exception as e:
        print(f"as812响应生成错误: {str(e)}")
