from ..utils.api_utils import call_deepseek_chat_api, call_local_chat_api
from ncatbot.utils.logger import get_log
import re
import json
import os
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


async def cat_cat_response(api_key, chat_history, prompt):
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

        # 支持本地模型：在 config 中将 api_key 设置为 `local` 或 `local:<模型名>` 来使用本地模型
        if api_key and (str(api_key).lower() == 'local' or str(api_key).startswith('local:')):
            model_name = None
            if str(api_key).startswith('local:'):
                model_name = str(api_key).split(':', 1)[1]
            response = await call_local_chat_api(model_name, messages)
        else:
            response = await call_deepseek_chat_api(api_key, messages)
        return response.strip('"') if response else ""
    except Exception as e:
        print(f"as812响应生成错误: {str(e)}")
