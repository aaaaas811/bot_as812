from ..utils.api_utils import call_deepseek_chat_api
import re
import json


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
        persona = prompt or "你是群聊机器人812，使用中文，简洁回复，必要时才回复。"
        instruction = "请根据上下文判断是否需要回复当前用户的消息，并只输出要说的话，不要任何额外说明或前缀。优先考虑当前消息的内容，保持角色一致性。"
        messages = [
            {"role": "system", "content": persona},
            {"role": "system", "content": instruction},
        ]
        # 如果chat_history已经是字典列表，直接使用
        if chat_history and isinstance(chat_history[0], dict):
            messages.extend(chat_history)
        else:
            # 兼容旧格式
            messages.extend(format_group_chat(chat_history))

        response = await call_deepseek_chat_api(api_key, messages)
        return response.strip('"') if response else ""
    except Exception as e:
        print(f"CatCat响应生成错误: {str(e)}")
