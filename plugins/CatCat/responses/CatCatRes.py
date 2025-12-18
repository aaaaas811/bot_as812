from ..utils.api_utils import call_deepseek_chat_api
import re


def format_group_chat(messages):
    """
    将原始群聊记录转换为 API 接受的格式
    输入示例：
        [
            166658.6419105 manager(10101): init catcat
            166658.6430702 何山(7894652): @812 你是谁,
        ]
    """
    # 将每条历史拆成独立的 user message，解析新格式：
    # 可接受的行格式例子：
    #   166658.6419105 manager(10101)[][member][效绿]: init catcat
    #   166658.6430702 何山(7894652)[小何][admin][]: @812 你是谁,
    # 或者带有前置分值：
    #   0.852 166658.6419105 manager(10101)[][member][效绿]: init catcat
    out = []
    # 正则：可选分值，时间戳，昵称(qq)，三个方括号字段，冒号后消息
    pattern = re.compile(r"^\s*(?:(?P<score>\d+\.\d+)\s+)?(?P<ts>\d+(?:\.\d+)?)\s+(?P<nick>[^()\[]+)\((?P<qq>\d+)\)\[(?P<card>[^\]]*)\]\[(?P<role>[^\]]*)\]\[(?P<title>[^\]]*)\]\s*:\s*(?P<msg>.*)$")
    for message in messages:
        try:
            line = message.strip()
            m = pattern.match(line)
            if m:
                nick = m.group('nick').strip()
                qq = m.group('qq').strip()
                card = m.group('card').strip()
                role = m.group('role').strip()
                title = m.group('title').strip()
                msg = m.group('msg').strip()
                # 构建内容，保留方括号信息供模型参考（不带时间戳/分值）
                content = f"{nick}({qq})[{card}][{role}][{title}]: {msg}"
            else:
                # 回退：如果不匹配新格式，尝试按旧规则处理（去掉首个 token）
                parts = line.split()
                content = ' '.join(parts[1:]) if len(parts) > 1 else line

            if content:
                out.append({"role": "user", "content": content})
        except Exception:
            continue
    return out


async def cat_cat_response(api_key, chat_history, prompt):
    """
    参数：
        chat_history: 群聊记录，格式为：
            [
                166658.6419105 manager(10101): init catcat
                166658.6430702 何山(98645135): @812 你是谁,
            ]
    """
    try:
        # prompt 可能包含 persona 描述；我们将其作为 system persona 使用（若无则使用默认简洁指令）
        persona = prompt or "你是群聊机器人812，使用中文，简洁回复，必要时才回复。"
        instruction = "请根据上下文判断是否需要回复，并只输出要说的话，不要任何额外说明或前缀。"
        messages = [
            {"role": "system", "content": persona},
            {"role": "system", "content": instruction},
            *format_group_chat(chat_history),
        ]

        response = await call_deepseek_chat_api(api_key, messages)
        return response.strip('"') if response else ""
    except Exception as e:
        print(f"CatCat响应生成错误: {str(e)}")
