"""
PROTOTYPE — 不要在生产代码中复用此文件

问题：这个二维码工具的 GUI 应该长什么样？
此原型回答：
  1) 生成器 Tab 的参数面板、信息架构、预览布局
  2) 解码器 Tab 的图片输入、多码检测、还原流程
  3) 二维码图片导出的交互

运行: python prototype/run.py
依赖: segno, pyzbar, Pillow (Tkinter 内置)
"""
import base64, ctypes, io, os, queue, struct, sys, tempfile, threading, zlib
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox

import customtkinter as ctk
import numpy as np
from PIL import (Image, ImageDraw, ImageFilter, ImageGrab, ImageOps,
                 ImageTk)

import segno


# ---------- 剪贴板（Win32）----------
CF_DIB = 8


def copy_image_to_clipboard(img):
    """把 PIL 图片真正写进 Windows 剪贴板（CF_DIB）。

    Tk 的 clipboard_append(format="image") 并不会产生系统认识的图片格式，
    ImageGrab.grabclipboard() 读不到，所以这里直接走 Win32。
    """
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]          # 去掉 14 字节 BMP 文件头

    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    for _ in range(10):                # 剪贴板可能被其它程序占用，重试
        if u.OpenClipboard(None):
            break
        import time
        time.sleep(0.05)
    else:
        raise RuntimeError("剪贴板被其它程序占用")

    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(dib))       # GMEM_MOVEABLE
        p = k.GlobalLock(h)
        ctypes.memmove(p, dib, len(dib))
        k.GlobalUnlock(h)
        u.SetClipboardData(CF_DIB, h)
    finally:
        u.CloseClipboard()


# ---------- 图标 / 提示 ----------
def make_scan_icon(size=16, scale=4, color="#1f2328"):
    """极简线性「截图」图标：四角取景框。按 scale 倍绘制，缩小后边缘干净。"""
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, int(round(1.4 * scale)))
    m = int(round(1.5 * scale))
    ln = int(round(size * scale * 0.34))
    hi = s - m - 1
    for x, y, dx, dy in ((m, m, 1, 1), (hi, m, -1, 1),
                         (m, hi, 1, -1), (hi, hi, -1, -1)):
        d.line([(x, y), (x + dx * ln, y)], fill=color, width=w)
        d.line([(x, y), (x, y + dy * ln)], fill=color, width=w)
    return img


class Tooltip:
    """轻量悬停提示（CTk 本身没有 tooltip）"""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _=None):
        if self.tip or not self.widget.winfo_ismapped():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 26
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=self.text, bg="#2b2f36", fg="#ffffff",
                 font=("Microsoft YaHei UI", 12), padx=6, pady=2).pack()
        tip.geometry(f"+{x}+{y}")
        self.tip = tip

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------- 核心编解码（从 PoC 直接搬，故意不抽象）----------
MAGIC = b"QRC\x01"
HEADER_SIZE_B64 = 20
HEADER_SIZE_BIN = 13
FLAG_COMPRESSED = 0x01


def _b64e(d): return base64.b64encode(d).decode("ascii")
def _b64d(s): return base64.b64decode(s)


def encode(text, compressed=False, max_b64_len=1600, error="L", prefer_single=True):
    """编码: str → list of QRCode + info dict
    prefer_single: 先尝试纯文本单片（不 base64、不分片），塞不下再分片
    """
    # 短路：先试纯文本单片（不压缩、不 base64）
    if prefer_single and not compressed:
        try:
            qr = segno.make(text, error=error)
            return {
                "strategy": "single-plain",
                "qrs": [qr],
                "total_parts": 1,
                "original_bytes": len(text.encode("utf-8")),
                "compressed": False,
                "frames_used": 0,
            }
        except segno.encoder.DataOverflowError:
            pass  # 单片塞不下，继续走分片流程

    raw = zlib.compress(text.encode("utf-8")) if compressed else text.encode("utf-8")
    full_b64 = _b64e(raw)
    data_per_part = max_b64_len - HEADER_SIZE_B64
    total = max(1, (len(full_b64) + data_per_part - 1) // data_per_part)

    parts = []
    for i in range(total):
        flags = FLAG_COMPRESSED if compressed else 0
        bin_hdr = MAGIC + bytes([flags]) + struct.pack(">HH", total, i) + struct.pack(">I", len(raw))
        chunk = full_b64[i * data_per_part : (i + 1) * data_per_part]
        parts.append(_b64e(bin_hdr) + chunk)

    # 单片如果能塞下直接存纯文本（省一帧头开销）
    if total == 1 and not compressed and len(text.encode("utf-8")) < 2700:
        qr = segno.make(text, error=error)
        return {"qrs": [qr], "payloads": [text], "compressed": False,
                "total_parts": 1, "original_bytes": len(text.encode("utf-8")),
                "strategy": "single-plain", "frames_used": 0}

    qrs = [segno.make(p, error=error) for p in parts]
    return {"qrs": qrs, "payloads": parts, "compressed": compressed,
            "total_parts": total, "original_bytes": len(text.encode("utf-8")),
            "strategy": "compressed-split" if compressed else "plain-split",
            "frames_used": total}


def parse_frames(strings):
    """从解码出的字符串里挑出带协议帧头的分片"""
    frames = []
    for s in strings:
        try:
            hdr = _b64d(s[:HEADER_SIZE_B64])
        except Exception:
            continue
        if not hdr.startswith(MAGIC):
            continue
        try:
            frames.append({
                "flags": hdr[4],
                "total": struct.unpack(">H", hdr[5:7])[0],
                "index": struct.unpack(">H", hdr[7:9])[0],
                "orig_len": struct.unpack(">I", hdr[9:13])[0],
                "b64": s[HEADER_SIZE_B64:],
                "payload": s,
            })
        except Exception:
            continue
    return frames


def assemble_frames(frames):
    """按片号索引重组（帧可以来自不同次截图/不同图片）"""
    if not frames:
        return {"status": "empty"}
    total = frames[0]["total"]
    compressed = bool(frames[0]["flags"] & FLAG_COMPRESSED)
    by_index = {}
    for f in frames:
        if f["total"] == total:
            by_index[f["index"]] = f

    missing = [i for i in range(total) if i not in by_index]
    if missing:
        return {"status": "partial", "total": total, "have": len(by_index),
                "missing": missing}

    full_b64 = "".join(by_index[i]["b64"] for i in range(total))
    try:
        raw = _b64d(full_b64)
        text = zlib.decompress(raw).decode("utf-8") if compressed \
            else raw.decode("utf-8")
        return {"status": "ok", "text": text}
    except Exception:
        return {"status": "partial", "total": total, "have": len(by_index),
                "missing": missing}


def decode_strings(strings):
    """
    解码: list[str] → dict
      {"status": "ok", "text": "..."}          完整还原
      {"status": "partial", "total": 18, "have": 1, "missing": [...]}
      {"status": "raw", "text": "..."}          纯文本单片/无法识别协议
      {"status": "empty"}                       空输入
    """
    if not strings:
        return {"status": "empty"}
    frames = parse_frames(strings)
    # 没有任何协议帧头 → 当作纯文本
    if not frames:
        return {"status": "raw", "text": "\n".join(strings)}
    return assemble_frames(frames)


def format_indices(idx):
    """[1,2,3,7] → '2,3,4,8'（1 基，连续段合并）"""
    idx = sorted(idx)
    parts, i = [], 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        parts.append(f"{idx[i] + 1}" if i == j else f"{idx[i] + 1}-{idx[j] + 1}")
        i = j + 1
    return ",".join(parts)


# ---------- 密集拼接图的二次识别 ----------
def _as_text(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _ink_segments(profile, min_len=12):
    """一维投影 → 非空白段 [(start, end)]（end 含）"""
    segs, start = [], None
    for i, v in enumerate(profile):
        if v:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                segs.append((start, i - 1))
            start = None
    if start is not None and len(profile) - start >= min_len:
        segs.append((start, len(profile) - 1))
    return segs


def _ink_mask(gray):
    """局部均值阈值，比全局 128/200 更抗低对比和光照不均"""
    h, w = gray.shape
    r = max(7, min(h, w) // 40)
    pad = np.zeros((h + 1, w + 1), np.float64)
    pad[1:, 1:] = gray
    ii = pad.cumsum(0).cumsum(1)
    ys, xs = np.arange(h), np.arange(w)
    y0 = np.clip(ys - r, 0, h)
    y1 = np.clip(ys + r + 1, 0, h)
    x0 = np.clip(xs - r, 0, w)
    x1 = np.clip(xs + r + 1, 0, w)
    s = (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)]
         - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])
    cnt = np.maximum((y1 - y0)[:, None] * (x1 - x0)[None, :], 1)
    mask = gray < (s / cnt - 10)
    ratio = float(mask.mean())
    if ratio > 0.65 or ratio < 0.002:      # 阈值失效时退回全局
        mask = gray < 128
    return mask.astype(np.uint8)


def _estimate_pitch(profile):
    """投影自相关估计码块周期（像素）"""
    p = profile.astype(np.float64)
    n = len(p)
    if n < 40 or not p.any():
        return 0
    p = p - p.mean()
    f = np.fft.rfft(p, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    lo, hi = max(16, n // 30), n // 2
    if hi <= lo:
        return 0
    lag = lo + int(np.argmax(ac[lo:hi]))
    return lag if ac[lag] > 0 else 0


def _decode_cell(cell, scales=(1, 2, 3), strong=True):
    """单码识别：补静默区 + 自动对比/锐化 + 多尺度。

    strong 额外做两次锐化（轻/重），用于低对比、压缩噪声的截图。
    """
    from pyzbar.pyzbar import decode as pz

    w, h = cell.size
    if w < 24 or h < 24:
        return []
    pad = max(6, int(round(min(w, h) * 0.10)))
    base = cell.convert("L")
    ac = ImageOps.autocontrast(base)
    variants = [(base, tuple(scales)),
                (ac.filter(ImageFilter.SHARPEN), tuple(scales))]
    if strong:
        big = ac.resize((w * 3, h * 3), Image.LANCZOS)
        variants.append((big.filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=2)),
            (1,)))
        variants.append((big.filter(
            ImageFilter.UnsharpMask(radius=1.4, percent=200, threshold=2)),
            (1,)))

    out = []
    for v, sc in variants:
        padded = Image.new("L", (v.width + pad * 2, v.height + pad * 2), 255)
        padded.paste(v, (pad, pad))
        for f in sc:
            im = padded if f == 1 else padded.resize(
                (padded.width * f, padded.height * f), Image.NEAREST)
            for r in pz(im):
                s = _as_text(r.data)
                if s not in out:
                    out.append(s)
    return out


def _drop_contained(boxes):
    """去掉被更大的框完全包住的框（脏图会把一个码切成一堆碎块）"""
    kept = []
    for b in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]),
                    reverse=True):
        if any(b[0] >= k[0] and b[1] >= k[1] and b[2] <= k[2] and b[3] <= k[3]
               for k in kept):
            continue
        kept.append(b)
    return kept


def _grid_cells(size, px, py):
    """按周期 + 相位给出所有格子（返回逐相位的格子列表）"""
    w, h = size
    out = []
    for oy in range(0, py, max(1, py // 4)):
        for ox in range(0, px, max(1, px // 4)):
            cells = []
            for y in range(oy, h - py // 2, py):
                for x in range(ox, w - px // 2, px):
                    cells.append((x, y, min(x + px, w), min(y + py, h)))
            if cells:
                out.append(cells)
    return out


def decode_tiles(pil_img):
    """拼接大图二次识别：白带切分 / 周期网格 + 补静默区 + 多尺度。

    1) 自适应阈值求墨迹掩膜，投影出白色分隔带切块（常规拼图）；
    2) 没有白带（码贴码）或某段明显宽于单码时，用自相关估周期，
       枚举相位生成网格逐格重试（借邻片位置补偿漏检）。
    """
    from pyzbar.pyzbar import decode as pz

    img = pil_img
    if max(img.size) > 1600:                # 大图降采样做分析，控制内存/耗时
        k = 1600 / max(img.size)
        img = img.resize((max(1, int(img.width * k)),
                          max(1, int(img.height * k))), Image.LANCZOS)

    gray = np.array(img.convert("L"))
    mask = _ink_mask(gray)
    row_prof = mask.sum(axis=1)
    col_prof = mask.sum(axis=0)
    row_segs = _ink_segments(row_prof, min_len=16)

    out = []

    def harvest(cells, scales=(1, 2, 3)):
        n = 0
        for box in cells:
            for s in _decode_cell(img.crop(box), scales):
                if s not in out:
                    out.append(s)
                    n += 1
        return n

    # 常规路径：沿白色分隔带切成一个个码
    cells = []
    for y0, y1 in row_segs:
        band = mask[y0:y1 + 1]
        for x0, x1 in _ink_segments(band.sum(axis=0), min_len=16):
            cells.append((x0, y0, x1 + 1, y1 + 1))
    # 脏图会把一个码切成很多互相包含的碎块：只留最大的，省掉重复识别
    cells = _drop_contained(cells)
    if cells:
        harvest(cells)

    # 贴边/贴码：用周期网格再补一轮
    px = _estimate_pitch(col_prof)
    py = _estimate_pitch(row_prof)
    # 码块是正方形：某一轴周期不可信时（例如视口只露出两行）沿用另一轴
    if px >= 32 and (py < 32 or not 0.7 <= py / px <= 1.4):
        py = px
    elif py >= 32 and (px < 32 or not 0.7 <= px / py <= 1.4):
        px = py
    if px >= 32 and py >= 32:
        merged = (
            len(row_segs) == 1 and row_segs[0] == (0, len(row_prof) - 1)
        ) or any(x1 - x0 > px * 1.6 or y1 - y0 > py * 1.6
                 for x0, y0, x1, y1 in cells)
        if merged:
            best_cells, best_n = None, 0
            for grid in _grid_cells(img.size, px, py):
                n = 0
                for box in grid:
                    for s in _decode_cell(img.crop(box), scales=(1,),
                                          strong=False):
                        if s not in out:
                            n += 1
                if n > best_n:
                    best_cells, best_n = grid, n
            if best_cells:
                harvest(best_cells)

    return out


# ---------- 拼图 ----------
def make_puzzle(qr_images, cols=None, scale=15):
    """list[segno.QRCode] → PIL.Image 拼图"""
    import tempfile
    pil_imgs = []
    tmpdir = tempfile.mkdtemp()
    for i, qr in enumerate(qr_images):
        fpath = os.path.join(tmpdir, f"_puzzle_{i}.png")
        qr.save(fpath, scale=scale)
        pil_imgs.append(Image.open(fpath).convert("RGB"))

    if cols is None:
        cols = min(4, len(pil_imgs))
    rows = (len(pil_imgs) + cols - 1) // cols
    w = max(i.width for i in pil_imgs)
    h = max(i.height for i in pil_imgs)
    canvas = Image.new("RGB", (cols * w, rows * h), "white")
    for idx, img in enumerate(pil_imgs):
        canvas.paste(img, ((idx % cols) * w, (idx // cols) * h))
    return canvas


# ---------- CustomTkinter GUI ----------
BG = "#f5f6f8"
CARD = "#ffffff"
FIELD = "#fafbfc"
BORDER = "#e3e6ea"
TEXT = "#1f2328"
MUTED = "#5c6572"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
BTN = "#f1f3f6"
BTN_HOVER = "#e6e9ee"
TRACK = "#e9ecf1"


class QRToolApp:
    def __init__(self, root):
        self.root = root
        root.title("QR Tool")

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

        families = set(tkfont.families(root))
        base = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
                     if f in families), "TkDefaultFont")
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
            font=self.f_ui, height=30, corner_radius=6,
            fg_color=TRACK, selected_color=CARD, selected_hover_color=CARD,
            unselected_color=TRACK, unselected_hover_color="#e1e4ea",
            text_color=MUTED)
        self.seg.pack(fill="x", padx=12, pady=(10, 0))
        self.seg.set("生成器")

        # 状态条
        self.status = tk.StringVar(value="就绪")
        ctk.CTkLabel(self.root, textvariable=self.status, font=self.f_sm,
                     text_color=MUTED, anchor="w").pack(
            side="bottom", fill="x", padx=12, pady=(0, 6))

        # 页面容器
        self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=12, pady=(8, 0))
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
        left = ctk.CTkFrame(page, fg_color=CARD, corner_radius=8,
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
                                 width=28, height=20, corner_radius=5,
                                 fg_color=BTN, hover_color=BTN_HOVER,
                                 border_width=1, border_color=BORDER)
        btn_shot.pack(side="right")
        Tooltip(btn_shot, "截图：框选屏幕区域并送解码")

        preview_wrap = ctk.CTkFrame(left, fg_color="transparent")
        preview_wrap.grid(row=1, column=0, sticky="nsew", padx=12)
        preview_wrap.grid_columnconfigure(0, weight=1)
        preview_wrap.grid_rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(preview_wrap, bg=FIELD, height=120, bd=0,
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
        self.loading = ctk.CTkFrame(preview_wrap, fg_color=FIELD, corner_radius=0,
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

        ctk.CTkLabel(params, text="纠错率", font=self.f_sm,
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_error_label = tk.StringVar(value="L · 最低（容量最大，约 7% 可恢复）")
        ctk.CTkOptionMenu(
            params, variable=self.var_error_label,
            values=["L · 最低（容量最大，约 7% 可恢复）",
                    "M · 中等（约 15% 可恢复）",
                    "Q · 较高（约 25% 可恢复）",
                    "H · 最高（容量最小，约 30% 可恢复）"],
            font=self.f_sm, dropdown_font=self.f_sm, height=28,
            corner_radius=6, width=120, dynamic_resizing=True,
            fg_color=FIELD, button_color=TRACK, button_hover_color=BTN_HOVER,
            text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, dropdown_hover_color=TRACK).grid(
            row=0, column=1, sticky="ew", pady=2)

        ctk.CTkLabel(params, text="清晰度", font=self.f_sm,
                     text_color=MUTED).grid(row=1, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_quality = tk.StringVar(value="清晰")
        ctk.CTkOptionMenu(
            params, variable=self.var_quality,
            values=["紧凑（分片少，码密）", "平衡",
                    "清晰（分片多，码易识别）",
                    "最清晰（分片最多，version≤20）"],
            font=self.f_sm, dropdown_font=self.f_sm, height=28,
            corner_radius=6, width=120, dynamic_resizing=True,
            fg_color=FIELD, button_color=TRACK, button_hover_color=BTN_HOVER,
            text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, dropdown_hover_color=TRACK).grid(
            row=1, column=1, sticky="ew", pady=2)

        ctk.CTkLabel(params, text="编码策略", font=self.f_sm,
                     text_color=MUTED).grid(row=2, column=0, sticky="w",
                                            padx=(0, 8))
        self.var_strategy = tk.StringVar(value="自动（推荐）")
        ctk.CTkOptionMenu(
            params, variable=self.var_strategy,
            values=["自动（推荐）", "强制单码", "强制分片", "压缩+分片"],
            font=self.f_sm, dropdown_font=self.f_sm, height=28,
            corner_radius=6, width=120, dynamic_resizing=True,
            fg_color=FIELD, button_color=TRACK, button_hover_color=BTN_HOVER,
            text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, dropdown_hover_color=TRACK).grid(
            row=2, column=1, sticky="ew", pady=2)

        # ---- 主操作 ----
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 12))
        btns.grid_columnconfigure(0, weight=3)
        btns.grid_columnconfigure(1, weight=2)

        self.btn_generate = ctk.CTkButton(
            btns, text="生成二维码", command=self._on_generate,
            font=self.f_bold, height=32, corner_radius=6,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff")
        self.btn_generate.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(btns, text="保存二维码", command=self._on_save_image,
                      font=self.f_sm, height=32, corner_radius=6,
                      fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=TEXT, border_width=1,
                      border_color=BORDER).grid(
            row=0, column=1, sticky="ew")

        # ---- 右：文本输入（整列占满高度）----
        right = ctk.CTkFrame(page, fg_color=CARD, corner_radius=8,
                             border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        head2 = ctk.CTkFrame(right, fg_color="transparent")
        head2.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkLabel(head2, text="文本输入", font=self.f_bold,
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(head2, text="导入", command=self._import_file,
                      font=self.f_sm, width=52, height=24, corner_radius=6,
                      fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(side="right")
        ctk.CTkButton(head2, text="测试", command=self._insert_long_demo,
                      font=self.f_sm, width=52, height=24, corner_radius=6,
                      fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(
            side="right", padx=(0, 4))

        self.text_input = ctk.CTkTextbox(
            right, font=self.f_ui, wrap="word",
            fg_color=FIELD, border_width=1, border_color=BORDER,
            corner_radius=6, text_color=TEXT,
            scrollbar_button_color=TRACK,
            scrollbar_button_hover_color=BTN_HOVER)
        self.text_input.grid(row=1, column=0, sticky="nsew",
                             padx=10, pady=(0, 10))

    # ========== 解码器页 ==========
    def _build_decoder_page(self):
        page = ctk.CTkFrame(self.content, fg_color=CARD, corner_radius=8,
                            border_width=1, border_color=BORDER)
        page.grid(row=0, column=0, sticky="nsew")
        self.dec_page = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=3)
        page.grid_rowconfigure(4, weight=2)

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        for i, (text, cmd) in enumerate([("选择图片", self._on_scan_file),
                                         ("剪贴板", self._on_scan_clipboard),
                                         ("全屏截图", self._on_scan_fullscreen),
                                         ("区域截图", self._on_scan_region)]):
            ctk.CTkButton(top, text=text, command=cmd, font=self.f_sm,
                          height=28, corner_radius=6, fg_color=BTN,
                          hover_color=BTN_HOVER, text_color=TEXT,
                          border_width=1, border_color=BORDER).grid(
                row=i // 2, column=i % 2, sticky="ew", pady=(0, 4),
                padx=(0, 4) if i % 2 == 0 else 0)

        srow = ctk.CTkFrame(page, fg_color="transparent")
        srow.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 4))
        srow.grid_columnconfigure(0, weight=1)
        self.scan_status = tk.StringVar(value="等待输入图片…")
        ctk.CTkLabel(srow, textvariable=self.scan_status, font=self.f_sm,
                     text_color=MUTED, anchor="w").grid(
            row=0, column=0, sticky="ew")
        # 只在「分片没收齐」时才出现，平时不占地方
        self.btn_clear_pool = ctk.CTkButton(
            srow, text="清空收集", command=self._clear_pool_ui,
            font=self.f_xs, width=64, height=22, corner_radius=6,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
            border_width=1, border_color=BORDER)
        self.btn_clear_pool.grid(row=0, column=1, padx=(6, 0))
        self.btn_clear_pool.grid_remove()

        self.scan_canvas = tk.Canvas(page, bg=FIELD, height=120, bd=0,
                                     highlightthickness=1,
                                     highlightbackground=BORDER)
        self.scan_canvas.grid(row=2, column=0, sticky="nsew", padx=12)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(head, text="还原文本", font=self.f_bold,
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(head, text="复制", width=52, height=24, font=self.f_sm,
                      corner_radius=6, fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=TEXT, border_width=1, border_color=BORDER,
                      command=lambda: self.root.clipboard_append(
                          self.scan_text.get("1.0", "end"))).pack(side="right")

        self.scan_text = ctk.CTkTextbox(
            page, height=100, font=self.f_ui, wrap="word",
            fg_color=FIELD, border_width=1, border_color=BORDER,
            corner_radius=6, text_color=TEXT,
            scrollbar_button_color=TRACK,
            scrollbar_button_hover_color=BTN_HOVER)
        self.scan_text.grid(row=4, column=0, sticky="nsew",
                            padx=12, pady=(0, 12))

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
        error = self.var_error_label.get()[0]  # 从 "L · ..." 里取首字母

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

        # 清晰度 → 每片 payload 上限
        quality_map = {
            "紧凑": 1700,
            "平衡": 1300,
            "清晰": 1000,
            "最清晰": 750,
        }
        quality_key = self.var_quality.get().split("（")[0]
        max_b64_len = quality_map.get(quality_key, 1000)

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
        versions = [qr.version for qr in result["qrs"]]
        self.status.set(
            f"{result['total_parts']} 片 · version {min(versions)}-{max(versions)} · "
            f"{result['original_bytes']} bytes"
        )
        self._set_busy(False)
        # 换了新文本：清掉上一组收集的分片
        self._reset_pool()

    def _generate_failed(self, msg):
        self._set_busy(False)
        self.status.set("生成失败")
        messagebox.showerror("生成失败", msg, parent=self.root)

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self.loading.place(x=0, y=0, relwidth=1, relheight=1)
            self.loading.lift()
            self.loading_bar.start()
            self.btn_generate.configure(state="disabled", text="生成中…",
                                        fg_color="#9db9f0",
                                        hover_color="#9db9f0")
            self.status.set("正在生成…")
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

        win = ctk.CTkToplevel(self.root)
        win.title("二维码大图预览")
        # 设为 root 的从属窗口：Windows 上 owned window 始终压在父窗口之上
        win.transient(self.root)
        pw = min(760, win.winfo_screenwidth() - 60)
        ph = min(620, win.winfo_screenheight() - 60)
        win.geometry(f"{pw}x{ph}")
        win.configure(fg_color=BG)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)

        puzzle = self._preview_puzzle

        # 工具条
        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=8)

        ctk.CTkLabel(bar, text="缩放", font=self.f_sm,
                     text_color=MUTED).pack(side="left")
        zoom_var = tk.DoubleVar(value=1.0)
        pct_var = tk.StringVar(value="100%")

        SB_W, SB_H = 16, 16   # 滚动条厚度(12) + 与画布的间距(4)

        # 缩放后的图片尺寸与 PhotoImage（留引用防止被回收）
        img_state = {"w": 0, "h": 0, "photo": None, "vbar": False, "hbar": False}

        def layout():
            """按视口大小决定两条滚动条显隐，并重排图片（不重新缩放图片）"""
            w, h = img_state["w"], img_state["h"]
            photo = img_state["photo"]
            if photo is None:
                return
            # 基准取 canvas_frame 自身的尺寸：它由窗口大小决定，
            # 不受滚动条显隐影响，所以显隐不会反过来改变判定、不会来回抖
            fw = canvas_frame.winfo_width()
            fh = canvas_frame.winfo_height()
            if fw <= 1 or fh <= 1:
                return
            # 该方向装得下就隐藏该方向的滚动条；隐藏后可视区只会更大，
            # 判定结果不会翻转。横纵互相独立，不会互相触发。
            want_v, want_h = w > fw, h > fh
            if want_v != img_state["vbar"]:
                img_state["vbar"] = want_v
                if want_v:
                    sb_v.grid()
                else:
                    sb_v.grid_remove()
            if want_h != img_state["hbar"]:
                img_state["hbar"] = want_h
                if want_h:
                    sb_h.grid()
                else:
                    sb_h.grid_remove()

            cw = fw - (SB_W if want_v else 0)
            ch = fh - (SB_H if want_h else 0)
            canvas.delete("all")
            # 居中绘制
            x = max(0, (cw - w) // 2)
            y = max(0, (ch - h) // 2)
            canvas.create_image(x, y, anchor="nw", image=photo)
            # 只有装不下时才设 scrollregion
            if want_v or want_h:
                canvas.configure(scrollregion=(0, 0, max(cw, w), max(ch, h)))
            else:
                canvas.configure(scrollregion="")
                canvas.xview_moveto(0)
                canvas.yview_moveto(0)
            size_lbl.configure(
                text=f"原图 {puzzle.width}×{puzzle.height}  ·  显示 {w}×{h}")

        def refresh():
            z = zoom_var.get()
            pct_var.set(f"{int(z * 100)}%")
            img_state["w"] = max(1, int(puzzle.width * z))
            img_state["h"] = max(1, int(puzzle.height * z))
            scaled = puzzle.resize((img_state["w"], img_state["h"]),
                                   Image.LANCZOS)
            img_state["photo"] = ImageTk.PhotoImage(scaled)
            layout()

        def on_scale(val):
            zoom_var.set(float(val))
            refresh()

        def fit():
            win.update_idletasks()
            fw = canvas_frame.winfo_width()
            fh = canvas_frame.winfo_height()
            if fw <= 1 or fh <= 1:      # 还没完成布局，稍后再试
                win.after(50, fit)
                return
            # 按「两条滚动条都隐藏」时的最大可视区算，且向下取整，
            # 避免适应窗口后刚好溢出又把滚动条显示回来
            z = min(fw / puzzle.width, fh / puzzle.height, 1.0)
            z = max(0.05, min(1.0, int(z * 100) / 100))
            zoom_var.set(z)
            refresh()

        ctk.CTkSlider(bar, from_=0.05, to=2.0, variable=zoom_var,
                      command=on_scale, width=150, height=16,
                      fg_color=TRACK, progress_color=ACCENT,
                      button_color=ACCENT,
                      button_hover_color=ACCENT_HOVER).pack(side="left", padx=6)
        ctk.CTkLabel(bar, textvariable=pct_var, width=44, font=self.f_sm,
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(bar, text="适应窗口", command=fit, width=64, height=26,
                      font=self.f_sm, corner_radius=6, fg_color=BTN,
                      hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(side="left", padx=4)
        # 与主预览区右上角那颗截图按钮完全一致（同图标、同尺寸、同提示、同回调）
        btn_shot = ctk.CTkButton(bar, text="", image=self.icon_scan,
                                 command=lambda: self._on_capture_region(win),
                                 width=28, height=20, corner_radius=5,
                                 fg_color=BTN, hover_color=BTN_HOVER,
                                 border_width=1, border_color=BORDER)
        btn_shot.pack(side="right", padx=(4, 0))
        Tooltip(btn_shot, "截图：框选屏幕区域并送解码")

        ctk.CTkButton(bar, text="保存原图",
                      command=lambda: self._on_save_image(parent=win),
                      width=64, height=26, font=self.f_sm, corner_radius=6,
                      fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(side="right")

        # 画布 + 滚动条：两条滚动条都放在同一个 frame 里，
        # 这样「视口基准」= frame 自身尺寸，与滚动条是否显示无关，
        # 显隐不会改变下一次判定的基准（避免经典的两边互相挤出又缩回）
        canvas_frame = ctk.CTkFrame(win, fg_color="#eceff3", corner_radius=0)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(canvas_frame, bg="#eceff3", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")

        sb_v = ctk.CTkScrollbar(canvas_frame, command=canvas.yview, width=12,
                                fg_color=TRACK, button_color="#c8cdd6")
        sb_v.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        canvas.configure(yscrollcommand=sb_v.set)

        sb_h = ctk.CTkScrollbar(canvas_frame, command=canvas.xview, height=12,
                                orientation="horizontal", fg_color=TRACK,
                                button_color="#c8cdd6")
        sb_h.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        canvas.configure(xscrollcommand=sb_h.set)

        # 先收起来，由 layout() 按实际视口决定是否显示（与 img_state 初值一致）
        sb_v.grid_remove()
        sb_h.grid_remove()

        size_lbl = ctk.CTkLabel(win, text="", font=self.f_sm, text_color=MUTED)
        size_lbl.grid(row=2, column=0, sticky="w", padx=10, pady=(2, 8))

        # 改变弹窗尺寸后重新判断两条滚动条
        canvas_frame.bind("<Configure>", lambda e: layout())

        # 鼠标滚轮缩放
        def _wheel(e):
            delta = -0.1 if e.delta > 0 else 0.1
            new = max(0.05, min(2.0, zoom_var.get() + delta))
            zoom_var.set(round(new, 2))
            refresh()

        canvas.bind("<MouseWheel>", _wheel)

        # 初始 fit
        win.after(100, fit)

        # CTkToplevel 初始化时会为了改标题栏颜色 withdraw → deiconify，
        # 重新 show 出来不带激活，容易落到主窗口后面；等它折腾完再抬一次
        def bring_front():
            if not win.winfo_exists():
                return
            win.lift()
            win.focus_force()

        win.after(30, bring_front)

    # ---------- 区域截图（真实屏幕像素） ----------
    def _virtual_screen(self):
        """虚拟桌面矩形（物理像素，可跨多显示器，含负坐标）"""
        u = ctypes.windll.user32
        return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                u.GetSystemMetrics(78), u.GetSystemMetrics(79))

    def _tk_to_phys_scale(self):
        """Tk 坐标 → 屏幕物理像素的换算系数（DPI 感知下通常为 1）"""
        sw = self.root.winfo_screenwidth()
        phys = ctypes.windll.user32.GetSystemMetrics(0)
        if not sw or not phys:
            return 1.0
        k = phys / sw
        return 1.0 if abs(k - 1.0) < 0.02 else k

    def _restore_owner(self, owner):
        """恢复框选期间临时隐藏的大图弹窗，并保持它在主窗口之上"""
        if owner is None or not owner.winfo_exists():
            return
        owner.deiconify()
        owner.lift()

    def _on_capture_region(self, owner=None):
        """区域截图：全屏遮罩拖拽框选 → 进剪贴板 → 解码器还原

        owner: 触发截图的大图预览弹窗。框选/抓屏期间临时隐藏，
        结束后恢复——既不让它挡住所框区域，也不让它被截进图里。
        """
        vx, vy, vw, vh = self._virtual_screen()
        if vw <= 0 or vh <= 0:
            messagebox.showerror("错误", "无法获取屏幕尺寸",
                                 parent=owner or self.root)
            return
        k = self._tk_to_phys_scale()

        if owner is not None:
            owner.withdraw()

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.34)
        top.configure(bg="#000000")
        top.geometry(f"{int(vw / k)}x{int(vh / k)}{int(vx / k):+d}{int(vy / k):+d}")

        cv = tk.Canvas(top, bg="#000000", highlightthickness=0,
                       cursor="crosshair")
        cv.pack(fill="both", expand=True)
        cv.create_text(int(vw / k) // 2, 28,
                       text="拖拽框选二维码区域 · Esc / 右键取消",
                       fill="#ffffff", font=("Microsoft YaHei UI", 14))

        state = {"sx": None, "sy": None, "closed": False}

        def on_press(e):
            if state["closed"]:
                return
            state["sx"], state["sy"] = e.x, e.y
            cv.delete("sel")

        def on_move(e):
            if state["closed"] or state["sx"] is None:
                return
            cv.delete("sel")
            cv.create_rectangle(state["sx"], state["sy"], e.x, e.y,
                                outline="#ffffff", width=2, dash=(4, 3),
                                tags="sel")
            cv.create_text(e.x + 12, e.y + 12, anchor="nw",
                           text=f"{int(abs(e.x - state['sx']) * k)}"
                                f"×{int(abs(e.y - state['sy']) * k)}",
                           fill="#ffffff", font=("Microsoft YaHei UI", 12),
                           tags="sel")

        def cancel(_=None):
            # Esc / 右键同一条取消路径；closed 保证连点多次也只关一次
            if state["closed"]:
                return
            state["closed"] = True
            top.destroy()          # 遮罩销毁，绑定随控件一起释放，不留监听
            self._restore_owner(owner)
            self.status.set("已取消截图")

        def on_release(e):
            # 拖拽中右键取消后，左键松开不能再触发截图
            if state["closed"] or state["sx"] is None:
                return
            state["closed"] = True
            x1, x2 = sorted((state["sx"], e.x))
            y1, y2 = sorted((state["sy"], e.y))
            px1 = int(round(vx + x1 * k))
            py1 = int(round(vy + y1 * k))
            px2 = int(round(vx + x2 * k))
            py2 = int(round(vy + y2 * k))
            top.destroy()
            if px2 - px1 < 24 or py2 - py1 < 24:
                self._restore_owner(owner)
                messagebox.showinfo("提示", "框选区域太小，请重新框选",
                                    parent=owner or self.root)
                return
            # 遮罩已销毁，留一点时间给桌面重绘，再抓真实像素
            self.root.after(150, lambda: self._finish_region(
                px1, py1, px2, py2, owner))

        cv.bind("<ButtonPress-1>", on_press)
        cv.bind("<B1-Motion>", on_move)
        cv.bind("<ButtonRelease-1>", on_release)
        cv.bind("<Button-3>", cancel)      # 右键等价 Esc；拖拽中也能取消
        top.bind("<Escape>", cancel)
        top.focus_force()
        cv.focus_set()

    def _finish_region(self, px1, py1, px2, py2, owner=None):
        vx, vy, _, _ = self._virtual_screen()
        try:
            full = ImageGrab.grab(all_screens=True)
        except Exception as e:
            self._restore_owner(owner)
            messagebox.showerror("错误", f"截图失败: {e}",
                                 parent=owner or self.root)
            return
        # 像素已经抓完，这时才把弹窗放回来，保证它没被截进图里
        self._restore_owner(owner)
        # all_screens 的图左上角对应虚拟屏原点 (vx, vy)
        img = full.crop((px1 - vx, py1 - vy, px2 - vx, py2 - vy))

        try:
            copy_image_to_clipboard(img)
        except Exception as e:
            self.status.set(f"写入剪贴板失败: {e}")

        self.seg.set("解码器")
        self._show_page(1)
        if self._scan_image(img) == 0:
            messagebox.showinfo("提示", "未识别到二维码，请重新框选",
                                parent=owner or self.root)

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
            self.status.set(f"二维码已保存: {path}")

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
            f"再用「选择图片」按原始分辨率解码，一次就能全中。\n\n"
            f"提示：模块不足 2 像素时任何解码器都无法还原，"
            f"这是采样不足，不是软件故障。")
        self.scan_status.set(f"⚠ 已收集 {have}/{total} · 缺 {miss}")
        self.btn_clear_pool.grid()

    def _scan_image(self, pil_img):
        """对 PIL Image 执行多码检测 + 重组；分片按片号累计到收集池"""
        from pyzbar.pyzbar import decode as pz_decode

        self.scan_status.set("正在检测...")
        self.root.update()

        try:
            results = pz_decode(pil_img)
        except Exception as e:
            self.scan_status.set(f"pyzbar 错误: {e}")
            return 0

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

        raw_strings = [_as_text(r.data) for r in results]

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

        elif status == "partial":
            self._show_partial(result["have"], result["total"],
                               result["missing"])

        elif status == "raw":
            self.scan_text.insert("1.0", result["text"])
            self.scan_status.set(f"纯文本: {len(result['text'])} chars")
            self._reset_pool()

        else:
            if self.shard_pool:
                res = assemble_frames(list(self.shard_pool.values()))
                if res["status"] == "partial":
                    self._show_partial(
                        res["have"], res["total"], res["missing"],
                        prefix="(本次没有识别到二维码，已保留之前收集的分片)")
                else:
                    self.scan_text.insert("1.0", "(没有可识别的文本内容)")
                    self.scan_status.set("未识别到二维码")
            else:
                self.scan_text.insert("1.0", "(没有可识别的文本内容)")
                self.scan_status.set("未识别到二维码")

        return n

    def _on_scan_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif"), ("所有文件", "*.*")])
        if path:
            self._scan_image(Image.open(path))

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

    def _on_scan_fullscreen(self):
        self.status.set("3 秒后截图全屏，请切换到目标窗口...")
        self.root.iconify()

        def do_capture():
            import time
            time.sleep(2.5)
            img = ImageGrab.grab(all_screens=True)
            # Tk 只能在主线程操作
            self.root.after(0, lambda: (
                self.root.deiconify(), self._scan_image(img)))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_scan_region(self):
        self._on_capture_region()


def main():
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

    root = ctk.CTk()
    QRToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
