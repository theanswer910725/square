"""界面配色与基础尺寸常量（唯一色板来源）。

色值对齐 Windows 11 light 的 Fluent 色板：浅灰底、白卡片、#E5E5E5 描边，
强调色统一到 Win11 light accent #005FB8。
"""

# ---- Win11 light 基础色 ----
BG = "#f3f3f3"            # 窗口底
CARD = "#ffffff"          # 卡片
FIELD = "#ffffff"         # 输入区（文本框）
SURFACE = "#fafafa"       # 图片/画布底
BORDER = "#e5e5e5"        # 描边
TEXT = "#1a1a1a"          # 主文字
MUTED = "#5d5d5d"         # 次要文字
TEXT_DISABLED = "#a0a0a0" # 禁用文字

# ---- 强调色（只保留这一支蓝色）----
ACCENT = "#005fb8"
ACCENT_HOVER = "#1a6fc4"
ACCENT_SOFT = "#9cc0de"   # 生成中按钮的禁用底
ON_ACCENT = "#ffffff"     # 强调底上的文字

# ---- 次级按钮 / 轨道 / 滚动条 ----
BTN = "#fbfbfb"
BTN_HOVER = "#f0f0f0"
TRACK = "#e5e5e5"
TRACK_HOVER = "#dcdcdc"
# 下拉框三态：整条填充 / 右侧箭头格 / 箭头格左侧分隔线
FIELD_HOVER = "#f7f7f7"
FIELD_OPEN = "#f0f0f0"
ARROW_BG = "#f5f5f5"
ARROW_BG_HOVER = "#ebebeb"
ARROW_BG_OPEN = "#e5e5e5"
DIVIDER = "#e5e5e5"
DIVIDER_HOVER = "#dcdcdc"
DIVIDER_OPEN = "#d2d2d2"
MENU_HOVER = "#f0f0f0"
SCROLL_THUMB = "#cdcdcd"
SCROLL_THUMB_HOVER = "#a6a6a6"

# ---- 文本选中 / 提示 / 截图遮罩 ----
SELECT_BG = "#cce4f7"
SELECT_FG = TEXT
TOOLTIP_BG = "#2b2b2b"
TOOLTIP_FG = "#ffffff"
OVERLAY_BG = "#000000"
OVERLAY_FG = "#ffffff"

# ---- 尺寸与字体 ----
RADIUS = 8
# 界面统一用微软雅黑：Segoe UI 系列不含 CJK 字形，中文只能靠系统 font linking
# 兜底，实际命中的中文字面不可控，中英混排时字形/字重也和雅黑不一致
FONT_STACK = ("Microsoft YaHei UI", "Microsoft YaHei",
              "Segoe UI Variable Text", "Segoe UI")
