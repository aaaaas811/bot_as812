# -*- coding: utf-8 -*-
import os
import shlex
import time
import base64

from ncatbot.core import BaseMessage, GroupMessage, PrivateMessage, Image, MessageChain
from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.utils.logger import get_log

from .utils.text_fit_draw import draw_text_auto
from .utils.config_loader import load_config

bot = CompatibleEnrollment  # 兼容回调函数注册器
_log = get_log("AnansSketchbookChatBox")  # 日志记录器


class AnansSketchbookChatBox(BasePlugin):
    name = "AnansSketchbookChatBox"  # 插件名
    version = "0.0.1"  # 插件版本

    async def handle_help_command(self, event: BaseMessage | GroupMessage | PrivateMessage) -> None:
        """处理帮助命令事件"""
        help_text = """安安的素描本聊天框 插件使用帮助：
命令格式：
/sketchbook <help|要生成的文本> [使用表情]

示例：
/sketchbook 吾辈不想当你的传话筒
/sketchbook 【洗脑】并没有开心 开心

可用表情：
base, 开心, 生气, 无语, 脸红, 病娇,
哭泣, 害怕, 惊讶, 激动, 闭眼, 难受"""
        await event.reply_text(help_text)

    async def user_command_handler(self, event: BaseMessage | GroupMessage | PrivateMessage):
        """处理用户命令事件"""
        # 替换消息中的转义符，如\\n -> \n
        replaced_message = event.raw_message.replace("\\n", "\n")

        # 解析命令
        try:
            command = shlex.split(replaced_message)
        except ValueError:
            await event.reply_text("命令格式错误，请检查引号是否匹配！")
            return

        # 检测是否为用户命令
        if not command or command[0] != '/sketchbook':
            return

        # 检测命令长度
        if len(command) == 1:
            # 显示帮助信息
            await self.handle_help_command(event)
            return

        # 处理 help 命令
        if command[1] == 'help':
            await self.handle_help_command(event)
            return

        # 获取文本内容
        text = command[1]

        # 获取表情参数（默认为 base）
        emotion = command[2] if len(command) > 2 else "base"

        # 映射表情名称到文件名
        emotion_mapping = {
            "base": "base.png",
            "开心": "开心.png",
            "生气": "生气.png",
            "无语": "无语.png",
            "脸红": "脸红.png",
            "病娇": "病娇.png",
            "哭泣": "哭泣.png",
            "害怕": "害怕.png",
            "惊讶": "惊讶.png",
            "激动": "激动.png",
            "闭眼": "闭眼.png",
            "难受": "难受.png",
        }

        # 获取底图路径
        if emotion not in emotion_mapping:
            await event.reply_text(f"未知的表情：{emotion}，使用默认表情 base")
            emotion = "base"

        base_image_path = self.self_space.path.as_posix() + '/utils/' + os.path.join("BaseImages",
                                                                                     emotion_mapping[emotion])

        # 检查文件是否存在
        if not os.path.exists(base_image_path):
            _log.error(f"底图文件不存在: {base_image_path}")
            await event.reply_text(f"底图文件不存在，请检查配置")
            return

        try:
            # 生成图片
            _log.info(f"生成图片: 文本={text}, 表情={emotion}")

            # 获取配置路径
            font_path = self.self_space.path.as_posix() + '/utils/' + self.image_config.font_file
            overlay_path = (
                self.self_space.path.as_posix() + '/utils/' + self.image_config.base_overlay_file
                if self.image_config.use_base_overlay
                else None
            )

            # 生成图片 bytes
            png_bytes = draw_text_auto(
                image_source=base_image_path,
                top_left=self.image_config.text_box_topleft,
                bottom_right=self.image_config.image_box_bottomright,
                text=text,
                color=(0, 0, 0),
                max_font_height=64,
                font_path=font_path if os.path.exists(font_path) else None,
                image_overlay=overlay_path if overlay_path and os.path.exists(overlay_path) else None,
                wrap_algorithm=self.image_config.text_wrap_algorithm,
            )

            # 将图片 bytes 转换为 Image 对象
            image_base64 = base64.b64encode(png_bytes).decode('utf-8')

            # 生成唯一的文件名
            # timestamp = int(time.time() * 1000)  # 使用毫秒时间戳
            # image_filename = "sketchbook_{msg_type}{id_}_{timestamp}.png".format(
            #     msg_type='group' if event.group_id else 'private',
            #     id_=event.group_id if event.group_id else event.user_id, timestamp=timestamp)
            # image_path = os.path.join(self.work_space.path.as_posix(), image_filename)

            # 保存图片到文件
            # with open(image_path, 'wb') as f:
            #     f.write(png_bytes)

            # 发送图片
            # 这里使用 base64 方式发送图片，避免文件路径问题
            # 并且避免了文件清理的问题
            # 最重要的是，路径发送在我这里经常失败，可能是权限问题
            if event.group_id:
                await self.api.post_group_msg(event.group_id, image='base64://' + image_base64)
            else:
                await self.api.post_private_msg(event.user_id, image='base64://' + image_base64)

            _log.info("成功生成并发送图片")
        except Exception as e:
            _log.error(f"生成图片失败: {e}", exc_info=True)
            await event.reply_text(f"生成图片失败: {str(e)}")

    async def on_load(self):
        """插件加载时调用"""
        # 加载配置
        config_path = os.path.join(os.path.dirname(__file__), "utils", "config.yaml")
        self.image_config = load_config(config_path)
        # 确保路径是相对于插件目录的
        self.utils_dir = os.path.join(os.path.dirname(__file__), "utils")

        # 注册用户命令处理函数
        self.register_user_func(
            '用户命令',
            self.user_command_handler,
            prefix='/sketchbook',
            description="根据文本生成图片",
            usage="/sketchbook <help|要生成的文本> [使用表情]",
            examples=[
                "/sketchbook 你好",
                "/sketchbook 你好 开心",
                "/sketchbook help"
            ]
        )
