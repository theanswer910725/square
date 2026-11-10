"""主窗口：生成器 / 解码器两个页面、预览、加载遮罩与各入口动作。"""
import ctypes
import os
import queue
import tempfile
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

from ..core.codec import (assemble_frames, decode_strings,
                          effective_part_limit, encode, fits_single,
                          parse_frames, single_capacity)
from ..core.puzzle import make_puzzle
from ..core.tiles import as_text, decode_tiles
from .capture import capture_region
from .dpi import apply_dpi_awareness, patch_ctk_scaling
from .preview import open_preview_popup
from .theme import (ACCENT, ACCENT_HOVER, ACCENT_SOFT, BG, BORDER, BTN,
                    BTN_HOVER, CARD, FIELD, MUTED, ON_ACCENT, RADIUS,
                    SCROLL_THUMB, SCROLL_THUMB_HOVER, SURFACE,
                    TEXT, TEXT_DISABLED, TRACK, TRACK_HOVER)
from .widgets import (SelectBox, Tooltip, fix_textbox_selection,
                      make_scan_icon, pick_font_family, set_window_icon)

# ---- 下拉预设（文案即键，变量初值必须取自这里，保证显示值与实际生效值一致）----
# 纠错率：整串文案 → segno 参数。显示值与实际值只在这里对应一次，取值一律查表，
# 不截取/解析标签文字，界面文案怎么改都不会走错档
ERROR_PARAM = {
    "最低（容量最大，约 7% 可恢复）": "L",
    "中等（约 15% 可恢复）": "M",
    "较高（约 25% 可恢复）": "Q",
    "最高（容量最小，约 30% 可恢复）": "H",
}
ERROR_OPTIONS = list(ERROR_PARAM)
QUALITY_OPTIONS = [
    "紧凑（分片少，码密）",
    "平衡",
    "清晰（分片多，码易识别）",
    "最清晰（分片最多，单码最疏）",
]
STRATEGY_OPTIONS = ["自动（推荐）", "强制单码", "强制分片", "压缩+分片"]

# 清晰度 → 每片 base64 载荷上限（字符）。上限越大分片越少、单码模块越密。
# 实际生效值还要与「当前纠错率的单码容量 - 20 字符帧头」取较小者，
# 避免上限超过单码容量时抛 DataOverflowError
QUALITY_PART_LIMIT = {
    "紧凑（分片少，码密）": 1700,
    "平衡": 1300,
    "清晰（分片多，码易识别）": 1000,
    "最清晰（分片最多，单码最疏）": 750,
}

# 纠错率默认「中等」（M）：通用推荐档，截图/翻拍的摩尔纹与缩放模糊靠 15% 冗余兜底；
# 容量损失由分片吸收（分片上限不变，只是每片版本略高）
DEFAULT_ERROR = "中等（约 15% 可恢复）"
# 清晰度：1000 字符/片，与旧版实际生效值一致；M 纠错下满片约 version 26
DEFAULT_QUALITY = "清晰（分片多，码易识别）"
DEFAULT_STRATEGY = "自动（推荐）"

# 窗口逻辑尺寸（DIP，1 逻辑像素 = 1/96 英寸）。CustomTkinter 会按 window scaling
# 换算成物理像素，这里不要再乘 DPI。当前值在 1536×864@125% 下约合
# 客户区 620×420 逻辑像素（外框约 635×462），是原来 775×525 的 0.8 倍
DEFAULT_SIZE = (620, 420)
# 最小尺寸同比缩放（原 700×475 × 0.8）。minsize 不能高于 geometry，
# 否则 Tk 会把窗口顶回 minsize，实际尺寸就不是 DEFAULT_SIZE 了
MIN_SIZE = (560, 380)


def format_bytes(n):
    """字节数 → 人类可读：不足 1KB 用「字节」，否则按 1024 进位 KB / MB"""
    if n < 1024:
        return f"{n} 字节"
    v, unit = n / 1024, "KB"
    if v >= 1024:
        v, unit = v / 1024, "MB"
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return f"{s} {unit}"


def restore_status(text):
    """还原成功状态行：字符数 + 人类可读的字节数"""
    return (f"✓ 还原成功 · {len(text)} 字符 · "
            f"{format_bytes(len(text.encode('utf-8')))}")


def progress_text(total, have, missing, avail, measure):
    """分片进度文本：片号空格分隔，放不下时在括号内以「 …」收尾

    括号外的「共 N 片，已收集 M 片，缺失 K 片」始终完整保留，K 为真实缺失数。
    """
    miss_nums = sorted(n + 1 for n in set(missing))
    miss_set = set(miss_nums)
    coll_nums = [n for n in range(1, total + 1) if n not in miss_set]
    k = len(miss_nums)

    def build(cs, ms, c_cut, m_cut):
        c = " ".join(str(n) for n in cs) + (" …" if c_cut else "")
        m = " ".join(str(n) for n in ms) + (" …" if m_cut else "")
        return f"共{total}片，已收集{have}片（{c}），缺失{k}片（{m}）"

    cs, ms = list(coll_nums), list(miss_nums)
    c_cut = m_cut = False
    while measure(build(cs, ms, c_cut, m_cut)) > avail and (cs or ms):
        # 优先截较长的列表；等长时先截缺失列表，保证「已收集」信息在前
        if len(ms) >= len(cs):
            ms.pop()
            m_cut = True
        else:
            cs.pop()
            c_cut = True
    return build(cs, ms, c_cut, m_cut)


class SquareApp:
    def __init__(self, root):
        self.root = root
        root.title("方寸 · Square")

        # CustomTkinter 的 geometry()/minsize() 内部会按 window scaling 把逻辑像素
        # 换算成物理像素（本机 125%），所以这里传逻辑像素即可。
        # 之前又自己乘了一次 DPI，导致缩放叠加两次、窗口比预期大 25%。
        scale = root.winfo_fpixels("1i") / 96.0
        screen_w = int(root.winfo_screenwidth() / scale)
        screen_h = int(root.winfo_screenheight() / scale)
        w = min(DEFAULT_SIZE[0], screen_w - 40)
        h = min(DEFAULT_SIZE[1], screen_h - 80)
        root.geometry(f"{w}x{h}")
        root.minsize(*MIN_SIZE)
        root.configure(fg_color=BG)

        # 状态
        self.gen_result = None
        self.gen_preview_photos = []
        self._preview_puzzle = None
        self._preview_photo = None
        self._last_result = None
        self._scan_photo_ref = None
        self._busy = False
        self._gen_queue = queue.Queue()
        # 参数提示的合并调度标记：三个下拉的 trace 会在变量写入时同步触发，
        # 连着改会来好几次；只置脏一次，真正的刷新留到空闲期（见 _update_param_hint）
        self._hint_pending = False
        # 折行宽度的重算依据：上次用过的根窗口物理宽度（变化不足 8px 不重算）
        self._hint_root_w = 0
        # 分片收集池：index -> frame，来自多次截图/多张图片，按片号去重
        self.shard_pool = {}
        self.shard_sig = None

        base = pick_font_family(root)
        # 字号用整数像素（CTk 的 size 即像素），避免非整数缩放导致的字形重采样
        self.f_ui = ctk.CTkFont(family=base, size=14)
        self.f_sm = ctk.CTkFont(family=base, size=13)
        self.f_xs = ctk.CTkFont(family=base, size=12)
        self.f_bold = ctk.CTkFont(family=base, size=14, weight="bold")

        self._build_ui()
        # 只在根窗口宽度真正变化时重算折行宽度；_build_ui 可能被重建，
        # 故绑定放在这里，保证只挂一次
        self.root.bind("<Configure>", self._on_root_resize, add="+")

    # ========== 界面骨架 ==========
    def _build_ui(self):
        for child in self.root.winfo_children():
            child.destroy()

        # 顶部分段切换：只占中间一段固定宽度并居中，不横贯整宽。
        # 原来 fill="x" 把两个选项拉到窗口两端，视觉上像一条宽横条。
        # CTkSegmentedButton 默认 dynamic_resizing=True 会用两个按钮的
        # 请求宽度（约 122 逻辑像素）反算自身宽度、无视 width 参数，
        # 必须关掉它，width 才真正生效
        self.seg = ctk.CTkSegmentedButton(
            self.root, values=["生成器", "解码器"],
            command=self._on_seg_change,
            font=self.f_ui, width=240, height=26, corner_radius=RADIUS,
            dynamic_resizing=False,
            fg_color=TRACK, selected_color=CARD, selected_hover_color=CARD,
            unselected_color=TRACK, unselected_hover_color=TRACK_HOVER,
            text_color=MUTED, text_color_disabled=TEXT_DISABLED)
        # 顶部只留最小呼吸位（4），下方内容区同样 4：原来 8/8 会在标题栏和
        # 分段按钮之间留出一条约 10px 的全宽空白带（用户圈出的那块）。
        # 再小控制就会贴住标题栏，故以此为下限
        self.seg.pack(pady=(4, 0))
        self.seg.set("生成器")

        # 页面容器
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_generator_page()
        self._build_decoder_page()
        self._show_page(0)

    def _on_seg_change(self, value):
        self._show_page(0 if value == "生成器" else 1)

    def _show_page(self, idx):
        self.gen_page.grid_remove()
        self.dec_page.grid_remove()
        (self.gen_page if idx == 0 else self.dec_page).grid(
            row=0, column=0, sticky="nsew")

    # ========== 生成器页 ==========
    def _build_generator_page(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        self.gen_page = page
        # 左右两列等宽：uniform 让两列在任何窗口宽度下都严格等分，
        # 不依赖内容请求宽度，放大/缩小都同步。minsize 物理像素（原 290×0.8）
        page.grid_columnconfigure(0, weight=1, minsize=232, uniform="cols")
        page.grid_columnconfigure(1, weight=1, minsize=232, uniform="cols")
        page.grid_rowconfigure(0, weight=1)

        # ---- 左：预览 + 参数 + 操作 ----
        left = ctk.CTkFrame(page, fg_color=CARD, corner_radius=RADIUS,
                            border_width=1, border_color=BORDER)
        # 两列之间的 8px 间距左右各分 4px，保证两张卡片本体宽度严格相等
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        ctk.CTkLabel(head, text="预览", font=self.f_bold,
                     text_color=TEXT).pack(side="left")
        # 图标按 4 倍绘制，CTkImage 缩小到 16px 交给 CTk 按 DPI 处理
        icon = make_scan_icon(16, scale=4)
        self.icon_scan = ctk.CTkImage(light_image=icon, dark_image=icon,
                                      size=(16, 16))
        btn_shot = ctk.CTkButton(head, text="", image=self.icon_scan,
                                 command=self._on_capture_region,
                                 width=28, height=20, corner_radius=RADIUS,
                                 fg_color=BTN, hover_color=BTN_HOVER,
                                 border_width=1, border_color=BORDER)
        btn_shot.pack(side="right")
        Tooltip(btn_shot, "截图：框选屏幕区域后送至解码器")

        preview_wrap = ctk.CTkFrame(left, fg_color="transparent")
        preview_wrap.grid(row=1, column=0, sticky="nsew", padx=12)
        preview_wrap.grid_columnconfigure(0, weight=1)
        preview_wrap.grid_rowconfigure(0, weight=1)

        # 画布请求尺寸（物理像素）同比 0.8，避免它把列请求宽度顶大
        self.preview_canvas = tk.Canvas(preview_wrap, bg=SURFACE, height=96,
                                        width=240, bd=0,
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self._open_preview_popup)
        self.preview_canvas.bind("<Configure>", self._refit_preview)

        # 图片下方的提醒文字（有二维码时才显示）
        self.preview_hint = ctk.CTkLabel(preview_wrap, text="点击可查看大图",
                                         font=self.f_xs, text_color=MUTED)
        self.preview_hint.grid(row=1, column=0, pady=(4, 0))
        self.preview_hint.grid_remove()

        # 生成中的遮罩（盖在预览上，含循环进度条）
        self.loading = ctk.CTkFrame(preview_wrap, fg_color=SURFACE, corner_radius=0,
                                    border_width=1, border_color=BORDER)
        self.loading.grid_columnconfigure(0, weight=1)
        self.loading.grid_rowconfigure(0, weight=1)
        box = ctk.CTkFrame(self.loading, fg_color="transparent")
        box.grid(row=0, column=0)
        ctk.CTkLabel(box, text="正在生成…", font=self.f_bold,
                     text_color=MUTED).pack(pady=(0, 8))
        self.loading_bar = ctk.CTkProgressBar(
            box, width=136, height=6, corner_radius=3, mode="indeterminate",
            indeterminate_speed=1.6, fg_color=TRACK, progress_color=ACCENT)
        self.loading_bar.pack()
        self.loading_bar.set(0)

        # ---- 参数 ----
        params = ctk.CTkFrame(left, fg_color="transparent")
        params.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        params.grid_columnconfigure(1, weight=1)

        def add_menu(row, variable, values):
            """只读下拉：整条框和展开菜单都由 SelectBox 自绘。

            CTkOptionMenu / CTkComboBox 的箭头区是独立绘制分区，右段外圈用
            的是 button_color 而不是 border_color，外框包一层也会被它压断。
            """
            SelectBox(params, variable=variable, values=values,
                      font=self.f_sm, height=30, width=168,
                      surface=CARD).grid(
                row=row, column=1, sticky="ew", pady=2)

        ctk.CTkLabel(params, text="纠错率", font=self.f_sm,
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_error_label = tk.StringVar(value=DEFAULT_ERROR)
        add_menu(0, self.var_error_label, ERROR_OPTIONS)

        ctk.CTkLabel(params, text="清晰度", font=self.f_sm,
                     text_color=MUTED).grid(row=1, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_quality = tk.StringVar(value=DEFAULT_QUALITY)
        add_menu(1, self.var_quality, QUALITY_OPTIONS)

        ctk.CTkLabel(params, text="编码策略", font=self.f_sm,
                     text_color=MUTED).grid(row=2, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_strategy = tk.StringVar(value=DEFAULT_STRATEGY)
        add_menu(2, self.var_strategy, STRATEGY_OPTIONS)

        # 参数区常驻提示：档位被单码容量压低、压缩码只有本软件能还原。
        # 用标签而不是弹窗，改下拉时即时更新，不打断操作。
        # 折行宽度只按根窗口宽度推算（见 _hint_wrap），不再从标签自身宽度倒推：
        # Win7 上「读标签宽度→写 wraplength→宽度又变」会形成极限环，
        # 188/266 之间每秒震荡 200 次，把主循环占满
        self.param_hint = ctk.CTkLabel(
            params, text="", font=self.f_xs, text_color=MUTED,
            anchor="w", justify="left", wraplength=self._hint_wrap())
        self.param_hint.grid(row=3, column=0, columnspan=2, sticky="ew",
                             pady=(4, 0))
        self.param_hint.grid_remove()
        for var in (self.var_error_label, self.var_quality,
                    self.var_strategy):
            var.trace_add("write", lambda *a: self._update_param_hint())
        self._update_param_hint()

        # ---- 主操作 ----
        # CTkButton 默认 width=140 逻辑像素，两颗并排会把整列请求宽度顶到 387，
        # 超过 620 宽窗口实际分到的 368，故按 0.8 收到 112（布局时按权重拉伸）
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 12))
        btns.grid_columnconfigure(0, weight=3)
        btns.grid_columnconfigure(1, weight=2)

        self.btn_generate = ctk.CTkButton(
            btns, text="生成二维码", command=self._on_generate,
            font=self.f_bold, height=32, width=112, corner_radius=RADIUS,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=ON_ACCENT, text_color_disabled=ON_ACCENT)
        self.btn_generate.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(btns, text="保存二维码", command=self._on_save_image,
                      font=self.f_sm, height=32, width=112, corner_radius=RADIUS,
                      fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=TEXT, border_width=1,
                      border_color=BORDER).grid(
            row=0, column=1, sticky="ew")

        # ---- 右：文本输入（整列占满高度）----
        right = ctk.CTkFrame(page, fg_color=CARD, corner_radius=RADIUS,
                             border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        head2 = ctk.CTkFrame(right, fg_color="transparent")
        head2.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkLabel(head2, text="文本输入", font=self.f_bold,
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(head2, text="导入", command=self._import_file,
                      font=self.f_sm, width=52, height=24, corner_radius=RADIUS,
                      fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(side="right")

        self.text_input = ctk.CTkTextbox(
            right, font=self.f_ui, wrap="word",
            fg_color=FIELD, border_width=1, border_color=BORDER,
            corner_radius=RADIUS, text_color=TEXT,
            scrollbar_button_color=SCROLL_THUMB,
            scrollbar_button_hover_color=SCROLL_THUMB_HOVER)
        self.text_input.grid(row=1, column=0, sticky="nsew",
                             padx=10, pady=(0, 10))
        fix_textbox_selection(self.text_input)

    # ========== 解码器页 ==========
    def _build_decoder_page(self):
        page = ctk.CTkFrame(self.content, fg_color=CARD, corner_radius=RADIUS,
                            border_width=1, border_color=BORDER)
        page.grid(row=0, column=0, sticky="nsew")
        self.dec_page = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=3)
        page.grid_rowconfigure(3, weight=2)

        # 状态行：左侧检测状态，右侧依次是「清空收集」（仅未收齐时出现）、
        # 「截图识别」「选择图片」「剪贴板」，全部垂直居中；除截图识别用主按钮色，
        # 其余小按钮与「复制」同款
        srow = ctk.CTkFrame(page, fg_color="transparent")
        srow.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        srow.grid_columnconfigure(0, weight=1)
        self.scan_status = tk.StringVar(value="等待输入图片")
        self.scan_status_label = ctk.CTkLabel(
            srow, textvariable=self.scan_status, font=self.f_sm,
            text_color=MUTED, anchor="w")
        self.scan_status_label.grid(row=0, column=0, sticky="ew")
        # 只在「分片没收齐」时才出现，平时不占地方
        self.btn_clear_pool = ctk.CTkButton(
            srow, text="清空收集", command=self._clear_pool_ui,
            font=self.f_xs, width=64, height=24, corner_radius=RADIUS,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            border_width=1, border_color=BORDER)
        self.btn_clear_pool.grid(row=0, column=1, padx=(6, 4))
        self.btn_clear_pool.grid_remove()
        # 三颗按钮取较宽者的宽度，右缘贴齐状态行右侧；
        # 截图识别复用主界面预览区与大图弹窗的同一条截图入口
        entries = [("截图识别", self._on_capture_region, True),
                   ("选择图片", self._on_scan_file, False),
                   ("剪贴板", self._on_scan_clipboard, False)]
        btn_w = max(self.f_sm.measure(t) for t, _, _ in entries) + 26
        self._status_btns = [self.btn_clear_pool]
        for col, (text, cmd, primary) in enumerate(entries, start=2):
            btn = ctk.CTkButton(
                srow, text=text, command=cmd, width=btn_w, height=24,
                corner_radius=RADIUS, font=self.f_sm,
                fg_color=ACCENT if primary else BTN,
                hover_color=ACCENT_HOVER if primary else BTN_HOVER,
                text_color=ON_ACCENT if primary else TEXT,
                border_width=0 if primary else 1,
                border_color=BORDER)
            btn.grid(row=0, column=col, padx=(0, 4) if col <= 3 else 0)
            self._status_btns.append(btn)

        self.scan_canvas = tk.Canvas(page, bg=SURFACE, height=96, bd=0,
                                     highlightthickness=1,
                                     highlightbackground=BORDER)
        self.scan_canvas.grid(row=1, column=0, sticky="nsew", padx=12)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(head, text="还原文本", font=self.f_bold,
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(head, text="复制", width=52, height=24, font=self.f_sm,
                      corner_radius=RADIUS, fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=TEXT, border_width=1, border_color=BORDER,
                      command=lambda: self.root.clipboard_append(
                          self.scan_text.get("1.0", "end"))).pack(side="right")

        self.scan_text = ctk.CTkTextbox(
            page, height=80, font=self.f_ui, wrap="word",
            fg_color=FIELD, border_width=1, border_color=BORDER,
            corner_radius=RADIUS, text_color=TEXT,
            scrollbar_button_color=SCROLL_THUMB,
            scrollbar_button_hover_color=SCROLL_THUMB_HOVER)
        self.scan_text.grid(row=3, column=0, sticky="nsew",
                            padx=12, pady=(0, 12))
        fix_textbox_selection(self.scan_text)

    # ========== 生成器动作 ==========
    def _import_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            with open(path, "r", encoding="utf-8") as f:
                self.text_input.delete("1.0", "end")
                self.text_input.insert("1.0", f.read())

    # ---------- 提示区折行宽度 ----------
    def _hint_wrap(self):
        """提示标签的折行宽度（逻辑像素）

        只由根窗口宽度推算：根窗口有显式 geometry，不会因为子控件的请求
        宽度而变宽，所以这里与标签自身的分配宽度不构成反馈——原来按
        ``event.width - 4`` 写回，Win7 上收敛不了，形成 188↔266 的极限环。

        620 逻辑宽时算得 268，与 Win11 实测收敛值 338÷1.251 一致。
        """
        try:
            if not self.root.winfo_ismapped():
                # 还没映射时 winfo_width() 给的是个偏小的中间值，
                # 按默认宽度估，避免映射后再纠正一次
                return 268
            scale = self.root.winfo_fpixels("1i") / 96.0
            root_w = self.root.winfo_width() / scale
        except tk.TclError:
            return 268
        card_w = (root_w - 32) / 2        # content padx 12×2 + 两列间距 8
        # 用 round：620 逻辑宽下算得 267.75，int 会截成 267，
        # 与构建时按 DEFAULT_SIZE 估的 268 差 1px，白白多写一次
        return max(160, int(round(card_w - 26)))  # 卡片 padx 12×2 + 边框 2

    def _on_root_resize(self, event):
        """根窗口宽度变了才重算折行宽度

        子控件的 <Configure> 会经 bindtags 冒到根窗口上，必须用
        ``event.widget is self.root`` 过滤，否则又变成「任何重排都写一次」。
        """
        if event.widget is not self.root:
            return
        if abs(event.width - self._hint_root_w) < 8:
            return
        self._hint_root_w = event.width
        try:
            if int(self.param_hint.cget("wraplength")) != self._hint_wrap():
                self.param_hint.configure(wraplength=self._hint_wrap())
        except (tk.TclError, ValueError):
            pass

    def _update_param_hint(self):
        """参数区提示：档位被容量压低、压缩码的兼容性说明（改下拉即时刷新）

        trace 回调在变量写入时同步执行，连着改三个下拉会触发多次；
        这里只置脏标记，把 N 次刷新合并成空闲期的一次。
        """
        if self._hint_pending:
            return
        self._hint_pending = True
        self.root.after_idle(self._apply_param_hint)

    def _apply_param_hint(self):
        """空闲期真正刷新提示文案与可见性

        窗口已销毁（退出过程中的残留调度）时 TclError 直接吞掉；
        其它异常不再拦，交给 Tk 的 report_callback_exception 落盘。
        """
        self._hint_pending = False
        try:
            error_label = self.var_error_label.get()
            error = ERROR_PARAM[error_label]
            tier = QUALITY_PART_LIMIT[self.var_quality.get()]
            limit = effective_part_limit(tier, error)
            lines = []
            if limit < tier:
                lines.append(
                    f"当前纠错率「{error_label}」下单码容量有限，"
                    f"每片上限已由 {tier} 字符降为 {limit} 字符。")
            if self.var_strategy.get() == STRATEGY_OPTIONS[3]:
                lines.append(
                    "压缩码仅可本软件还原，通用扫码工具读取到的内容为编码字符串非原始文本。")
            text = "\n".join(lines)
            if text:
                self.param_hint.configure(text=text)
                self.param_hint.grid()
            else:
                self.param_hint.grid_remove()
        except tk.TclError:
            pass

    def _on_generate(self):
        if self._busy:
            return

        text = self.text_input.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("无法生成", "请输入待编码的文本。",
                                   parent=self.root)
            return

        orig_len = len(text.encode("utf-8"))
        strategy = {"自动（推荐）": "auto", "强制单码": "single",
                    "强制分片": "split", "压缩+分片": "compress"}.get(
            self.var_strategy.get(), "auto")
        error = ERROR_PARAM[self.var_error_label.get()]

        # 强制单码：按纠错率下的真实单码容量判断，而不是拍一个固定字节阈值
        if strategy == "single" and not fits_single(text, error):
            cap = single_capacity(error)
            over = max(0, orig_len - cap)
            messagebox.showerror(
                "内容超出单码容量",
                f"当前纠错率「{self.var_error_label.get()}」下，"
                f"单码容量为 {cap} 字节；当前内容为 {orig_len} 字节，"
                f"超出 {over} 字节。\n\n"
                "可降低纠错率、缩短内容，或改用「自动」「强制分片」策略。",
                parent=self.root)
            return

        # 每片上限 = min(清晰度档位上限, 当前纠错率下单码容量 - 20 字符帧头)
        max_b64_len = effective_part_limit(
            QUALITY_PART_LIMIT[self.var_quality.get()], error)

        # 编码放到后台线程，主线程保持响应（进度条才能动）
        self._set_busy(True)
        threading.Thread(
            target=self._generate_worker,
            args=(text, strategy, error, max_b64_len),
            daemon=True).start()
        self.root.after(50, self._poll_generate)

    def _generate_worker(self, text, strategy, error, max_b64_len):
        """后台线程：编码 + 拼图都做完，只回传结果和 PIL 图（不碰任何 Tk 控件）"""
        try:
            result = encode(
                text, error=error, max_b64_len=max_b64_len,
                compressed=strategy == "compress",
                prefer_single=strategy != "split",
                single_only=strategy == "single")
            # 拼图在子线程构造没问题；ImageTk.PhotoImage 留给主线程
            result["preview_image"] = make_puzzle(
                result["qrs"], cols=min(4, len(result["qrs"])), scale=8)
        except Exception as e:
            self._gen_queue.put(("err", str(e)))
            return
        self._gen_queue.put(("ok", result))

    def _poll_generate(self):
        """主线程轮询队列，保证所有 UI 更新都在主线程"""
        try:
            status, payload = self._gen_queue.get_nowait()
        except queue.Empty:
            if self._busy:
                self.root.after(60, self._poll_generate)
            return
        if not self._busy:
            return
        try:
            if status == "ok":
                self._generate_done(payload)
            else:
                self._generate_failed(payload)
        except Exception as e:
            # 收尾动作本身出错：必须先退出 busy 再报错，否则遮罩常驻、
            # 按钮永久禁用、轮询也不再续期，界面就彻底停在「生成中」
            try:
                self._set_busy(False)
            finally:
                messagebox.showerror("生成结果处理失败", str(e),
                                     parent=self.root)

    def _generate_done(self, result):
        self.gen_result = result
        try:
            self._render_preview(result)
        except Exception as e:
            messagebox.showerror("预览渲染失败", str(e), parent=self.root)
        finally:
            # 渲染失败也必须退出 busy，理由同 _poll_generate
            self._set_busy(False)
            # 换了新文本：清掉上一组收集的分片
            self._reset_pool()

    def _generate_failed(self, msg):
        self._set_busy(False)
        messagebox.showerror("二维码生成失败", msg, parent=self.root)

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self.loading.place(x=0, y=0, relwidth=1, relheight=1)
            self.loading.lift()
            self.loading_bar.start()
            self.btn_generate.configure(state="disabled", text="生成中……",
                                        fg_color=ACCENT_SOFT,
                                        hover_color=ACCENT_SOFT)
            # 编码在后台线程，可能几十毫秒就回来；主线程紧接着要重排预览（卡住），
            # 不在这里强制刷一次，遮罩根本来不及上屏就被撤掉了
            self.root.update_idletasks()
        else:
            self.loading_bar.stop()
            self.loading.place_forget()
            self.btn_generate.configure(state="normal", text="生成二维码",
                                        fg_color=ACCENT,
                                        hover_color=ACCENT_HOVER)

    def _render_preview(self, result):
        """渲染主预览（自动 fit 窗口，点击弹窗看大图）"""
        self._last_result = result
        self._refit_preview()

    def _refit_preview(self, event=None):
        """主预览：fit 并居中"""
        if not getattr(self, "_last_result", None):
            self._draw_preview_placeholder()
            return
        result = self._last_result

        puzzle = result.get("preview_image")
        if puzzle is None:
            return
        self._preview_puzzle = puzzle

        self.preview_canvas.delete("all")
        self.gen_preview_photos.clear()

        self.root.update_idletasks()
        cw = max(100, self.preview_canvas.winfo_width())
        ch = max(100, self.preview_canvas.winfo_height())
        ratio = min((cw - 16) / puzzle.width, (ch - 16) / puzzle.height, 1.0)
        sw = max(1, int(puzzle.width * ratio))
        sh = max(1, int(puzzle.height * ratio))
        scaled = puzzle.resize((sw, sh), Image.LANCZOS)

        self._preview_photo = ImageTk.PhotoImage(scaled)
        self.gen_preview_photos.append(self._preview_photo)
        # 居中绘制
        x = (cw - sw) // 2
        y = (ch - sh) // 2
        self.preview_canvas.create_image(x, y, anchor="nw", image=self._preview_photo)
        self.preview_hint.grid()

    def _draw_preview_placeholder(self):
        c = self.preview_canvas
        c.delete("all")
        self.preview_hint.grid_remove()
        cw = max(1, c.winfo_width())
        ch = max(1, c.winfo_height())
        c.create_text(cw // 2, ch // 2, text="输入文本后点击「生成二维码」",
                      fill=MUTED, font=self.f_sm)

    def _open_preview_popup(self, event=None):
        """弹出大图窗口，带缩放条"""
        if self._preview_puzzle is None:
            return
        open_preview_popup(self)

    # ---------- 区域截图（真实屏幕像素） ----------
    def _on_capture_region(self, owner=None):
        """区域截图：全屏遮罩拖拽框选 → 进剪贴板 → 解码器还原"""
        capture_region(self, owner)

    def _on_save_image(self, parent=None):
        # 大图弹窗里点「保存原图」时把弹窗传进来，对话框才会跟着弹窗置前
        parent = parent or self.root
        if not self.gen_result:
            messagebox.showwarning("无法保存", "当前尚未生成二维码，请先生成。",
                                   parent=parent)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
            initialfile="qrcode.png", parent=parent)
        if path:
            cols = min(4, len(self.gen_result["qrs"]))
            make_puzzle(self.gen_result["qrs"], cols=cols, scale=15).save(path)

    # ========== 解码器动作 ==========
    def _reset_pool(self):
        """清空分片收集池（凑齐/换文本/手动清空时）"""
        self.shard_pool.clear()
        self.shard_sig = None
        if hasattr(self, "btn_clear_pool"):
            self.btn_clear_pool.grid_remove()

    def _clear_pool_ui(self):
        self._reset_pool()
        self.scan_text.delete("1.0", "end")
        self.scan_status.set("已清空收集分片，可重新选择图片")

    @staticmethod
    def _grid_pad(w):
        """控件在 grid 里占用的左右外边距总和（padx 可能是元组或字符串）"""
        pad = w.grid_info().get("padx", 0)
        if isinstance(pad, (tuple, list)):
            return sum(int(p) for p in pad)
        return sum(int(p) for p in str(pad).split())

    def _status_text_width(self):
        """状态行左侧实际可用像素：整行宽减去右侧按钮及间距"""
        used = 0
        for w in self._status_btns:
            if w.winfo_ismapped():
                used += w.winfo_width() + self._grid_pad(w)
        return max(140, self.scan_status_label.master.winfo_width()
                   - used - 6)

    def _textbox_text_width(self):
        """还原文本框内真正可排文字的像素宽度（扣除边框与内边距）"""
        inner = getattr(self.scan_text, "_textbox", None)
        if inner is not None:
            w = inner.winfo_width()
        else:
            w = self.scan_text.winfo_width() - 24
        return max(200, w - 2)

    def _show_partial(self, have, total, missing, prefix=""):
        self.btn_clear_pool.grid()
        self.root.update_idletasks()
        status_line = progress_text(total, have, missing,
                                    self._status_text_width(), self.f_sm.measure)
        text_line = progress_text(total, have, missing,
                                  self._textbox_text_width(), self.f_ui.measure)
        if prefix:
            self.scan_text.insert("1.0", prefix + "\n\n")
        self.scan_text.insert("end",
            text_line + "\n\n"
            f"可继续补充：再框选或选择一张包含缺失分片的图片，"
            f"已收集分片将按片号自动合并，收齐后自动还原。\n\n"
            f"更快的无损方式：在生成器点击「保存二维码」获取原图，"
            f"再通过「选择图片」按原始分辨率识别。")
        self.scan_status.set(status_line)

    def _scan_image(self, pil_img):
        """对 PIL Image 执行多码检测 + 重组；分片按片号累计到收集池

        返回 "ok"（收齐/单码文本）、"partial"（分片未收齐）、
        "none"（没识别到）或 "error"（解码器异常）。
        """
        from pyzbar.pyzbar import decode as pz_decode

        self.scan_status.set("正在识别图片……")
        self.root.update()

        try:
            results = pz_decode(pil_img)
        except Exception as e:
            self.scan_status.set(f"识别过程出错：{e}")
            return "error"

        n = len(results)
        if n:       # 0 个不报数，最终统一落到「未识别到二维码」
            self.scan_status.set(f"已识别到 {n} 个二维码")

        # 渲染图片预览（按画布尺寸缩放并居中）
        display = pil_img.copy()
        self.root.update_idletasks()
        cw = max(100, self.scan_canvas.winfo_width())
        ch = max(100, self.scan_canvas.winfo_height())
        ratio = min((cw - 24) / display.width, (ch - 24) / display.height, 1.0)
        nw, nh = max(1, int(display.width * ratio)), max(1, int(display.height * ratio))
        display = display.resize((nw, nh), Image.LANCZOS)
        self._scan_photo_ref = ImageTk.PhotoImage(display)
        self.scan_canvas.delete("all")
        self.scan_canvas.create_image((cw - nw) // 2, (ch - nh) // 2,
                                      anchor="nw", image=self._scan_photo_ref)

        raw_strings = [as_text(r.data) for r in results]

        # 密集拼接时整图检测会互相干扰：切块 + 补静默区 + 多尺度再试一次
        frames = parse_frames(raw_strings)
        if n == 0 or (frames and len({f["index"] for f in frames}) <
                      frames[0]["total"]):
            self.scan_status.set("正在细分识别……")
            self.root.update()
            extra = [s for s in decode_tiles(pil_img) if s not in raw_strings]
            if extra:
                raw_strings.extend(extra)
                n = len(raw_strings)
                frames = parse_frames(raw_strings)

        if frames:
            # 批次指纹带上版本与整条内容 CRC：两条字节数恰好相同的不同消息
            # 也会被判为换了数据，旧池作废，不会互相覆盖出错误拼接
            sig = (frames[0].get("version"), frames[0]["total"],
                   frames[0]["orig_len"], frames[0].get("crc"),
                   frames[0]["flags"])
            if self.shard_sig is not None and self.shard_sig != sig:
                self.shard_pool.clear()     # 换了一组数据，旧池作废
            self.shard_sig = sig
            for f in frames:
                # 同一片被多次识别时，取帧体更完整的那份（解码成功才有 b64）
                old = self.shard_pool.get(f["index"])
                if old is None or len(f["b64"]) > len(old["b64"]):
                    self.shard_pool[f["index"]] = f
            result = assemble_frames(list(self.shard_pool.values()))
        else:
            result = decode_strings(raw_strings)

        self.scan_text.delete("1.0", "end")
        status = result["status"]

        if status == "ok":
            text = result["text"]
            self.scan_text.insert("1.0", text)
            self.scan_status.set(restore_status(text))
            self._reset_pool()
            return "ok"

        if status == "partial":
            reason = result.get("reason", "")
            if reason and not result.get("missing"):
                # 片数齐了但内容对不上（CRC/解压/编码失败）：明确指出原因，
                # 不能显示成「已收集 N/N、缺 0 片」那种看起来成功的进度
                self.scan_status.set(reason)
                self.scan_text.delete("1.0", "end")
                self.scan_text.insert(
                    "1.0",
                    f"{reason}。\n\n"
                    f"通常是不同文本的二维码被混在一起识别了。"
                    f"请点击「清空收集」，再只扫同一批分片。")
                self.btn_clear_pool.grid()
                return "partial"
            self._show_partial(result["have"], result["total"],
                               result["missing"],
                               prefix=f"（{reason}）" if reason else "")
            return "partial"

        if status == "raw":
            self.scan_text.insert("1.0", result["text"])
            self.scan_status.set(f"纯文本：{len(result['text'])} 字符")
            self._reset_pool()
            return "ok"

        if self.shard_pool:
            res = assemble_frames(list(self.shard_pool.values()))
            if res["status"] == "partial":
                self._show_partial(
                    res["have"], res["total"], res["missing"],
                    prefix="（本次未识别到二维码，已保留先前收集的分片）")
                return "partial"
        self.scan_text.insert("1.0", "（没有可识别的文本内容）")
        self.scan_status.set("未识别到二维码")
        return "none"

    def _on_scan_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            messagebox.showerror("图片读取失败", str(e), parent=self.root)
            return
        self._scan_image(img)

    def _on_scan_clipboard(self):
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                self._scan_image(img)
            elif isinstance(img, list) and img:      # 复制的是文件
                self._scan_image(Image.open(img[0]))
            else:
                self.scan_status.set("剪贴板中没有图片")
                messagebox.showinfo("无法读取图片", "剪贴板中没有图片。",
                                    parent=self.root)
        except Exception as e:
            self.scan_status.set(f"读取剪贴板失败：{e}")
            messagebox.showerror("无法读取剪贴板", str(e), parent=self.root)


def _install_callback_error_log():
    """未捕获的 Tk 回调异常写进 %TEMP%\\square-error.log

    打包成 windowed exe 后 sys.stderr 是 None，Tk 默认只在 stderr 打
    traceback，等于异常凭空消失；落到文件里才能在真机复现后回溯。
    只有真出错时才创建/追加这个文件，正常运行不写任何东西。
    """
    path = os.path.join(tempfile.gettempdir(), "square-error.log")

    def report(_root, exc_type, exc_value, exc_tb):
        # Tk 通过实例调用（root.report_callback_exception(...)），
        # 故第一个参数是 Tk 实例本身，不能用三参数签名
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n===== %s =====\n"
                        % time.strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass

    tk.Tk.report_callback_exception = report


def run():
    # 必须在创建 Tk 之前开启 DPI 感知：Win10 1703+ 走 Per-Monitor V2，
    # Win8.1 走 shcore，Win7 回退 SetProcessDPIAware（见 gui/dpi.py）。
    # 目的是窗口坐标、鼠标事件与屏幕物理像素 1:1，区域截图不错位/不只截主屏
    apply_dpi_awareness()
    # Win7 没有 shcore.dll，CTk 创建窗口时会直接抛 OSError，先替它兜底
    patch_ctk_scaling()

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    # 明确进程自己的 AppUserModelID：否则 Win11 任务栏按 pythonw.exe 归组，
    # 按钮上会一直显示 python 默认图标，窗口图标设了也不生效
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("square.app")
    except Exception:
        pass

    _install_callback_error_log()
    root = ctk.CTk()
    # 在窗口首次显示前设图标，否则任务栏会缓存 python 默认图标
    set_window_icon(root)
    SquareApp(root)
    root.mainloop()
