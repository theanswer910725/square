# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onefile、无控制台、图标取自 square/gui/assets。

用法（在仓库根目录执行）：
    python -m PyInstaller --noconfirm square.spec
产物：dist/Square.exe
"""
import os

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

APP_NAME = "Square"
ROOT = os.path.abspath(os.getcwd())

# ---- 运行期数据文件 ----
# CustomTkinter 的主题 json、字体与图标是运行时按路径读的，不 collect 会白屏或崩
datas = collect_data_files("customtkinter")

# 窗口图标：widgets.py 用 Path(__file__).with_name("assets") 定位，
# 冻结后 __file__ 在 _MEIPASS/square/gui/ 下，所以目标目录必须是 square/gui/assets
ICON = os.path.join(ROOT, "square", "gui", "assets", "CustomTkinter_icon_Windows.ico")
datas.append((ICON, os.path.join("square", "gui", "assets")))

# ---- 运行期二进制 ----
# pyzbar 用 ctypes 在自己的包目录里找这两个 DLL：
#   libzbar-64.dll 依赖 libiconv.dll；两者都不在系统 PATH 里，必须随包走。
# 注意 libzbar-64.dll 还依赖 MSVCR120.dll（VC++ 2013 运行库），那是目标机
# 前置条件，不打包系统 DLL。
# get_package_paths 返回 (package_base, package_dir)：这里要包目录本身，
# 用 pkg_base 会拼到 site-packages 根上，PyInstaller 直接报找不到 DLL
_, pyzbar_dir = get_package_paths("pyzbar")
binaries = [(os.path.join(pyzbar_dir, name), "pyzbar")
            for name in ("libzbar-64.dll", "libiconv.dll")]

hiddenimports = [
    "pyzbar.pyzbar",          # ctypes 方式加载，静态分析看不到
]

# 排除项见 README「打包」一节：每一项都经过启动、生成、保存、两条解码路径
# 与截图识别的回归确认；去掉任何一条都会让体积回涨
excludes = [
    "PIL.AvifImagePlugin",    # 界面不提供 avif
    "PIL.ImageCms",           # 未使用色彩管理
    "ssl",
    "_ssl",
    "_hashlib",               # 本地工具不联网，它是 libcrypto-3.dll 的来源
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
    upx=False,                       # 不使用加壳，避免误报
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                   # 带窗口，无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
