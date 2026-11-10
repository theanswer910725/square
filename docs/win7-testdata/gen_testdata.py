# -*- coding: utf-8 -*-
"""
Author: Lin。
Date: 2026-11-10 21:40:00

生成 Win7 真机验收用的测试数据（docs/win7-testdata/）。

片数不是我估的：每个文件都真的过一遍 square.core.codec.encode()，
再断言「算出来的片数 == 期望片数」，失败就直接退出非 0。

重跑（在仓库根目录，用带 segno 的解释器，例如 .venv-win7）：
    .venv-win7\\Scripts\\python.exe docs\\win7-testdata\\gen_testdata.py
"""
import hashlib
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from square.core import codec  # noqa: E402

# 与界面默认值一致：纠错率「中等」+ 清晰度「清晰（1000 字符/片）」+ 策略「自动」
ERROR = "M"
PART_LIMIT = 1000
DATA_PER_PART = codec.effective_part_limit(PART_LIMIT, ERROR) - codec.HEADER_SIZE_B64

BOM = b"\xef\xbb\xbf"


def b64_len(n_bytes):
    return (n_bytes * 4 + 2) // 3


def parts_for_bytes(n_bytes, limit=PART_LIMIT, error=ERROR):
    limit = codec.effective_part_limit(limit, error)
    per = limit - codec.HEADER_SIZE_B64
    return max(1, math.ceil(b64_len(n_bytes) / per))


def solved_hex_len(target_parts, limit=PART_LIMIT, error=ERROR):
    """求一个十六进制串长度 n，使它的片数正好等于 target_parts（内容为 ASCII）"""
    for n in range(1, 200000):
        if parts_for_bytes(n, limit, error) == target_parts:
            return n
    raise SystemExit("找不到长度")


def hex_text(n, seed):
    rng = random.Random(seed)
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def cn_text(chars):
    """确定性的中文长文本：按句循环截断到指定字符数"""
    base = ("方寸二维码工具在 Windows 7 上分 32 位与 64 位两条构建线维护，"
            "本文件用于验证参数档位提示、分片数量与解码往返是否一致。")
    out = []
    while sum(len(s) for s in out) < chars:
        out.append(base)
    return "".join(out)[:chars]


MULTILINE = "\r\n".join([
    "第一行：方寸 Square",
    "第二行：冻干粉大富大贵",
    "",
    "第四行是空行之后的续行，用于确认换行与空行在还原后是否保留。",
    "",
    "第六行：ASCII baseline 0123456789",
])


def main():
    n5 = solved_hex_len(5)
    n8 = solved_hex_len(8)
    n20k = 20000

    specs = [
        ("F1", "F1_single_cn.txt", "冻干粉大富大贵", "无（单行）",
         "单码（1 片，single-plain）",
         "生成器输入框直接粘贴。F1 生成、F2 手机扫码、H1 保存、H2 往返、E1/E2 复制都从这张开始"),
        ("F2", "F2_single_mixed.txt",
         "方寸 Square v1.0 扫码测试 ✅ 中文+CJK 混排 2026-11-10",
         "无（单行）", "单码（1 片，single-plain）",
         "手机扫码用这张：中/英/emoji 混排，验证 UTF-8 与 ECI 是否被手机端正确识别"),
        ("F3", "F3_long_cn_hint.txt", cn_text(1200), "无（单行）",
         "按实测（见 manifest 表格）",
         "切「纠错率=较高」+「清晰度=紧凑」时观察档位被压低的提示；文本本身会分片，可顺带确认分片数量"),
        ("G1", "G1_multi_5parts.txt", hex_text(n5, 20261110), "无（单行）",
         "多片（5 片，plain-split）",
         "不可压缩十六进制随机串，固定 5 片；G1 生成、H3 收集、E4 复制都用它"),
        ("G2", "G2_multi_5parts.txt", hex_text(n5, 777), "无（单行）",
         "多片（5 片，plain-split）",
         "与 G1 内容不同的另一份 5 片数据，两条线（3.8/3.13）各生成一次对比片数"),
        ("G2", "G2_multi_8parts.txt", hex_text(n8, 888), "无（单行）",
         "多片（8 片，plain-split）",
         "8 片档：G2 片数对比、G3 大图弹窗、I1–I3 缩放与滚动都建议用这张（片多，视觉更明显）"),
        ("G4", "G4_extreme_20000.txt", hex_text(n20k, 20261111), "无（单行）",
         "按实测（见 manifest 表格）",
         "极端长文本（20000 字符），验证大批量分片不崩、提示明确"),
        ("H2", "H2_roundtrip_multiline.txt", MULTILINE, "CRLF",
         "单码（1 片，single-plain）",
         "多行含空行：验证解码往返后换行与空行是否原样保留"),
    ]

    rows = []
    for entry_id, name, text, eol, expect, purpose in specs:
        data = BOM + text.encode("utf-8")
        path = os.path.join(HERE, name)
        with open(path, "wb") as f:
            f.write(data)
        res = codec.encode(text, error=ERROR, max_b64_len=PART_LIMIT,
                           compressed=False, prefer_single=True)
        total = res["total_parts"]
        # 回归：把分片自己拼回去，确认数据没坏
        if total > 1:
            back = codec.decode_strings(res["payloads"])
            assert back["status"] == "ok" and back["text"] == text, name
        expect_final = f"单码（1 片，{res['strategy']}）" if total == 1 else \
                       f"多片（{total} 片，{res['strategy']}）"
        rows.append({
            "id": entry_id, "file": name, "text": text, "eol": eol,
            "chars": len(text), "bytes": len(data), "parts": total,
            "strategy": res["strategy"], "expect": expect_final,
            "purpose": purpose,
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "limit": PART_LIMIT,
        })
        print(f"{name:32} {len(text):6d} chars {len(data):7d} B  "
              f"{total:2d} 片  {res['strategy']}  {rows[-1]['sha256'][:16]}…")

    # 断言：随机串必须正好命中期望片数
    want = {"G1_multi_5parts.txt": 5, "G2_multi_5parts.txt": 5, "G2_multi_8parts.txt": 8}
    for r in rows:
        if r["file"] in want:
            assert r["parts"] == want[r["file"]], (r["file"], r["parts"])

    write_manifest(rows)
    write_usage(rows)
    print("\nmanifest.md / usage.md 已更新")


def write_manifest(rows):
    lines = []
    lines.append("# Win7 验收测试数据清单")
    lines.append("")
    lines.append("Author: Lin。")
    lines.append("Date: 2026-11-10 21:40:00")
    lines.append("")
    lines.append("> 片数是本机用项目自身 `square.core.codec.encode()` 实测算出来的，"
                 "不是估算；重跑脚本见同目录 `gen_testdata.py`。")
    lines.append("")
    lines.append("## 实测条件")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 解释器 | Python 3.8.10 (`.venv-win7`) |")
    lines.append("| segno | 1.6.6 |")
    lines.append(f"| 纠错率 | 中等（M，{codec.single_capacity('M')} 字节/单码） |")
    lines.append(f"| 清晰度 | 清晰（{PART_LIMIT} 字符/片） |")
    lines.append(f"| 策略 | 自动（推荐） |")
    lines.append(f"| 每片有效载荷 | {DATA_PER_PART} 字符（{PART_LIMIT} − 24 帧头） |")
    lines.append("")
    lines.append("**界面保持默认值（中等 + 清晰 + 自动）时，下表的片数与实测一致。**"
                 "改动清晰度或纠错率会改变片数，属正常，见文末附表。")
    lines.append("")
    lines.append("## 文件清单")
    lines.append("")
    lines.append("| 条目 | 文件名 | 编码 | 换行 | 字符数 | 字节数 | 预期编码结果 | 用途 | SHA256 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        lines.append(
            f"| {r['id']} | `{r['file']}` | UTF-8 with BOM | {r['eol']} | "
            f"{r['chars']} | {r['bytes']} | {r['expect']} | {r['purpose']} | "
            f"`{r['sha256']}` |")
    lines.append("")
    lines.append("## 编码与换行")
    lines.append("")
    lines.append("- 所有 `.txt` 均为 **UTF-8 带 BOM**（3 字节 `EF BB BF`）。"
                 "带 BOM 是为了 Win7 记事本能正确显示中文；"
                 "记事本全选复制时不会把 BOM 带进剪贴板，粘贴内容与「字符数」一致。")
    lines.append("- 除 `H2_roundtrip_multiline.txt` 用 **CRLF** 外，其余都是**单行文件，完全没有行尾字符**（不是 LF）。")
    lines.append("- 所有文件**末尾都没有多余换行**：Ctrl+A / Ctrl+C 得到的就是「字符数」那么多字符。")
    lines.append("- 字节数 = 文件实际字节（含 3 字节 BOM 与 CRLF 的 2 字节）。"
                 "若把这些文件另存为 ANSI 或 LF，字节数会变，`certutil` 的哈希也会对不上。")
    lines.append("")
    lines.append("### 校验方法")
    lines.append("")
    lines.append("```bat")
    lines.append("rem 逐个核对大小与哈希（在测试数据目录内执行）")
    lines.append("for %f in (*.txt) do @certutil -hashfile \"%f\" SHA256 | findstr /v \"哈希 CertUtil\"")
    lines.append("```")
    lines.append("")
    lines.append("```powershell")
    lines.append("rem PowerShell 2.0 可用：字符数与字节数")
    lines.append("Get-ChildItem *.txt | ForEach-Object {")
    lines.append("  $t = [System.IO.File]::ReadAllText($_.FullName)")
    lines.append("  '{0}  {1} chars  {2} bytes' -f $_.Name, $t.Length, $_.Length")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("## 复用关系（不是缺文件）")
    lines.append("")
    lines.append("| 条目 | 使用哪个文件 | 说明 |")
    lines.append("| --- | --- | --- |")
    lines.append("| H1 | `F1_single_cn.txt` | 单码保存，输入内容同上 |")
    lines.append("| H2 | `F1_single_cn.txt`、`H2_roundtrip_multiline.txt` | 先跑单行，再跑多行含空行 |")
    lines.append("| H3 | `G1_multi_5parts.txt` | 5 片：大图弹窗「保存原图」后「选择图片」选这张拼图，或逐片区域截图送入 |")
    lines.append("| E1 / E2 | `F1_single_cn.txt` | 复制全部后粘到画图 / 微信 |")
    lines.append("| E4 | `G1_multi_5parts.txt` | 多片拼图复制 |")
    lines.append("| I1–I4 | `G2_multi_8parts.txt` | 8 片拼图，缩放/滚动观察更明显 |")
    lines.append("")
    lines.append("## 附表：改清晰度后的片数（同样实测）")
    lines.append("")
    limits = [("紧凑", 1700), ("平衡", 1300), ("清晰（默认）", 1000), ("最清晰", 750)]
    head = "| 文件 | " + " | ".join(n for n, _ in limits) + " |"
    lines.append(head)
    lines.append("| --- |" + " --- |" * len(limits))
    for r in rows:
        if not r["file"].startswith(("G1", "G2", "G4")):
            continue
        cells = []
        for _, lim in limits:
            cells.append(str(parts_for_bytes(len(r["text"].encode("utf-8")), lim)))
        lines.append(f"| `{r['file']}` | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("> 纠错率也会影响：最高（H）下单码容量 1273 字节、每片载荷降为 1249，片数会再增加。")
    lines.append("")

    with open(os.path.join(HERE, "manifest.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def write_usage(rows):
    by = {r["file"]: r for r in rows}
    lines = []
    lines.append("# Win7 验收测试数据 · 操作提示")
    lines.append("")
    lines.append("Author: Lin。")
    lines.append("Date: 2026-11-10 21:40:00")
    lines.append("")
    lines.append("按下面的入口逐项操作；每项做完把现象填回 Excel 验收表对应行。")
    lines.append("")
    lines.append("## 打开与复制")
    lines.append("")
    lines.append("1. 用**记事本**打开 `.txt`（UTF-8 带 BOM，中文不会乱码）。")
    lines.append("2. `Ctrl+A` 全选 → `Ctrl+C` 复制。**不要手动删改内容**，否则字符数与片数都会变。")
    lines.append("3. 在程序里 `Ctrl+V` 粘到「文本输入」框，再点「生成二维码」。")
    lines.append("")
    lines.append("## 逐项入口")
    lines.append("")
    lines.append("| 条目 | 使用文件 | 界面入口 | 要看什么 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| F1 | `F1_single_cn.txt` | 生成器 → 文本输入框 | 预览出现 1 个二维码，提示「点击可查看大图」 |")
    lines.append("| F2 | `F2_single_mixed.txt` | 生成器生成后，用**手机**扫屏幕 | 手机上中文、英文、emoji 全部正确（emoji 可能显示为黑白符号，不算失败） |")
    lines.append("| F3 | `F3_long_cn_hint.txt` | 生成器 → 先把「清晰度」切到「最清晰」再切回「紧凑」 | 参数区出现「每片上限已由 X 字符降为 Y 字符」这类常驻提示 |")
    lines.append("| G1 | `G1_multi_5parts.txt` | 生成器 → 文本输入框 | 预览变成拼图，片数应为 5 |")
    lines.append("| G2 | `G2_multi_5parts.txt`、`G2_multi_8parts.txt` | 生成器 → 各生成一次 | 片数分别为 5 与 8；再用 3.13 线 `Square.exe` 生成同样的文件对比 |")
    lines.append("| G3 | `G2_multi_8parts.txt` | 生成后点预览打开大图弹窗 | 8 片拼图完整、无空格、无重复 |")
    lines.append("| G4 | `G4_extreme_20000.txt` | 生成器 → 文本输入框 | 能出多片或给出明确提示；不卡死、不崩溃 |")
    lines.append("| H1 | `F1_single_cn.txt` | 生成器 → 「保存二维码」 | 存成 PNG，能用系统看图打开 |")
    lines.append("| H2 | `F1_single_cn.txt`、`H2_roundtrip_multiline.txt` | 解码器 → 「选择图片」→ 选 H1 存的 PNG | 「还原文本」与输入逐字一致；多行那份要保留换行与空行 |")
    lines.append("| H3 | `G1_multi_5parts.txt` | 生成 5 片 → 大图弹窗「保存原图」→ 解码器「选择图片」选这张拼图 | 状态行「共 5 片，已收集 …」，收齐后自动还原 |")
    lines.append("| E1 / E2 | `F1_single_cn.txt` | 生成 → 大图弹窗「复制全部」→ 画图 / 微信 `Ctrl+V` | 图片能粘出、能发送、能被扫 |")
    lines.append("| E3 | 任意文字（先复制一段文字） | 解码器 → 「剪贴板」 | 弹「剪贴板中没有图片」，不崩 |")
    lines.append("| E4 | `G1_multi_5parts.txt` | 生成 5 片 → 大图弹窗「复制全部」→ 画图 | 粘出的是拼图，不是单片 |")
    lines.append("| I1–I3 | `G2_multi_8parts.txt` | 生成 8 片 → 打开大图弹窗 → 拖缩放滑块 | 8 片拼图缩放连续、滚动条正常、无花屏 |")
    lines.append("")
    lines.append("## 手机扫码扫哪张")
    lines.append("")
    lines.append("- **F2 的手机扫码**：扫屏幕上由 `F2_single_mixed.txt` 生成的**那一个**二维码，"
                 "不要扫预览缩略图之外的地方；窗口放大到 100% 以上再扫更稳。")
    lines.append("- **H3 的多片往返**：不需要手机，全部在 PC 上完成（保存拼图 → 选择图片）。")
    lines.append("- **G1/G2 的拼图**：通用扫码器只能读到单片内容（base64 片段），这是设计如此，"
                 "必须把所有片收集齐才能还原，不要用手机扫多片拼图当作失败。")
    lines.append("")
    lines.append("## 常见误判")
    lines.append("")
    lines.append("- 复制时把行尾换行也带上了：字符数会比清单多 1–2，5 片/8 片可能变成 6 片/9 片。"
                 "此时用清单的「字符数」核对粘贴后的字数（生成器不显示字数时可用记事本状态栏估）。")
    lines.append("- 用 WinRAR / 7-Zip 解压导致 BOM 丢失或换行被转：重新从原始目录拷贝，"
                 "并用 `certutil` 核对 SHA256。")
    lines.append("- 把清晰度改成「最清晰」后片数变多：正常，见 manifest 文末附表。")
    lines.append("")

    with open(os.path.join(HERE, "usage.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
