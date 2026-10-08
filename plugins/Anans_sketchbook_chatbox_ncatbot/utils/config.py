from pydantic import BaseModel
from typing import Tuple

# 本文件中包含了各种参数, 可以进行调整
# 其中以"#"开头的注释为说明该参数的使用方法

# 使用字体的文件名, 需要自己导入
# 此值为字符串, 代表相对utils目录的相对路径
FONT_FILE = "font.ttf"

# 文本框左上角坐标 (x, y), 同时适用于图片框
# 此值为一个二元组, 例如 (100, 150), 单位像素, 图片的左上角记为 (0, 0)
TEXT_BOX_TOPLEFT = (119, 450)

# 文本框右下角坐标 (x, y), 同时适用于图片框
# 此值为一个二元组, 例如 (100, 150), 单位像素, 图片的左上角记为 (0, 0)
IMAGE_BOX_BOTTOMRIGHT = (119 + 279, 450 + 175)

# 置顶图层的文件名, 需要自己导入
# 此值为字符串, 代表相对utils目录的相对路径
BASE_OVERLAY_FILE = "BaseImages\\base_overlay.png"

# 是否启用底图的置顶图层, 用于表现遮挡
# 此值为布尔值, True 或 False
USE_BASE_OVERLAY = True

# 文本换行算法，可选值："original"(原始算法), "knuth_plass"(改进的Knuth-Plass算法)
# 此值为字符串
TEXT_WRAP_ALGORITHM = "original"


class Config(BaseModel):
    font_file: str = FONT_FILE
    """字体文件路径"""
    text_box_topleft: Tuple[int, int] = TEXT_BOX_TOPLEFT
    """文本框左上角坐标"""
    image_box_bottomright: Tuple[int, int] = IMAGE_BOX_BOTTOMRIGHT
    """文本框右下角坐标"""
    base_overlay_file: str = BASE_OVERLAY_FILE
    """底图置顶图层文件路径"""
    use_base_overlay: bool = USE_BASE_OVERLAY
    """是否使用底图置顶图层"""
    text_wrap_algorithm: str = TEXT_WRAP_ALGORITHM
    """文本换行算法，可选值："original"(原始算法), "knuth_plass"(改进的Knuth-Plass算法)"""
