"""密集拼接图的二次识别（纯逻辑，不依赖 Tk）。"""
import numpy as np
from PIL import Image, ImageFilter, ImageOps


def as_text(data):
    """二维码原始字节 → 文本：优先 UTF-8，失败退回 latin-1。"""
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
                s = as_text(r.data)
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
