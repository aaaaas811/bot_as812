import os
from .responses.CatCatRes import cat_cat_response


def parse_log_content(content: str):
    """解析已有日志内容，返回 (basic_info, existing_summary, chat_history)。

    如果未找到相应段落，会返回空字符串；若文件为纯聊天记录，则把全部内容作为聊天记录返回。
    """
    if not content:
        return "", "", ""

    def extract_section(s, start_marker, end_marker=None):
        try:
            start = s.index(start_marker) + len(start_marker)
        except ValueError:
            return ""
        if end_marker:
            try:
                end = s.index(end_marker, start)
                return s[start:end].strip()
            except ValueError:
                return s[start:].strip()
        else:
            return s[start:].strip()

    basic_info = extract_section(content, "该用户的基本信息：", "该用户的个性总结：")
    existing_summary = extract_section(content, "该用户的个性总结：", "过往聊天记录：")
    chat_history = extract_section(content, "过往聊天记录：", None)

    # 如果三个标记都不存在，则把全部内容作为聊天记录返回
    if not (basic_info or existing_summary or chat_history):
        return "", "", content.strip()

    return basic_info, existing_summary, chat_history


def format_log_file(basic_info: str, personality_summary: str, chat_history: str) -> str:
    """按指定格式构建日志文件内容：三部分（基本信息、个性总结、过往聊天记录）。"""
    basic_info = basic_info.strip()
    personality_summary = personality_summary.strip()
    chat_history = chat_history.strip()

    return (
        f"该用户的基本信息：{basic_info}\n\n"
        f"该用户的个性总结：\n{personality_summary}\n\n"
        f"过往聊天记录：\n{chat_history}\n"
    )


def is_format_correct(content: str) -> bool:
    """检查内容是否包含三个必需的段落标记：基本信息、个性总结、过往聊天记录。"""
    if not content:
        return False
    return (
        "该用户的基本信息：" in content
        and "该用户的个性总结：" in content
        and "过往聊天记录：" in content
    )


def adjust_format_if_needed(log_file_path: str, user_info_str: str = "", max_attempts: int = 3) -> bool:
    """如果文件格式不对，尝试修正并覆盖文件，最多重复 max_attempts 次。

    返回 True 表示文件最终为正确格式，False 表示尝试后仍然不符合。
    """
    for _ in range(max_attempts):
        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = ""

        if is_format_correct(content):
            return True

        # 解析已有内容并构建规范内容
        basic_info, existing_summary, chat_history = parse_log_content(content)
        if not basic_info.strip():
            basic_info = user_info_str or ""

        new_content = format_log_file(basic_info, existing_summary or "", chat_history or "")
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    # 最后再检查一次
    if os.path.exists(log_file_path):
        with open(log_file_path, "r", encoding="utf-8") as f:
            return is_format_correct(f.read())
    return False


async def summarize_personality(log_file_path, api_key, user_info_str):
    # 确保目录存在
    parent_dir = os.path.dirname(log_file_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    # 如果格式不对，先尝试修正一次
    try:
        adjust_format_if_needed(log_file_path, user_info_str)
    except Exception:
        pass

    # 读取现有文件（如果存在）
    if os.path.exists(log_file_path):
        with open(log_file_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = ""

    basic_info, existing_summary, chat_history = parse_log_content(content)

    # 如果文件中没有基本信息，则使用传入的 user_info_str
    if not basic_info.strip():
        basic_info = user_info_str or ""

    # 构建 prompt，传入已有的个性总结（供更新）与过往聊天记录
    prompt = f"""请分析以下用户的聊天日志，提取对话中的有效信息，并结合用户当前的个性总结（如果存在），生成一个新的、准确的用户个性关键词列表。

分析要求：
1. 仔细阅读用户的每条消息，提取关键信息、兴趣爱好、说话风格、性格特征等
2. 重要：区分用户自己的言论和引用/转述别人的话。不要将引用内容当作用户的个人特征
3. 如果已有个性总结，请在原有基础上进行更新和完善，而不是完全重写
4. 原个性总结中的错误信息应该被删除或修正
5. 重点关注用户的语言习惯、情感表达、话题偏好、互动模式等，更加有特色的信息优先
6. 生成的个性总结应该简洁但全面，只记录有特色的内容
7. 个性总结应该为数个句子的结合，使用逗号分隔不同的特征描述
8. 句子上限尽量控制在5句以内，避免冗长

注意：用户的说话环境为QQ群聊，请考虑群聊语境下的表达特点。特别注意区分引用内容和用户自己的表达。

该用户的基本信息：
{basic_info}

该用户已有的个性总结（如果有）：
{existing_summary}

过往聊天记录：
{chat_history}

请生成新的用户个性关键词：
"""

    chat_history_for_api = [prompt]
    summary = await cat_cat_response(api_key, chat_history_for_api, "")

    if summary:
        new_content = format_log_file(basic_info, summary, chat_history)
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    return summary