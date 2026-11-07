"""QR Tool：二维码生成与分片还原。

分层约定：
  core/  纯逻辑（编码、解码、分片协议、密集图切块识别、拼图合成、剪贴板）
  gui/   Tk / CustomTkinter 界面（主窗口、预览、大图弹窗、区域截图遮罩）

core 不依赖 Tk，也不反向 import gui。
"""
