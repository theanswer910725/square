"""二维码编码与分片协议（纯逻辑，不依赖 Tk）。"""
import base64
import struct
import zlib

import segno

# 帧头版本（第 4 字节）：v2 增加 4 字节整条内容 CRC32，用来识破
# 「不同消息的分片被混在一起」。v1 只读兼容，写出的一律是 v2。
MAGIC = b"QRC\x02"                 # 新格式：17 字节头 → base64 24 字符
MAGIC_LEGACY = b"QRC\x01"          # 旧格式：13 字节头 → base64 20 字符（仅读）
HEADER_SIZE_B64 = 24
HEADER_SIZE_BIN = 17
HEADER_SIZE_B64_LEGACY = 20
HEADER_SIZE_BIN_LEGACY = 13
FLAG_COMPRESSED = 0x01

# 版本 40、byte 模式下的单码容量（字节）。分片载荷是 base64 纯 ASCII，
# 1 个字符正好 1 字节，所以这里可以直接当字符数用
SINGLE_CAPACITY = {"L": 2953, "M": 2331, "Q": 1663, "H": 1273}


class SingleOverflow(Exception):
    """强制单码放不下：带上容量与内容的字节数，便于给出可读提示"""

    def __init__(self, actual, capacity, error):
        self.actual, self.capacity, self.error = actual, capacity, error
        super().__init__(
            f"当前纠错率 {error} 下单码最多 {capacity} 字节，"
            f"当前内容 {actual} 字节，超出 {actual - capacity} 字节")


def _b64e(d): return base64.b64encode(d).decode("ascii")
def _b64d(s): return base64.b64decode(s)


def _make_plain(text, error):
    """纯文本单码：带 ECI（UTF-8）设计符生成。

    不加 ECI 时，扫描端对无标记的字节模式载荷只能靠猜：zbar（pyzbar）
    在载荷「恰好也是合法 SJIS」时按 SJIS 解读，纯中文 UTF-8（如
    「冻干粉大富大贵」）会被转成「蜀ｻ蟷ｲ…」式乱码——乱码在扫描端
    就已经产生，解码侧无法根因性挽回。显式 ECI 26 让两端都按 UTF-8 读。
    分片载荷是 base64 纯 ASCII，不受猜测影响，不需要 ECI。
    """
    return segno.make(text, error=error, micro=False, eci=True)


def single_capacity(error="L"):
    """单码在指定纠错率下的最大字节数（byte 模式，版本 40）"""
    return SINGLE_CAPACITY.get(error, SINGLE_CAPACITY["L"])


def part_capacity_chars(error="L"):
    """一片载荷里能放的数据字符数：单码容量扣掉 24 字符协议帧头"""
    return single_capacity(error) - HEADER_SIZE_B64


def effective_part_limit(max_b64_len, error="L"):
    """每片实际上限 = min(清晰度档位上限, 当前纠错率的单码容量 - 帧头)"""
    return min(max_b64_len, part_capacity_chars(error))


def fits_single(text, error="L"):
    """按内容实际形态（数字/字母/字节模式）判断能否塞进一个码"""
    try:
        # 一律生成标准 QR：Micro QR 不被 pyzbar / zbar 识别，
        # 通用扫码器同样读不出，会把短内容的可用性直接毁掉
        _make_plain(text, error)
        return True
    except segno.encoder.DataOverflowError:
        return False


def encode(text, compressed=False, max_b64_len=1600, error="L",
           prefer_single=True, single_only=False):
    """编码: str → QRCode 列表 + 信息 dict

    prefer_single: 先试纯文本单码（不压缩、不加帧头），放不下再分片
    single_only:   只允许一个码，放不下抛 SingleOverflow
    compressed:    zlib 压缩 UTF-8 字节 → base64 → 带帧头分片（仅本软件可还原）
    """
    info = {"original_bytes": len(text.encode("utf-8"))}

    if single_only:
        try:
            qr = _make_plain(text, error)
        except segno.encoder.DataOverflowError:
            raise SingleOverflow(info["original_bytes"],
                                 single_capacity(error), error) from None
        return {"strategy": "single-plain", "qrs": [qr], "total_parts": 1,
                "compressed": False, "frames_used": 0, **info}

    # 纯文本单码：整段直接编，不加帧头；分片策略会跳过这一步
    if prefer_single and not compressed:
        try:
            qr = _make_plain(text, error)
            return {"strategy": "single-plain", "qrs": [qr], "total_parts": 1,
                    "compressed": False, "frames_used": 0, **info}
        except segno.encoder.DataOverflowError:
            pass  # 塞不下，继续走分片流程

    raw = zlib.compress(text.encode("utf-8")) if compressed else text.encode("utf-8")
    # 校验和覆盖「整条原始内容」（压缩前、base64 前的 UTF-8 字节），
    # 不是单片数据：只有这样 A[0] + B[1:] 这种混拼才会在 assemble 时被查出来
    content = text.encode("utf-8")
    crc = zlib.crc32(content) & 0xFFFFFFFF
    full_b64 = _b64e(raw)
    limit = effective_part_limit(max_b64_len, error)
    data_per_part = limit - HEADER_SIZE_B64
    total = max(1, (len(full_b64) + data_per_part - 1) // data_per_part)

    parts = []
    for i in range(total):
        flags = FLAG_COMPRESSED if compressed else 0
        bin_hdr = (MAGIC + bytes([flags]) + struct.pack(">HH", total, i)
                   + struct.pack(">I", len(raw)) + struct.pack(">I", crc))
        chunk = full_b64[i * data_per_part : (i + 1) * data_per_part]
        parts.append(_b64e(bin_hdr) + chunk)

    qrs = [segno.make(p, error=error, micro=False) for p in parts]
    return {"qrs": qrs, "payloads": parts, "compressed": compressed,
            "total_parts": total, "strategy": "compressed-split" if compressed else "plain-split",
            "frames_used": total, "part_limit": limit, **info}


def _parse_one(s):
    """单个字符串 → 帧 dict；不是帧就返回 None

    先按 v2（24 字符头）试，再按 v1（20 字符头）试，老码保持可读。
    v1 没有 crc 字段（crc=None），读得到就照旧规则还原。
    """
    for size, magic, version, legacy in (
            (HEADER_SIZE_B64, MAGIC, 2, False),
            (HEADER_SIZE_B64_LEGACY, MAGIC_LEGACY, 1, True)):
        try:
            hdr = _b64d(s[:size])
        except Exception:
            continue
        if not hdr.startswith(magic):
            continue
        need = HEADER_SIZE_BIN_LEGACY if legacy else HEADER_SIZE_BIN
        if len(hdr) < need:
            continue
        try:
            total, index = struct.unpack(">HH", hdr[5:9])
            orig_len = struct.unpack(">I", hdr[9:13])[0]
            crc = None if legacy else struct.unpack(">I", hdr[13:17])[0]
        except Exception:
            continue
        return {"version": version, "flags": hdr[4], "total": total,
                "index": index, "orig_len": orig_len, "crc": crc,
                "header_len": size, "b64": s[size:], "payload": s}
    return None


def parse_frames(strings):
    """从解码出的字符串里挑出带协议帧头的分片（v2 与 v1 都认）"""
    frames = []
    for s in strings:
        f = _parse_one(s)
        if f:
            frames.append(f)
    return frames


def _batch_key(f):
    """同一批分片的特征：版本 + 总片数 + 原始长度 + 整条内容 CRC

    crc 是关键：两条字节数恰好相同的不同消息，靠它才能分成两批，
    不会在 by_index 里互相覆盖。
    """
    return (f.get("version", 1), f["total"], f["orig_len"], f.get("crc"))


def assemble_frames(frames):
    """按片号索引重组（帧可以来自不同次截图/不同图片）

    混入其他消息的分片时：按片数最多的那批继续，缺片照常报 partial；
    即使凑齐了，CRC 校验也会把「内容对不上」的拼装拒掉。
    """
    if not frames:
        return {"status": "empty"}

    groups = {}
    for f in frames:
        groups.setdefault(_batch_key(f), []).append(f)
    # 片数最多的那一批为主，同数量取最先出现的；其余批次视为误入
    group = max(groups.values(), key=len)
    total = group[0]["total"]
    compressed = bool(group[0]["flags"] & FLAG_COMPRESSED)
    crc = group[0].get("crc")

    by_index = {}
    for f in group:
        if 0 <= f["index"] < total:
            by_index[f["index"]] = f

    missing = [i for i in range(total) if i not in by_index]
    mixed = len(groups) > 1
    if missing:
        out = {"status": "partial", "total": total, "have": len(by_index),
               "missing": missing}
        if mixed:
            out["reason"] = "混入了其他内容的分片"
        return out

    full_b64 = "".join(by_index[i]["b64"] for i in range(total))
    try:
        raw = _b64d(full_b64)
        content = zlib.decompress(raw) if compressed else raw
    except Exception:
        return {"status": "partial", "total": total, "have": len(by_index),
                "missing": [], "reason": "内容损坏：base64 或解压失败"}

    if crc is not None and (zlib.crc32(content) & 0xFFFFFFFF) != crc:
        return {"status": "partial", "total": total, "have": len(by_index),
                "missing": [], "reason": "内容校验不通过：分片来自不同消息"}
    try:
        return {"status": "ok", "text": content.decode("utf-8")}
    except Exception:
        return {"status": "partial", "total": total, "have": len(by_index),
                "missing": [], "reason": "内容损坏：不是合法的 UTF-8 文本"}


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
