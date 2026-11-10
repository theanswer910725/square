# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows 7 兼容线）：onefile、无控制台。

与 square.spec 的差异只有三处，务必保持同步：
1. 二进制白名单：剔除只在 Win8+ 存在的 api-ms-win-* 与 ucrtbase.dll，
   防止像 3.13 线那样把构建机 PATH 上第三方软件的 UCRT 抓进包里；
2. libzbar 按解释器位宽取 64/32 位（Win7 线允许用 32 位 Python 构建）；
3. 产物名 Square-Win7，避免与现代化线产物混淆。

用法（在仓库根目录执行，解释器必须是 Python 3.8）：
    build_win7.bat
或：
    <python3.8> -m PyInstaller --noconfirm square-win7.spec
产物：dist/Square-Win7.exe
"""
import os
import struct

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

APP_NAME = "Square-Win7"
ROOT = os.path.abspath(os.getcwd())

IS_64BIT = struct.calcsize("P") == 8

# ---- 运行期数据文件 ----
datas = collect_data_files("customtkinter")

ICON = os.path.join(ROOT, "square", "gui", "assets", "CustomTkinter_icon_Windows.ico")
datas.append((ICON, os.path.join("square", "gui", "assets")))

# ---- 运行期二进制 ----
# pyzbar 只带了与安装位宽一致的 zbar DLL：64 位是 libzbar-64.dll，32 位是
# libzbar-32.dll，两者都依赖 libiconv.dll，且 libzbar 还静态依赖 MSVCR120.dll
_, pyzbar_dir = get_package_paths("pyzbar")
ZBAR = "libzbar-64.dll" if IS_64BIT else "libzbar-32.dll"
for name in (ZBAR, "libiconv.dll"):
    if not os.path.exists(os.path.join(pyzbar_dir, name)):
        raise SystemExit(
            f"缺少 {name}：pyzbar 安装位宽与当前解释器不一致（解释器 {64 if IS_64BIT else 32} 位）")
binaries = [(os.path.join(pyzbar_dir, name), "pyzbar")
            for name in (ZBAR, "libiconv.dll")]

hiddenimports = [
    "pyzbar.pyzbar",          # ctypes 方式加载，静态分析看不到
]

excludes = [
    "PIL.AvifImagePlugin",
    "PIL.ImageCms",
    "ssl",
    "_ssl",
    "_hashlib",               # 本地工具不联网
    "setuptools",
    "pkg_resources",
]

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# 目标机 OS 提供的组件绝不随包：api-ms-win-* 是 Win8 起才有的 API set（Win7 上没有，
# 且在 Win7 上无法加载），ucrtbase.dll 必须来自目标机（Win7 SP1 + KB2999226）。
# 构建机 PATH 里若存在第三方软件自带的 UCRT（如 TortoiseGit\bin），bindepend 会
# 无条件把它们收进来，这里按名字统一剔除。
_BANNED_EXACT = {"ucrtbase.dll"}
_BANNED_PREFIX = ("api-ms-win-",)
a.binaries = [
    b for b in a.binaries
    if b[0].lower() not in _BANNED_EXACT
    and not b[0].lower().startswith(_BANNED_PREFIX)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
