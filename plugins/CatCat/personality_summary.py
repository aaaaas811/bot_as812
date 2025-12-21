import json
import os
from .responses.CatCatRes import cat_cat_response

async def summarize_personality(log_file_path, api_key, user_info_str):
    # 读取日志文件
    if not os.path.exists(log_file_path):
        return

    with open(log_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 构建prompt
    prompt = f"""请分析以下用户的聊天日志，提取对话中的有效信息，并结合用户当前的个性总结（如果存在），生成一个新的、准确的用户个性关键词列表。

    分析要求：
    1. 仔细阅读用户的每条消息，提取关键信息、兴趣爱好、说话风格、性格特征等
    2. 如果日志中已有个性总结，请在原有基础上进行更新和完善，而不是完全重写
    3. 重点关注用户的语言习惯、情感表达、话题偏好、互动模式等
    4. 生成的个性关键词应该简洁但全面，能够帮助AI更好地理解和模拟用户
    5. 只生成关键词，用逗号分隔，不要生成句子

    注意：用户的说话环境为QQ群聊，请考虑群聊语境下的表达特点。

    日志内容：
    {content}

    请生成新的用户个性关键词：
    """

    # 调用API
    chat_history = [prompt]
    summary = await cat_cat_response(api_key, chat_history, "")

    if summary:
        # 覆写日志文件
        new_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n{summary}\n\n过往聊天记录：\n"
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_content)