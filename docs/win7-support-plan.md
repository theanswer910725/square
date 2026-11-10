# Windows 7 支持方案（双构建线）

Author: Lin。
Date: 2026-11-10 18:32:53

> 状态：方案已定稿，代码骨架已落地（未提交、未推送、未在 Win7 真机验证）。
> 本文档是评审基线，实施结果与偏差回写到文末「实施状态」。

## 1. 背景：Win7 上报的两个错误

| 截图 | 原文 | 失败阶段 |
| --- | --- | --- |
| 1 | `<Square.exe - 系统错误>` 无法启动此程序，因为计算机中丢失 `api-ms-win-core-path-l1-1-0.dll` | 系统加载器 / `CreateProcess` |
| 2 | `Failed to load Python DLL '...\_MEI000017cc2\python313.dll'. LoadLibrary: 找不到指定的模块。` | PyInstaller 引导器解包后 `LoadLibrary` |

根因（已用 PE 导入表取证）：

- Python 3.13 的 `python313.dll` 静态依赖 `api-ms-win-core-path-l1-1-0.dll`。该 API set 自 Windows 8 起才存在，Win7 没有，也不存在可安装补丁；从别人机器复制同名 DLL 也不可靠。
- 官方口径：Python 3.13 支持 Windows 8.1 及以上，「需要 Windows 7 支持请安装 Python 3.8」。
- 因此这两条报错属于「目标系统不受支持」，不是装 VC++ 运行库或 KB2999226 能解决的。
- 截图 1 与当前 `dist/Square.exe` 的导入表不符（当前产物只导入 KERNEL32/USER32/GDI32/ADVAPI32/COMCTL32，无该 DLL，字符串命中 0 次），判断为另一份构建/更早产物所产生；不影响结论。

结论：支持 Win7 只能换运行时（降 Python），因此采用**双构建线**。

## 2. 运行时来源

### 2.1 评估过的候选

| 候选 | 结论 |
| --- | --- |
| `D:\IPA\PJ-IPAStudio_Windows_Professional\...\python38.exe`（用户指定） | **可用但仅限可行性验证**：Python 3.8.8、**32 位**、带 tkinter/pip/venv/sqlite3、DLL 只依赖 `VCRUNTIME140` + `api-ms-win-crt-*`（Win7 SP1 + KB2999226 可满足）。问题：32 位产物、位于第三方商业软件私有目录、`sys.path` 混入 `..\executor` 与其他包，构建不可复现 |
| 官方 `python-3.8.10-amd64.exe` 装到 `E:\Python38` | **推荐的发布基线**：64 位、与现有产物架构一致、路径自有、可复现。需用户批准安装（尚未安装） |

### 2.2 已做的只读验证（对 `python38.exe`）

- `-VV`：`Python 3.8.8 (tags/v3.8.8:024d805, Feb 19 2021) [MSC v.1928 32 bit (Intel)]`
- 目录形态：完整发行版（`Lib/`、`DLLs/`、`tcl/`、`include/`、`libs/`、`Scripts/`、`python38.dll`、`vcruntime140.dll`）；存在 `python38._pth` 且内容含 `import site`
- 模块：`tkinter`、`_tkinter`、`pip 20.2.3`、`venv`、`ensurepip`、`sqlite3`、`ssl`、`ctypes`、`zlib`、`bz2`、`lzma` 全部可用
- `sys.prefix` = `sys.base_prefix` = 该第三方目录
- venv：在 `%TEMP%` 下 `-B -m venv --without-pip` 实测成功，venv 内 `import tkinter` 正常；**未在该第三方目录内建 venv，未写入任何文件**
- 32 位依赖可得性：PyPI 上 `numpy-1.24.4-cp38-cp38-win32.whl`、`pillow-10.4.0-cp38-cp38-win32.whl`、`pyzbar-0.1.9-py2.py3-none-win32.whl` 均存在

### 2.3 使用规则

- venv 只建在项目内或任意自有目录，**绝不写第三方软件目录**；创建时带 `-B` 避免生成 `__pycache__`。
- 用该 32 位解释器出的包是 32 位；`square-win7.spec` 已按解释器位宽自动选 `libzbar-32.dll` / `libzbar-64.dll`。
- 正式发布仍建议 64 位官方 3.8.10；32 位产物是否需要保留，等真机验证后再定。

## 3. 依赖版本矩阵

| 组件 | 3.13 线（`requirements.txt`） | Win7 线（`requirements-win7.txt`） | 依据 |
| --- | --- | --- | --- |
| Python | 3.13.8 | 3.8.10（推荐）/ 3.8.8（现有 32 位） | 3.9 起不支持 Win7；3.8 已 EOL（2024-10） |
| customtkinter | 6.0.0 | 6.0.0 | 同版本避免 UI 分叉；`Requires-Python>=3.7`；shcore 问题用运行时 shim 解决 |
| pillow | 12.0.0 | 10.4.0 | 11.x 起要求 Python≥3.9；10.4.0 是最后支持 3.8 的版本 |
| numpy | 2.2.6 | 1.24.4 | 1.25 起要求 Python≥3.9；1.24.4 是最后一个有 cp38 轮子的版本 |
| segno | 1.6.6 | 1.6.6 | 纯 Python，同版本保证二维码位图可逐字节比对 |
| pyzbar | 0.1.9 | 0.1.9 | 同版本，`libzbar` / `libiconv` 完全一致，解码行为不分叉 |
| PyInstaller | 6.22.2 | 5.13.2 | 5.x 末版，bootloader 只导入经典系统 DLL；6.x 对新系统假设更多 |
| pyinstaller-hooks-contrib | 2026.7（隐式） | 2023.10 | 与 5.13.2 同期，避免 hook 反向要求新接口 |

> 两条线都改为精确 pin：本次问题的诱因之一就是 `customtkinter>=5.2.2` 解析到了 6.0.0。

## 4. CustomTkinter 的 shcore 硬依赖

问题：`customtkinter 6.0.0` 的 `ScalingTracker.activate_high_dpi_awareness()` 无条件调用
`ctypes.windll.shcore.SetProcessDpiAwareness(2)`，`get_window_dpi_scaling()` 调用
`shcore.GetDpiForMonitor`。Win7 无 `shcore.dll`，创建 `CTk()` 时直接抛 `OSError`。

| 方案 | 取舍 |
| --- | --- |
| 降 CTk 到 5.2.2 | 5.2.2 同样是无条件 shcore 调用，**解决不了**，还引入 UI 分叉 |
| `ctk.deactivate_automatic_dpi_awareness()` | 不崩，但 `get_window_dpi_scaling()` 恒为 1，CTk 不再按 DPI 缩放，120 DPI 下界面偏小 |
| **运行时 shim（已采用）** | 依赖 CTk 私有类路径，升级 CTk 可能失效；用断言 + 真机验证兜住 |

已落地：`square/gui/dpi.py` 的 `patch_ctk_scaling()`，在 `app.py:run()` 里于 `ctk.CTk()` 之前调用；
当 `shcore` 不存在时，把 `activate_high_dpi_awareness` 置为空操作、`get_window_dpi_scaling` 换成
`gdi32.GetDeviceCaps(LOGPIXELSX)/96`。

风险控制：如果将来 CTk 改了内部路径，`patch_ctk_scaling()` 会抛 `ImportError`，
`build_win7.bat` 的依赖检查与 Win7 真机启动验证都会暴露；不要静默降级。

## 5. DPI 兼容层

`apply_dpi_awareness()` 三级回退（顺序不可调换）：

1. `user32.SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` — Win10 1703+
2. `shcore.SetProcessDpiAwareness(2)` — Win8.1+
3. `user32.SetProcessDPIAware()` — Vista+，**Win7 唯一可用**

返回命中级别的字符串，便于日志与问题定位。

`capture.py` 的影响评估：

- `tk_to_phys_scale()` 用 `winfo_screenwidth` 与 `GetSystemMetrics(0)` 的比值，system-DPI-aware 下两者相等、返回 1，无需改代码；
- 虚拟桌面矩形用的 `GetSystemMetrics(76..79)`、`MonitorFromPoint`、`GetMonitorInfoW` 均为 Vista+ API，Win7 可用；
- 真正需要真机确认的是**行为**：Win7 不支持 per-monitor DPI，多屏不同缩放时系统按主屏统一缩放，`ImageGrab.grab(all_screens=True)` 的坐标域是否与 `GetSystemMetrics` 一致，必须在 Win7 上重跑「遮罩位置 / 框选尺寸 / 跨屏 / 负坐标」四项。
- 预计代码改动 0～10 行，视真机结果决定是否需要按 DPI 级别分支。

## 6. 打包分离

新增文件：

- `square-win7.spec`：与 `square.spec` 的差异仅三处——二进制白名单、libzbar 按位宽选择、产物名 `Square-Win7.exe`；
- `build_win7.bat`：解释器优先级 `参数 > .venv-win7 > 已知 3.8 路径`；**PATH 只保留系统目录 + 解释器目录**，从源头断掉 bindepend 命中第三方目录；
- `tools/check_bundle.py`：构建后读 `Analysis-00.toc` 断言。

白名单写法（`square-win7.spec` 内，`Analysis` 之后、`EXE` 之前）：

```python
_BANNED_EXACT = {"ucrtbase.dll"}
_BANNED_PREFIX = ("api-ms-win-",)
a.binaries = [b for b in a.binaries
              if b[0].lower() not in _BANNED_EXACT
              and not b[0].lower().startswith(_BANNED_PREFIX)]
```

自检断言（`tools/check_bundle.py`）：

- 不得出现 `ucrtbase.dll`、任何 `api-ms-win-*.dll`；
- 必须含 `python38.dll`、`tcl86t.dll`、`tk86t.dll`、`libiconv.dll`、`MSVCR120.dll`、`VCRUNTIME140.dll`；
- 产物 exe 的 PE 机器类型必须与 `libzbar-32/64` 一致。

README 的改动口径：

- 「直接下载使用」区分两个资产：`Square.exe`（Win10/11 x64）与 `Square-Win7.exe`（Win7 SP1 x64，需 KB2999226；32 位产物也可在 Win7 x86 运行）；
- 明确 Win7 线基于已 EOL 的 Python 3.8，仅作兼容维护；
- 修正「`MSVCR120.dll` 不随包分发」的不实表述：3.13 线实际已由 bindepend 从构建机 `system32` 收进包内。

## 7. 回归与验证策略

可自动（两条线都跑）：

1. `pytest tests/`；
2. **双线位图一致性**：同一字符串在 3.8/3.13 下编码 + 分片，PNG 应逐字节相同（segno/pyzbar 同版本，不一致即说明依赖漂移）；
3. `tools/check_bundle.py` 的 TOC 断言；
4. exe 冒烟：Win11 上启动 `Square-Win7.exe`，进程存活且出现主窗口。

必须真机（Win7 SP1 x64，120 DPI 优先）：启动 / 生成 6–8 片 / 预览片号与缩放 / 区域截图识别 / 跨屏截图 / 剪贴板 CF_DIB / 保存原图 / 任务栏图标 / CTk 缩放不裁切。

## 8. 风险与工作量

| 模块 | 规模 | 风险 |
| --- | --- | --- |
| `square/gui/dpi.py`（新增）+ `app.py` 调用点 | ~90 行新增，`app.py` 改 ~10 行 | 中：依赖 CTk 私有 API |
| `requirements*.txt` | 2 文件 | 低 |
| `square-win7.spec` / `build_win7.bat` / `tools/check_bundle.py` | ~200 行 | 中：PyInstaller 5.13.2 的 TOC 结构需实测 |
| `capture.py` | 0～10 行 | 中：只能真机定论 |
| README | 1 节 | 低 |
| 不可控 | — | Python 3.8 已 EOL 无安全更新；numpy 1.24.4 / Pillow 10.4.0 官方不承诺 Win7；CTk 6.0.0 在 3.8 上未实测；32 位进程 2 GB 地址空间；双线长期维护成本 |

## 9. 实施状态

已完成（未提交）：

- [x] `square/gui/dpi.py`（DPI 三级回退 + CTk shim）
- [x] `app.py:run()` 接入上述两个函数
- [x] `requirements.txt` 改为精确 pin；新增 `requirements-win7.txt`
- [x] `square-win7.spec`（二进制白名单 + 位宽自适应 libzbar）
- [x] `build_win7.bat`（PATH 隔离、依赖检查、构建后自检）
- [x] `tools/check_bundle.py`
- [x] README 系统要求改写
- [x] 安装 CPython 3.8.10 x64 到 `E:\Python38`（不入 PATH、不注册 py launcher；
      已删除安装器自动写入的 `HKCU\Software\Python\PythonCore\3.8`，`py -0p` 仍为空）
- [x] 用该解释器建 `.venv-win7`，按 `requirements-win7.txt` 装齐（全部有 cp38 win_amd64 轮子，
      无源码编译、无装不上的包）

本机已跑的验证：

- 四个新增/修改的 Python 文件 `ast.parse` 通过；`square-win7.spec` 可解析；
- `dpi.apply_dpi_awareness()` / `shcore_available()` / `patch_ctk_scaling()` 在 Win11 上行为正确（命中 shcore，未打补丁）；`square.gui.app` 可正常导入；
- 3.13 线 `python tests/test_qr_encoding.py`：13 PASS / 0 FAIL；
- 3.8 线同一脚本（`.venv-win7`）：13 PASS / 0 FAIL，含真实界面的生成→识别往返；
- `build_win7.bat` 实际出包成功，耗时 22 s，`dist/Square-Win7.exe` = 24,319,774 字节（23.2 MiB）；
- `tools/check_bundle.py`：无 `ucrtbase.dll`、无 `api-ms-win-*`；含 `python38.dll`、`tcl86t.dll`、
  `tk86t.dll`、`libiconv.dll`、`msvcr120.dll`、`vcruntime140.dll`、`libzbar-64.dll`；产物架构 x64 与
  libzbar 位宽一致。exe 自身导入表只有 ADVAPI32/COMCTL32/GDI32/KERNEL32/USER32；
- Win11 上对冻结产物做烟测（非 Win7）：启动出主窗口、单码生成、多片生成（5 片拼图）、
  单码与多片的大图弹窗、缩放与「适应窗口」均正常；期间误触区域截图按钮，遮罩层能弹出且
  对空白区域给出「框选区域过小」提示后回到主界面。

已知问题：

- `check_bundle.py` 原先用 `dirname(dirname(toc))` 推仓库根，实际少退一级，导致产物架构校验
  被静默跳过；已改为退三级，并在找不到产物时报错而不是静默通过。
- 冻结产物的一次异常退出未能复现（无 WER 崩溃记录、无事件日志条目），后续真机验证时需留意。

未完成 / 待真机：

- [ ] Win7 SP1 真机全项验证（启动、CTk 缩放不裁切、区域截图、跨屏截图、剪贴板 CF_DIB、
      保存原图、任务栏图标）；Win7 需先装 KB2999226（UCRT），否则 python38.dll 的
      `api-ms-win-crt-*` 依赖无法满足
- [ ] 双线位图一致性回归脚本
