"""二维码编码与分片协议（纯逻辑，不依赖 Tk）。"""
import base64
import struct
import zlib

import segno

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
