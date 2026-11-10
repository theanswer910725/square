# Win7 验收测试数据 · 操作提示

Author: Lin。
Date: 2026-11-10 21:40:00

按下面的入口逐项操作；每项做完把现象填回 Excel 验收表对应行。

## 打开与复制

1. 用**记事本**打开 `.txt`（UTF-8 带 BOM，中文不会乱码）。
2. `Ctrl+A` 全选 → `Ctrl+C` 复制。**不要手动删改内容**，否则字符数与片数都会变。
3. 在程序里 `Ctrl+V` 粘到「文本输入」框，再点「生成二维码」。

## 环境自检（对应验收表 P5）

> **以下命令必须在 PowerShell 中执行，不能在 cmd 中执行。** 判据：提示符应带 `PS ` 前缀（如 `PS C:\Users\xxx>`）。
> 在 cmd 里粘贴会直接报「`Write-Host` 不是内部或外部命令，也不是可运行的程序或批处理文件」，六项值一个都不会输出——这是 shell 用错了，不是命令写错。

在 **PowerShell** 里整块粘贴。分隔符必须是半角 `;`，不要把中文说明也贴进去：

```powershell
Write-Host '=== Square-Win7 precheck (P5) ==='
Write-Host ('shcore.dll present : ' + (Test-Path 'C:\Windows\System32\shcore.dll') + '   (Win7 expect False)')
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | ForEach-Object { '  screen : ' + $_.DeviceName + '  bounds=' + $_.Bounds.ToString() + '  primary=' + $_.Primary }
$dpi = $null
$src = 'none'
try { $dpi = (Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name AppliedDPI -ErrorAction Stop).AppliedDPI; $src = 'HKCU WindowMetrics AppliedDPI' } catch { }
if ($dpi -eq $null) { try { $dpi = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Hardware Profiles\Current\Software\Fonts' -Name LogPixels -ErrorAction Stop).LogPixels; $src = 'HKLM Hardware Profiles LogPixels' } catch { } }
if ($dpi -eq $null) { $dpi = 96; $src = 'fallback 96 (nothing read)' }
Write-Host ('dpi = ' + $dpi + '   source = ' + $src)
Write-Host ('scale = ' + [int](100 * $dpi / 96) + ' %')
```

单行版：

```powershell
Test-Path 'C:\Windows\System32\shcore.dll'; Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::AllScreens | ForEach-Object { 'screen : ' + $_.DeviceName + ' bounds=' + $_.Bounds.ToString() + ' primary=' + $_.Primary }; $d=$null; try { $d=(Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name AppliedDPI -ErrorAction Stop).AppliedDPI } catch {}; if ($d -eq $null) { try { $d=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Hardware Profiles\Current\Software\Fonts' -Name LogPixels -ErrorAction Stop).LogPixels } catch {} }; if ($d -eq $null) { $d=96 }; 'dpi = ' + $d + '  scale = ' + [int](100*$d/96) + ' %'
```

期望值：100% → `dpi = 96`、`scale = 96 %`；125% → `dpi = 120`、`scale = 125 %`；两种 DPI 都要**注销重登**后再取。
`shcore.dll present` 在 Win7 上必须是 `False`（没有 shcore 才是正常）。`source` 若显示 `fallback 96 (nothing read)`，不要改用 `GetDeviceCaps` 判断，它在非 DPI 感知进程里恒为 96。

### cmd 兜底版（只落到 cmd 时用）

```bat
dir /a C:\Windows\System32\shcore.dll
reg query "HKCU\Control Panel\Desktop\WindowMetrics" /v AppliedDPI
reg query "HKLM\SYSTEM\CurrentControlSet\Hardware Profiles\Current\Software\Fonts" /v LogPixels
wmic desktopmonitor get deviceid,screenwidth,screenheight,availability
```

| 输出 | 判读 |
| --- | --- |
| `dir` 报「系统找不到指定的文件」 | `shcore.dll present` = `False`（Win7 正常） |
| `AppliedDPI    REG_SZ    120` 或 `REG_DWORD    0x78` | `120` / `0x78` → 125%；`96` / `0x60` → 100%；`0x90` → 150% |
| 第一条 `reg query` 报「找不到指定的注册表项或值」 | 改用第二条 `LogPixels` 的值，`source` 记 `HKLM Hardware Profiles` |
| `wmic desktopmonitor` 列出 N 条带分辨率的记录 | 显示器块数 = N（只给数量与分辨率） |

`wmic desktopmonitor` **不提供显示器相对位置**：哪块是主屏、副屏在左还是右都答不了。跨屏仍必须用 PowerShell 的 `[System.Windows.Forms.Screen]::AllScreens`，看 `bounds` 里 `X` 的正负。cmd 兜底只够 `shcore` 与 DPI 两项。

## 逐项入口

| 条目 | 使用文件 | 界面入口 | 要看什么 |
| --- | --- | --- | --- |
| F1 | `F1_single_cn.txt` | 生成器 → 文本输入框 | 预览出现 1 个二维码，提示「点击可查看大图」 |
| F2 | `F2_single_mixed.txt` | 生成器生成后，用**手机**扫屏幕 | 手机上中文、英文、emoji 全部正确（emoji 可能显示为黑白符号，不算失败） |
| F3 | `F3_long_cn_hint.txt` | 生成器 → 先把「清晰度」切到「最清晰」再切回「紧凑」 | 参数区出现「每片上限已由 X 字符降为 Y 字符」这类常驻提示 |
| G1 | `G1_multi_5parts.txt` | 生成器 → 文本输入框 | 预览变成拼图，片数应为 5 |
| G2 | `G2_multi_5parts.txt`、`G2_multi_8parts.txt` | 生成器 → 各生成一次 | 片数分别为 5 与 8；再用 3.13 线 `Square.exe` 生成同样的文件对比 |
| G3 | `G2_multi_8parts.txt` | 生成后点预览打开大图弹窗 | 8 片拼图完整、无空格、无重复 |
| G4 | `G4_extreme_20000.txt` | 生成器 → 文本输入框 | 能出多片或给出明确提示；不卡死、不崩溃 |
| H1 | `F1_single_cn.txt` | 生成器 → 「保存二维码」 | 存成 PNG，能用系统看图打开 |
| H2 | `F1_single_cn.txt`、`H2_roundtrip_multiline.txt` | 解码器 → 「选择图片」→ 选 H1 存的 PNG | 「还原文本」与输入逐字一致；多行那份要保留换行与空行 |
| H3 | `G1_multi_5parts.txt` | 生成 5 片 → 大图弹窗「保存原图」→ 解码器「选择图片」选这张拼图 | 状态行「共 5 片，已收集 …」，收齐后自动还原 |
| E1 / E2 | `F1_single_cn.txt` | 生成 → 大图弹窗「复制全部」→ 画图 / 微信 `Ctrl+V` | 图片能粘出、能发送、能被扫 |
| E3 | 任意文字（先复制一段文字） | 解码器 → 「剪贴板」 | 弹「剪贴板中没有图片」，不崩 |
| E4 | `G1_multi_5parts.txt` | 生成 5 片 → 大图弹窗「复制全部」→ 画图 | 粘出的是拼图，不是单片 |
| I1–I3 | `G2_multi_8parts.txt` | 生成 8 片 → 打开大图弹窗 → 拖缩放滑块 | 8 片拼图缩放连续、滚动条正常、无花屏 |

## 手机扫码扫哪张

- **F2 的手机扫码**：扫屏幕上由 `F2_single_mixed.txt` 生成的**那一个**二维码，不要扫预览缩略图之外的地方；窗口放大到 100% 以上再扫更稳。
- **H3 的多片往返**：不需要手机，全部在 PC 上完成（保存拼图 → 选择图片）。
- **G1/G2 的拼图**：通用扫码器只能读到单片内容（base64 片段），这是设计如此，必须把所有片收集齐才能还原，不要用手机扫多片拼图当作失败。

## 出问题后：日志在哪、要发回什么

程序**正常运行时不做任何日志记录**，所以 `%TEMP%` 下**没有**日志文件是正常现象，不要把它当成失败。

只有在交互回调（点击、切下拉、拖窗口等）里出现**未被捕获的 Python 异常**时，程序才会把 traceback 追加写入：

```
%TEMP%\square-error.log
```

**看不到这个文件 ⇒ 这一轮没有发生回调异常。** 此时若界面卡住或白屏，那是阻塞而非异常，日志里也无从体现，直接按「失败记录」要求截图并描述最后一步操作即可。

文件存在时这样发回：

1. **打开所在目录**：按 `Win+R`，输入 `%TEMP%` 回车。
2. **发回内容**：把 `square-error.log` 整个发回来（通常只有几百字节到几十 KB，一次异常一段，段首是 `===== 时间 =====`）。
3. **判断大方向**：每段末尾是异常类型与出错位置，例如：

| 看到的末行 | 含义 |
| --- | --- |
| `ZeroDivisionError: ...` / `AttributeError: ...` / `TclError: ...` | 该回调里发生了 Python 异常，末行往上两行即出错的文件与行号 |
| 没有任何 `=====` 段落 | 文件被别的程序误建，可忽略 |

## 常见误判

- 复制时把行尾换行也带上了：字符数会比清单多 1–2，5 片/8 片可能变成 6 片/9 片。此时用清单的「字符数」核对粘贴后的字数（生成器不显示字数时可用记事本状态栏估）。
- 用 WinRAR / 7-Zip 解压导致 BOM 丢失或换行被转：重新从原始目录拷贝，并用 `certutil` 核对 SHA256。
- 把清晰度改成「最清晰」后片数变多：正常，见 manifest 文末附表。
