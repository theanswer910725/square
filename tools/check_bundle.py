"""
Author: Lin。
Date: 2026-11-10 18:32:53

构建后自检：读 PyInstaller 的 Analysis TOC，断言 Win7 包里没有 Win8+ 才有的
API set / UCRT，并且该带的东西都在。任何一项不满足即退出码 1。

用法：
    python tools/check_bundle.py build/Square-Win7/Analysis-00.toc
"""
import os
import re
import struct
import sys

BANNED_EXACT = ("ucrtbase.dll",)
BANNED_PREFIX = ("api-ms-win-",)
REQUIRED = ("python38.dll", "tcl86t.dll", "tk86t.dll", "libiconv.dll",
            "msvcr120.dll", "vcruntime140.dll")


def read_toc(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def pe_machine(exe_path):
    """返回 exe 的机器类型：0x14c=x86，0x8664=x64"""
    with open(exe_path, "rb") as f:
        data = f.read(4096)
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    return struct.unpack_from("<H", data, e_lfanew + 4)[0]


def main(toc_path):
    errors = []
    text = read_toc(toc_path)
    lowered = text.lower()

    for name in BANNED_EXACT:
        if name in lowered:
            errors.append(f"包内出现 {name}：应由目标机 OS 提供")
    for prefix in BANNED_PREFIX:
        hits = sorted(set(re.findall(r"[\w.\-]*" + re.escape(prefix) + r"[\w.\-]*\.dll", lowered)))
        if hits:
            errors.append("包内出现 Win8+ API set：" + ", ".join(hits))

    for name in REQUIRED:
        if name not in lowered:
            errors.append(f"缺少必需文件 {name}")

    zbar = re.findall(r"libzbar-(32|64)\.dll", lowered)
    print(f"TOC: {toc_path}")
    print(f"  libzbar 位宽: {sorted(set(zbar)) or '未找到'}")
    print(f"  python 运行时: {'python38.dll' if 'python38.dll' in lowered else '未找到 python38.dll'}")

    # toc 位于 <root>/build/<name>/Analysis-00.toc，往上三级才是仓库根
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(toc_path))))
    exe = os.path.join(root, "dist", "Square-Win7.exe")
    if os.path.exists(exe):
        machine = pe_machine(exe)
        arch = {0x14C: "x86 (32 位)", 0x8664: "x64 (64 位)"}.get(machine, hex(machine))
        print(f"  产物架构: {arch}")
        if zbar:
            expected = "64" if machine == 0x8664 else "32"
            if expected not in set(zbar):
                errors.append(f"产物架构与 libzbar 位宽不匹配：exe {arch}，libzbar-{zbar[0]}")
    else:
        # 路径算错时不能静默跳过这项检查
        errors.append(f"找不到产物 {exe}，无法校验架构一致性")

    if errors:
        print("\n自检失败：")
        for e in errors:
            print("  - " + e)
        return 1
    print("自检通过")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python tools/check_bundle.py <Analysis-00.toc>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
