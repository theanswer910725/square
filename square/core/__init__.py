"""纯逻辑层：不依赖 Tk。

对外入口：
  codec     编码 / 分片协议解析 / 重组 / 文本解码
  tiles     密集拼接图的切块二次识别
  puzzle    多张二维码合成为一张拼图
  clipboard 把 PIL 图片写入 Windows 剪贴板
"""
from .clipboard import copy_image_to_clipboard
from .codec import (MAGIC, assemble_frames, decode_strings, encode,
                    format_indices, parse_frames)
from .puzzle import make_puzzle
from .tiles import decode_tiles

__all__ = [
    "MAGIC",
    "encode",
    "parse_frames",
    "assemble_frames",
    "decode_strings",
    "format_indices",
    "decode_tiles",
    "make_puzzle",
    "copy_image_to_clipboard",
]
