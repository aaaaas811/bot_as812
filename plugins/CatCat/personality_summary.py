import json
import os
from .responses.CatCatRes import cat_cat_response

async def summarize_personality(log_file_path, api_key, user_info_str):
    # 读取日志文件
    if not os.path.exists(log_file_path):
        return

    with open(log_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 读取cat_prompt.txt
    prompt_file = "plugins/CatCat/config/cat_prompt.txt"
    cat_prompt = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            cat_prompt = f.read()

    # 构建prompt
    prompt = f"根据以下日志文件内容，总结这个用户的个性特征。日志内容：\n{content}\n\n输出用户的个性总结（而非812的）："

    # 调用API
    chat_history = [prompt]
    summary = await cat_cat_response(api_key, chat_history, "")

    if summary:
        # 覆写日志文件
        new_content = f"该用户的基本信息：{user_info_str}\n\n该用户的个性总结：\n{summary}\n\n过往聊天记录：\n"
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(new_content)