"""主窗口：生成器 / 解码器两个页面、预览、加载遮罩与各入口动作。"""
import ctypes
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

from ..core.codec import (assemble_frames, decode_strings, encode,
                          format_indices, parse_frames)
from ..core.puzzle import make_puzzle
from ..core.tiles import as_text, decode_tiles
from .capture import capture_region
from .preview import open_preview_popup
from .theme import (ACCENT, ACCENT_HOVER, ACCENT_SOFT, BG, BORDER, BTN,
                    BTN_HOVER, CARD, FIELD, MUTED, ON_ACCENT, RADIUS,
                    SCROLL_THUMB, SCROLL_THUMB_HOVER, SURFACE,
                    TEXT, TEXT_DISABLED, TRACK, TRACK_HOVER)
from .widgets import (SelectBox, Tooltip, fix_textbox_selection,
                      make_scan_icon, pick_font_family, set_window_icon)

# ---- 下拉预设（文案即键，变量初值必须取自这里，保证显示值与实际生效值一致）----
ERROR_OPTIONS = [
    "L · 最低（容量最大，约 7% 可恢复）",
    "M · 中等（约 15% 可恢复）",
    "Q · 较高（约 25% 可恢复）",
    "H · 最高（容量最小，约 30% 可恢复）",
]
QUALITY_OPTIONS = [
    "紧凑（分片少，码密）",
    "平衡",
    "清晰（分片多，码易识别）",
    "最清晰（分片最多，单码最疏）",
]
STRATEGY_OPTIONS = ["自动（推荐）", "强制单码", "强制分片", "压缩+分片"]

# 清晰度 → 每片 base64 载荷上限（字符）。上限越大分片越少、单码模块越密
QUALITY_PART_LIMIT = {
    "紧凑（分片少，码密）": 1700,
    "平衡": 1300,
    "清晰（分片多，码易识别）": 1000,
    "最清晰（分片最多，单码最疏）": 750,
}

# 纠错率 M：通用推荐档，截图/翻拍的摩尔纹与缩放模糊靠 15% 冗余兜底；
# 容量损失由分片吸收（分片上限不变，只是每片版本略高）
DEFAULT_ERROR = "M · 中等（约 15% 可恢复）"
# 清晰度：1000 字符/片，与旧版实际生效值一致；M 纠错下满片约 version 26
DEFAULT_QUALITY = "清晰（分片多，码易识别）"
DEFAULT_STRATEGY = "自动（推荐）"


class SquareApp:
    def __init__(self, root):
        self.root = root
        root.title("方寸 · Square")

        # 按系统 DPI 换算，保持观感一致（左右两栏：预览 + 整列文本输入）
        scale = root.winfo_fpixels("1i") / 96.0
        w, h = int(720 * scale), int(580 * scale)
        w = min(w, root.winfo_screenwidth() - 40)
        h = min(h, root.winfo_screenheight() - 80)
        root.geometry(f"{w}x{h}")
        root.minsize(int(660 * scale), int(520 * scale))
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

    # ========== 界面骨架 ==========
    def _build_ui(self):
        for child in self.root.winfo_children():
            child.destroy()

        # 顶部分段切换
        self.seg = ctk.CTkSegmentedButton(
            self.root, values=["生成器", "解码器"],
            command=self._on_seg_change,
            font=self.f_ui, height=30, corner_radius=RADIUS,
            fg_color=TRACK, selected_color=CARD, selected_hover_color=CARD,
            unselected_color=TRACK, unselected_hover_color=TRACK_HOVER,
            text_color=MUTED, text_color_disabled=TEXT_DISABLED)
        self.seg.pack(fill="x", padx=12, pady=(10, 0))
        self.seg.set("生成器")

        # 页面容器
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=12, pady=(8, 10))
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
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=0, minsize=290)
        page.grid_rowconfigure(0, weight=1)

        # ---- 左：预览 + 参数 + 操作 ----
        left = ctk.CTkFrame(page, fg_color=CARD, corner_radius=RADIUS,
                            border_width=1, border_color=BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
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
        Tooltip(btn_shot, "截图：框选屏幕区域并送解码")

        preview_wrap = ctk.CTkFrame(left, fg_color="transparent")
        preview_wrap.grid(row=1, column=0, sticky="nsew", padx=12)
        preview_wrap.grid_columnconfigure(0, weight=1)
        preview_wrap.grid_rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(preview_wrap, bg=SURFACE, height=120, bd=0,
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self._open_preview_popup)
        self.preview_canvas.bind("<Configure>", self._refit_preview)

        # 图片下方的提醒文字（有二维码时才显示）
        self.preview_hint = ctk.CTkLabel(preview_wrap, text="点击可放大",
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
            box, width=170, height=6, corner_radius=3, mode="indeterminate",
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
                      font=self.f_sm, height=30, surface=CARD).grid(
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

        # ---- 主操作 ----
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 12))
        btns.grid_columnconfigure(0, weight=3)
        btns.grid_columnconfigure(1, weight=2)

        self.btn_generate = ctk.CTkButton(
            btns, text="生成二维码", command=self._on_generate,
            font=self.f_bold, height=32, corner_radius=RADIUS,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=ON_ACCENT, text_color_disabled=ON_ACCENT)
        self.btn_generate.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(btns, text="保存二维码", command=self._on_save_image,
                      font=self.f_sm, height=32, corner_radius=RADIUS,
                      fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=TEXT, border_width=1,
                      border_color=BORDER).grid(
            row=0, column=1, sticky="ew")

        # ---- 右：文本输入（整列占满高度）----
        right = ctk.CTkFrame(page, fg_color=CARD, corner_radius=RADIUS,
                             border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew")
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
        ctk.CTkButton(head2, text="测试", command=self._insert_long_demo,
                      font=self.f_sm, width=52, height=24, corner_radius=RADIUS,
                      fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(
            side="right", padx=(0, 4))

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
        # 「选择图片」「剪贴板」，全部垂直居中；右侧小按钮与「复制」同款。
        # 截图链路不在这里：主界面预览卡右上角与大图弹窗仍走 _on_capture_region
        srow = ctk.CTkFrame(page, fg_color="transparent")
        srow.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        srow.grid_columnconfigure(0, weight=1)
        self.scan_status = tk.StringVar(value="等待输入图片…")
        ctk.CTkLabel(srow, textvariable=self.scan_status, font=self.f_sm,
                     text_color=MUTED, anchor="w").grid(
            row=0, column=0, sticky="ew")
        # 只在「分片没收齐」时才出现，平时不占地方
        self.btn_clear_pool = ctk.CTkButton(
            srow, text="清空收集", command=self._clear_pool_ui,
            font=self.f_xs, width=64, height=22, corner_radius=RADIUS,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            border_width=1, border_color=BORDER)
        self.btn_clear_pool.grid(row=0, column=1, padx=(6, 4))
        self.btn_clear_pool.grid_remove()
        # 两颗按钮取较宽者的宽度，右缘贴齐状态行右侧
        entries = [("选择图片", self._on_scan_file),
                   ("剪贴板", self._on_scan_clipboard)]
        btn_w = max(self.f_sm.measure(t) for t, _ in entries) + 26
        for col, (text, cmd) in enumerate(entries, start=2):
            ctk.CTkButton(srow, text=text, command=cmd, width=btn_w,
                          height=24, corner_radius=RADIUS, font=self.f_sm,
                          fg_color=BTN, hover_color=BTN_HOVER,
                          text_color=TEXT, border_width=1,
                          border_color=BORDER).grid(
                row=0, column=col, padx=(0, 4) if col == 2 else 0)

        self.scan_canvas = tk.Canvas(page, bg=SURFACE, height=120, bd=0,
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
            page, height=100, font=self.f_ui, wrap="word",
            fg_color=FIELD, border_width=1, border_color=BORDER,
            corner_radius=RADIUS, text_color=TEXT,
            scrollbar_button_color=SCROLL_THUMB,
            scrollbar_button_hover_color=SCROLL_THUMB_HOVER)
        self.scan_text.grid(row=3, column=0, sticky="nsew",
                            padx=12, pady=(0, 12))
        fix_textbox_selection(self.scan_text)

    # ========== 生成器动作 ==========
    def _insert_long_demo(self):
        demo = ("这是一段用来测试超长文本编码能力的示例段落。" * 200)
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", demo)

    def _import_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            with open(path, "r", encoding="utf-8") as f:
                self.text_input.delete("1.0", "end")
                self.text_input.insert("1.0", f.read())

    def _on_generate(self):
        if self._busy:
            return

        text = self.text_input.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("提示", "请输入要编码的文本", parent=self.root)
            return

        orig_len = len(text.encode("utf-8"))
        strategy = {"自动（推荐）": "auto", "强制单码": "single",
                    "强制分片": "split", "压缩+分片": "compress"}.get(
            self.var_strategy.get(), "auto")
        error = self.var_error_label.get()[:1]  # 从 "M · ..." 里取首字母

        # 根据策略决定是否压缩
        compressed = False
        if strategy == "compress":
            compressed = True
        elif strategy == "auto":
            # auto：先试单片→再无压缩分片→再压缩分片
            compressed = False  # 简化：auto 先走无压缩，放不下再提示
        elif strategy == "single":
            # 强制单码：放不下就报错
            if orig_len > 2700:
                messagebox.showerror("错误",
                    f"文本 {orig_len} 字节超过单二维码容量（~2700 bytes）\n"
                    f"请改用其他策略", parent=self.root)
                return
            compressed = False
        elif strategy == "split":
            compressed = False

        # 清晰度 → 每片 payload 上限。直接以完整文案为键，不截断文案再兜底，
        # 避免"显示某档、实际按另一档生成"
        max_b64_len = QUALITY_PART_LIMIT[self.var_quality.get()]

        # 编码放到后台线程，主线程保持响应（进度条才能动）
        self._set_busy(True)
        threading.Thread(
            target=self._generate_worker,
            args=(text, compressed, error, max_b64_len),
            daemon=True).start()
        self.root.after(50, self._poll_generate)

    def _generate_worker(self, text, compressed, error, max_b64_len):
        """后台线程：编码 + 拼图都做完，只回传结果和 PIL 图（不碰任何 Tk 控件）"""
        try:
            result = encode(text, compressed=compressed, error=error,
                            max_b64_len=max_b64_len)
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
        if status == "ok":
            self._generate_done(payload)
        else:
            self._generate_failed(payload)

    def _generate_done(self, result):
        self.gen_result = result
        self._render_preview(result)
        self._set_busy(False)
        # 换了新文本：清掉上一组收集的分片
        self._reset_pool()

    def _generate_failed(self, msg):
        self._set_busy(False)
        messagebox.showerror("生成失败", msg, parent=self.root)

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self.loading.place(x=0, y=0, relwidth=1, relheight=1)
            self.loading.lift()
            self.loading_bar.start()
            self.btn_generate.configure(state="disabled", text="生成中…",
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
            messagebox.showwarning("提示", "请先生成二维码", parent=parent)
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
        self.scan_status.set("已清空收集，可以重新选择图片")

    def _show_partial(self, have, total, missing, prefix=""):
        miss = format_indices(missing)
        if prefix:
            self.scan_text.insert("1.0", prefix + "\n\n")
        self.scan_text.insert("end",
            f"分片二维码：共 {total} 片，已收集 {have} 片，缺第 {miss} 片。\n\n"
            f"可以继续补充：再框选/选择一张含缺失分片的图，"
            f"已收集的片会按片号自动合并，凑齐后自动还原，不用再点一次。\n\n"
            f"更快的无损路径：生成器点「保存二维码」拿到原图，"
            f"再用「选择图片」按原始分辨率解码，一次就能全中。")
        self.scan_status.set(f"⚠ 已收集 {have}/{total} · 缺 {miss}")
        self.btn_clear_pool.grid()

    def _scan_image(self, pil_img):
        """对 PIL Image 执行多码检测 + 重组；分片按片号累计到收集池

        返回 "ok"（收齐/单码文本）、"partial"（分片未收齐）、
        "none"（没识别到）或 "error"（解码器异常）。
        """
        from pyzbar.pyzbar import decode as pz_decode

        self.scan_status.set("正在检测...")
        self.root.update()

        try:
            results = pz_decode(pil_img)
        except Exception as e:
            self.scan_status.set(f"pyzbar 错误: {e}")
            return "error"

        n = len(results)
        self.scan_status.set(f"检测到 {n} 个二维码")

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
            self.scan_status.set("正在细分识别…")
            self.root.update()
            extra = [s for s in decode_tiles(pil_img) if s not in raw_strings]
            if extra:
                raw_strings.extend(extra)
                n = len(raw_strings)
                frames = parse_frames(raw_strings)

        if frames:
            sig = (frames[0]["total"], frames[0]["orig_len"], frames[0]["flags"])
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
            self.scan_status.set(
                f"✓ 还原成功 · {len(text)} 字符 · {len(text.encode('utf-8'))} bytes")
            self._reset_pool()
            return "ok"

        if status == "partial":
            self._show_partial(result["have"], result["total"],
                               result["missing"])
            return "partial"

        if status == "raw":
            self.scan_text.insert("1.0", result["text"])
            self.scan_status.set(f"纯文本: {len(result['text'])} chars")
            self._reset_pool()
            return "ok"

        if self.shard_pool:
            res = assemble_frames(list(self.shard_pool.values()))
            if res["status"] == "partial":
                self._show_partial(
                    res["have"], res["total"], res["missing"],
                    prefix="(本次没有识别到二维码，已保留之前收集的分片)")
                return "partial"
        self.scan_text.insert("1.0", "(没有可识别的文本内容)")
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
            messagebox.showerror("打不开图片",
                                 f"图片读取失败：{e}", parent=self.root)
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
                self.scan_status.set("剪贴板里没有图片")
                messagebox.showinfo("提示", "剪贴板里没有图片", parent=self.root)
        except Exception as e:
            self.scan_status.set(f"读取剪贴板失败: {e}")
            messagebox.showerror("错误", str(e), parent=self.root)


def run():
    # 必须在创建 Tk 之前开启「每显示器 DPI 感知 V2」，
    # 这样窗口坐标、鼠标事件与屏幕物理像素 1:1，区域截图不会错位/只截主屏
    try:
        u = ctypes.windll.user32
        u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if not u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            raise OSError("SetProcessDpiAwarenessContext failed")
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    # 明确进程自己的 AppUserModelID：否则 Win11 任务栏按 pythonw.exe 归组，
    # 按钮上会一直显示 python 默认图标，窗口图标设了也不生效
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("square.app")
    except Exception:
        pass

    root = ctk.CTk()
    # 在窗口首次显示前设图标，否则任务栏会缓存 python 默认图标
    set_window_icon(root)
    SquareApp(root)
    root.mainloop()
