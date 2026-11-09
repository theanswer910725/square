# -*- coding: utf-8 -*-
"""中文文本二维码回归：用户乱码案例 + 三种策略长文本往返。

覆盖 2026-11 真实 bug：纯中文 UTF-8 单码（无 ECI）被 zbar 按 SJIS 猜测，
扫出来是「蜀ｻ蟷ｲ邊牙､ｧ…」式乱码。修复 = 纯文本单码生成时带 ECI。

直接运行：python tests/test_qr_encoding.py
需要显示环境（GUI 用例会拉起真实窗口）。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyzbar.pyzbar as pyzbar
from PIL import Image

from square.core.codec import decode_strings, encode

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {extra}")


def user_text():
    """复刻用户输入：「冻干粉大富大贵」长/短行交替，含空行"""
    lines = []
    for i in range(22):
        lines.append("冻干粉大富大贵冻干粉大富大贵")
        lines.append("冻干粉大富大贵")
        if i % 4 == 3:
            lines.append("")
    return "\n".join(lines)


def long_cjk():
    """约 3000 字符的中文长文本（必然分片）"""
    return "".join(
        f"第{i:03d}段：方寸打包后分片与还原验证，计入 UTF-8 与中文混排。\n"
        for i in range(1, 90)).rstrip("\n")


def qr_image(qr):
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=8, border=2)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def scan_roundtrip(result):
    """QR 列表 → 逐张渲染 → pyzbar 真实扫码 → decode_strings 还原"""
    strings = []
    for qr in result["qrs"]:
        dec = pyzbar.decode(qr_image(qr))
        assert dec, "生成的二维码无法被 pyzbar 识别"
        strings.append(dec[0].data.decode("utf-8"))
    return decode_strings(strings)


def test_user_text_single():
    """用户乱码文本：自动策略（单码）生成→扫码→还原必须逐字一致"""
    print("[core] 用户文本（冻干粉大富大贵）单码往返")
    text = user_text()
    result = encode(text, error="M")
    check("策略为 single-plain", result["strategy"] == "single-plain",
          f"实际 {result['strategy']}")
    out = scan_roundtrip(result)
    check("还原状态 ok/raw", out["status"] in ("ok", "raw"), out["status"])
    check("还原文本逐字一致", out.get("text") == text,
          repr(out.get("text", "")[:40]))


def test_long_cjk_strategies():
    """中文长文本 × 自动/强制分片/压缩+分片 三策略往返"""
    print("[core] 中文长文本三种策略往返")
    text = long_cjk()
    for name, kw in (("自动", {}),
                     ("强制分片", {"prefer_single": False}),
                     ("压缩+分片", {"compressed": True, "prefer_single": False})):
        result = encode(text, error="M", max_b64_len=1000, **kw)
        out = scan_roundtrip(result)
        check(f"{name}（{result['strategy']}，{len(result['qrs'])} 码）逐字一致",
              out["status"] == "ok" and out["text"] == text,
              f"status={out['status']}")


def test_ascii_unaffected():
    """ECI 不影响原有 ASCII / 混排内容"""
    print("[core] ASCII 与混排回归")
    for text in ("Hello QR", "方寸 exe 打包验证 2026-11-09", "abc123\nXYZ"):
        result = encode(text, error="M")
        out = scan_roundtrip(result)
        check(f"{text[:16]!r} 逐字一致",
              out["status"] in ("ok", "raw") and out["text"] == text)


def test_gui_roundtrip():
    """GUI 层：真实窗口 → 输入用户文本 → 生成 → 对预览拼图 _scan_image → 还原文本一致"""
    print("[gui] 用户文本经真实界面生成→识别往返")
    import customtkinter as ctk
    from square.gui.app import SquareApp

    root = ctk.CTk()
    try:
        from square.gui.app import SquareApp as App
        app = App(root)
        text = user_text()
        app.text_input.insert("1.0", text)
        app._on_generate()
        deadline = time.time() + 60
        while app.gen_result is None and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        check("生成完成", app.gen_result is not None)
        if app.gen_result is None:
            return
        check("生成策略为 single-plain",
              app.gen_result["strategy"] == "single-plain",
              app.gen_result["strategy"])
        outcome = app._scan_image(app.gen_result["preview_image"])
        root.update()
        got = app.scan_text.get("1.0", "end").strip()
        check("GUI 识别返回 ok", outcome == "ok", outcome)
        check("GUI 还原文本逐字一致", got == text.strip(),
              repr(got[:40]))
    finally:
        root.destroy()


if __name__ == "__main__":
    test_user_text_single()
    test_long_cjk_strategies()
    test_ascii_unaffected()
    test_gui_roundtrip()
    print(f"\n{PASS} PASS / {FAIL} FAIL")
    sys.exit(1 if FAIL else 0)
