# Win7 真机验收清单（Square-Win7.exe）

Author: Lin。
Date: 2026-11-10 19:10:00

> 用法：在一台 Windows 7 SP1 x64 机器上按 A→I 顺序逐项执行，每项在「结果」栏打勾。
> 失败时不要跳过，按该项的「失败记录」采集证据，最后填第 11 节模板回传。
> 本清单只覆盖冻结产物 `Square-Win7.exe`，不涉及源码运行。

## 1. 前置条件（先全部核对，任一不满足则本轮验收作废）

### 1.1 被测文件

| 项 | 值 |
| --- | --- |
| 路径（建议） | `D:\SquareWin7\Square-Win7.exe` |
| 大小 | 24,319,773 字节（23.2 MiB） |
| SHA256 | `28B410321A4A6297D7D5AE7A23CEF4937732D9B01264737557594B2ADCDEDADB` |
| 架构 | x64（只能跑在 64 位 Win7 上） |

校验命令（Win7 SP1 自带 certutil，不要用 `Get-FileHash`，PS 2.0 没有该 cmdlet）：

```bat
certutil -hashfile D:\SquareWin7\Square-Win7.exe SHA256
```

- [ ] 输出的哈希与上表一致。不一致就停止验收，重新拷贝文件（传输损坏会导致假故障）。

### 1.2 系统与运行库

在「开始 → 运行」输入 `winver` 记下版本号，然后依次执行：

```bat
ver
```
```powershell
# UCRT（KB2999226 的效果）是否在位
Test-Path C:\Windows\System32\ucrtbase.dll
Test-Path C:\Windows\System32\api-ms-win-crt-runtime-l1-1-0.dll
# VC++ 2013 x64 运行库（libzbar-64.dll 静态依赖 MSVCR120.dll）
Test-Path C:\Windows\System32\msvcr120.dll
# 是否装了 KB2999226（部分系统该补丁不进 Get-HotFix 列表，以上面的文件是否存在为准）
Get-HotFix -Id KB2999226 -ErrorAction SilentlyContinue
```

- [ ] `ver` 显示 `Microsoft Windows [版本 6.1.7601]`（即 Win7 SP1；6.1.7600 说明没打 SP1，直接终止验收）
- [ ] `ucrtbase.dll` 与 `api-ms-win-crt-runtime-l1-1-0.dll` 均为 `True`
- [ ] `msvcr120.dll` 为 `True`
- [ ] 记下三条命令的原始输出（回传模板要用）

任一项为 `False`：先装对应运行库再验收，不要带着缺失环境去判断程序是否有 bug。

- KB2999226（UCRT）缺失 → 症状是启动即报「Failed to load Python DLL ...\python38.dll ... 找不到指定的模块」
- VC++ 2013 x64 缺失 → 症状是解码时报找不到 `MSVCR120.dll` 或 pyzbar 加载失败

### 1.2.1 本机已确认的信息（2026-11-10 winver 截图）

| 项 | 已确认值 | 结论 |
| --- | --- | --- |
| 版本名称 | Windows 7 旗舰版 | — |
| 内部版本 | `6.1 (内部版本 7601: Service Pack 1)` | **已满足 SP1 要求** |
| 系统类型 | 截图未显示 | **待确认，见下** |

系统位数必须另行确认（winver 不显示），两条命令任一即可：

```bat
echo %PROCESSOR_ARCHITECTURE%
```
```powershell
Get-WmiObject Win32_OperatingSystem | Select-Object OSArchitecture
```

- 输出 `AMD64` / `64 位` → 满足，继续验收
- 输出 `x86` / `32 位` → **停止**：`Square-Win7.exe` 是 x64 产物，32 位 Win7 上双击会直接报「不是有效的 Win32 应用程序」，这不是缺陷。需要改用 32 位 Python 3.8 构建的产物（`square-win7.spec` 会按解释器位宽自动选 `libzbar-32.dll`）

### 1.2.2 补装顺序与逐步验证（仅当 1.2 检查有 `False` 时）

顺序不可颠倒：UCRT 的安装包要求 SP1；VC++ 2013 与 UCRT 无依赖关系但建议后装便于分辨报错来源。

1. **SP1**（已满足，跳过）。若遇到 7600 的机器：KB2999226 与绝大多数 Win7 补丁都要求 SP1，必须先装 Windows 7 SP1（微软已下线直接下载，可用 Windows Update，或离线包 `windows6.1-KB976932-X64.exe`）
   - 验证：`winver` 显示 `内部版本 7601: Service Pack 1`
2. **KB2999226（UCRT）**
   - 验证：`Test-Path C:\Windows\System32\api-ms-win-crt-runtime-l1-1-0.dll` 为 `True`，且 `ucrtbase.dll` 在同目录
   - 没装成时 `Get-HotFix -Id KB2999226` 常查不到条目，以文件是否存在为准
3. **VC++ 2013 x64 运行库**（`vcredist_x64.exe`，2013 Update 5）
   - 验证：`Test-Path C:\Windows\System32\msvcr120.dll` 为 `True`；也可在「程序和功能」看到 `Microsoft Visual C++ 2013 Redistributable (x64)`

### 1.2.3 启动阶段三种失败形态的区分

`Square-Win7.exe` 是 onefile，启动分两段：bootloader 解包 → `LoadLibrary(python38.dll)`。报错形态直接对应根因，不要混为一谈：

| 报错 | 出现阶段 | 根因 |
| --- | --- | --- |
| 「不是有效的 Win32 应用程序」 | 双击即失败 | 系统是 32 位，产物是 x64 |
| 「Failed to load Python DLL ...\python38.dll ... 找不到指定的模块」 | 解包后 | 系统缺 UCRT（`api-ms-win-crt-*`），即 KB2999226 未装或未生效 |
| 「丢失 api-ms-win-core-path-l1-1-0.dll」 | 双击即失败 | 拿错了产物：这是 3.13 线的 `Square.exe`，Win7 不支持，必须换 `Square-Win7.exe` |

补充：本产物的 bootloader 只导入 `KERNEL32/USER32/ADVAPI32/COMCTL32/GDI32`，这五个 DLL 在 Win7 RTM 上就有，所以 **bootloader 阶段本身不挑 SP1**；真正卡住启动的是第二段的 `python38.dll` 对 UCRT 的依赖。也就是说：没 SP1 的机器表现与「有 SP1 但没装 UCRT」在用户看来是同一条报错，只能靠 `winver` 区分。

### 1.3 显示环境

> **以下命令必须在 PowerShell 中执行，不能在 cmd 中执行。**
> 判据：窗口提示符要带 `PS ` 前缀，例如 `PS C:\Users\xxx>`。
> 在 cmd 里粘贴下面任何一段，都会直接报「`Write-Host` 不是内部或外部命令，也不是可运行的程序或批处理文件」，而且六项值一个都不会输出——那不是脚本写错，是 shell 用错了。cmd 的提示符形如 `C:\Users\xxx>`，没有 `PS `。
> 打开 PowerShell 的方法：「开始 → 运行」输入 `powershell` 回车，确认提示符带 `PS ` 再粘贴。

在 **PowerShell** 里整块粘贴（PS 2.0 可用；分隔符必须是半角 `;`，末尾不要带中文说明）：

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

单行版（同样可直接粘）：

```powershell
Test-Path 'C:\Windows\System32\shcore.dll'; Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::AllScreens | ForEach-Object { 'screen : ' + $_.DeviceName + ' bounds=' + $_.Bounds.ToString() + ' primary=' + $_.Primary }; $d=$null; try { $d=(Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name AppliedDPI -ErrorAction Stop).AppliedDPI } catch {}; if ($d -eq $null) { try { $d=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Hardware Profiles\Current\Software\Fonts' -Name LogPixels -ErrorAction Stop).LogPixels } catch {} }; if ($d -eq $null) { $d=96 }; 'dpi = ' + $d + '  scale = ' + [int](100*$d/96) + ' %'
```

如果只习惯用 cmd、也不想在 cmd 里套 `powershell -Command`，用下面这组纯 cmd 命令兜底（能拿到 `shcore` 与 DPI，但**拿不到屏幕相对位置**）：

```bat
dir /a C:\Windows\System32\shcore.dll
reg query "HKCU\Control Panel\Desktop\WindowMetrics" /v AppliedDPI
reg query "HKLM\SYSTEM\CurrentControlSet\Hardware Profiles\Current\Software\Fonts" /v LogPixels
wmic desktopmonitor get deviceid,screenwidth,screenheight,availability
```

读法：

| 输出 | 判读 |
| --- | --- |
| `dir` 报「系统找不到指定的文件」 | P5-1 记 `False`（Win7 正常结果） |
| `AppliedDPI    REG_SZ    120` 或 `REG_DWORD    0x78` | `120` / `0x78` → 125%；`96` / `0x60` → 100%；`0x90` → 150%（十六进制换算：0x60=96、0x78=120、0x90=144） |
| 第一条 `reg query` 报「找不到指定的注册表项或值」 | 改用第二条 `LogPixels` 的值，`source` 记 `HKLM Hardware Profiles` |
| `wmic desktopmonitor` 列出 N 条带分辨率的记录 | 显示器块数 = N（只给数量与分辨率） |

`wmic desktopmonitor` **不提供显示器相对位置**——哪块是主屏、副屏在左还是右，它都答不了。跨屏布局仍要靠 PowerShell 的 `[System.Windows.Forms.Screen]::AllScreens`，看 `bounds` 里 `X` 的正负判断。所以 cmd 兜底只够完成 P5-1 与 P5-3，**P5-2 仍建议补跑一次 PowerShell**。

- [ ] P5-1 `shcore.dll present` 为 `False`（Win7 没有 shcore，属正常）
- [ ] P5-2 记下显示器数量、每台的分辨率与相对位置（例如副屏在主屏左侧，则副屏 x 为负）
- [ ] P5-3 `dpi` 记录两次：一次在「控制面板 → 显示」设为 **较小(100%)**，一次设为 **中等(125%)**，注销重登后重取（Win7 改 DPI 必须注销才生效）

期望值与判读：

| 运行时机 | `dpi` | `scale` | `source` |
| --- | --- | --- | --- |
| 100% | `96` | `96 %` | `HKCU WindowMetrics AppliedDPI` |
| 125% | `120` | `125 %` | 同上 |
| 144（150%） | `144` | `150 %` | 同上 |

- 若 `source` 变成 `HKLM Hardware Profiles LogPixels`：说明 HKCU 里没有 `AppliedDPI`，值仍可信，需在备注里写明。
- 若 `source` 变成 `fallback 96 (nothing read)`：两个位置都没读到，**不要**改用 `GetDeviceCaps` 当判据——非 DPI 感知进程里它恒返回 96，会把 125% 误判成 100%。此时直接以「控制面板 → 显示」里选的档位为准，并在备注写明注册表读不到。
- 100% 与 125% 两次的 `dpi` 若都是 96，通常是没注销重登，重新登录后再取。

> 第 2 节要求 100% 与 125% 各跑一遍；第 4 节要求多显示器。单屏机器请在第 4 节直接记「阻塞：无第二台显示器」。

### 1.4 命令级核对（在 Win7 上直接复制粘贴）

以下命令全部在 **cmd.exe** 或 **PowerShell 2.0** 原生支持下可用，不需要装任何东西。

#### 1.4.0 开一个 64 位 cmd

「开始 → 运行」输入 `cmd` 即可。下面的命令若在 32 位 cmd 里跑，个别项会给出误导结果（见 1.4.1）。

#### 1.4.1 系统位数

```bat
echo %PROCESSOR_ARCHITECTURE%
echo %PROCESSOR_ARCHITEW6432%
wmic os get osarchitecture
```

| 命令 | 期望输出 | 判读 |
| --- | --- | --- |
| `%PROCESSOR_ARCHITECTURE%` | `AMD64` | 64 位系统 + 64 位 cmd |
| 同上 | `x86` | **可能是坑**：64 位系统上被 32 位 cmd（如某些 32 位程序自带的终端）启动时也显示 `x86`，必须看下一条 |
| `%PROCESSOR_ARCHITEW6432%` | `AMD64` | 说明真实系统是 64 位，当前只是跑在 32 位进程里；结论仍是通过 |
| 同上 | `%PROCESSOR_ARCHITEW6432%`（原样输出，未展开） | 系统确实是 32 位，**停止验收** |
| `wmic os get osarchitecture` | `OSArchitecture` / `64-bit` | 权威结论；显示 `32-bit` 即 32 位系统 |

判读规则：`osarchitecture = 64-bit` 或 `PROCESSOR_ARCHITEW6432 = AMD64` 任一命中即视为 64 位系统。两者都指向 32 位 → `Square-Win7.exe` 无法运行（双击报「不是有效的 Win32 应用程序」）。

#### 1.4.2 UCRT（KB2999226）

```bat
dir /a C:\Windows\System32\ucrtbase.dll
dir /a C:\Windows\System32\api-ms-win-crt-runtime-l1-1-0.dll
wmic datafile where "name='C:\Windows\System32\ucrtbase.dll'" get version
```

| 命令 | 期望输出 | 失败含义 |
| --- | --- | --- |
| 两条 `dir` | 各列出 1 个文件（约 970 KB / 约 20 KB） | 「系统找不到指定的文件」→ UCRT 未安装，启动时 `python38.dll` 加载失败 |
| `wmic ... get version` | `10.0.10240.16384` 或更高（Win7 上通常是 `10.0.10240.x` / `10.0.10586.x`） | 无输出或报错 → 同上；版本低于 `10.0.10240` 说明是早期预览版 UCRT，建议重装 KB2999226 |

补充：`Get-HotFix -Id KB2999226` 在很多机器上查不到条目（该补丁不一定登记为 hotfix），**不要以它为空判定未安装**，以上面的文件为准。

#### 1.4.3 VC++ 2013 x64

```bat
dir /a C:\Windows\System32\msvcr120.dll
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "Visual C++ 2013" /d
reg query "HKLM\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "Visual C++ 2013" /d
```

| 命令 | 期望输出 | 失败含义 |
| --- | --- | --- |
| `dir msvcr120.dll` | 列出文件（约 950 KB） | 找不到 → 未装 VC++ 2013 x64；解码时报 `MSVCR120.dll` 缺失 |
| 第一条 `reg query` | 至少 1 个 `DisplayName    REG_SZ    Microsoft Visual C++ 2013 x64 ...`（通常带 `Additional Runtime` / `Minimum Runtime` 两条；版本 `12.0.21005` 是 2013 RTM，`12.0.40664` 是 Update 5，**两者都算通过**） | 只有 `x86` 条目 → 装的是 32 位运行库，**不满足**，需再装 x64 |
| 第二条 `reg query` | 可能出现 `Microsoft Visual C++ 2013 Redistributable (x86)` | 仅作参考；x64 条目在第一条里 |

也可以用 `wmic product where "name like '%Visual C++ 2013%'" get name,version`，但有两点要注意：
- 它慢（十几秒到几分钟），因为 `Win32_Product` 会对每个 MSI 触发一次一致性检查；
- 对非 MSI 方式安装的运行库返回空，**空结果不能判定未安装**，以 `msvcr120.dll` 是否存在为准（若在 .bat 里写这条命令，`%` 要写成 `%%`）。

#### 1.4.4 被测文件哈希与大小

```bat
dir D:\SquareWin7\Square-Win7.exe
certutil -hashfile D:\SquareWin7\Square-Win7.exe SHA256
```

| 命令 | 期望输出 | 失败含义 |
| --- | --- | --- |
| `dir` | `24,319,773` 字节（`24,319,773 bytes`） | 字节数不符 → 文件不完整或被替换，重新拷贝 |
| `certutil` | `28b410321a4a6297d7d5ae7a23cef4937732d9b01264737557594b2adcdedadb`（大小写、是否带空格随系统语言/版本略有差异） | 不一致 → 传输损坏，重新拷贝，不要继续验收 |

完整期望值（比对时忽略空格与大小写）：

```
28B410321A4A6297D7D5AE7A23CEF4937732D9B01264737557594B2ADCDEDADB
```

#### 1.4.5 启动失败三种形态的命令级判据

先执行，再对着结果判断：

```bat
tasklist /fi "imagename eq Square-Win7.exe"
dir /b "%TEMP%\_MEI*"
wevtutil qe Application /c:5 /rd:true /f:text
```

| 现象 | 命令级判据 | 结论 |
| --- | --- | --- |
| 双击**立刻**弹「不是有效的 Win32 应用程序」 | `tasklist` 无进程；`%TEMP%\_MEI*` **不产生** | 系统是 32 位，产物是 x64（见 1.4.1） |
| 弹「Failed to load Python DLL ...\python38.dll ... 找不到指定的模块」 | `tasklist` 无进程；`%TEMP%\_MEI*` **有**目录（解包已发生） | 缺 UCRT（见 1.4.2） |
| 弹「丢失 api-ms-win-core-path-l1-1-0.dll」 | 同上，且窗口标题是 `Square.exe` | 拿错产物，那是 3.13 线，换 `Square-Win7.exe` |
| 进程存在但**没有窗口** | `tasklist` 有 1–2 个进程，持续 30 s 以上；`wevtutil` 里可能有 `Application Error` 条目 | 卡在解包或 UI 初始化；记录 `_MEI` 目录名、进程数、事件条目全文 |
| 双击毫无反应 | `tasklist` 无进程且 `_MEI*` 无目录 | 被拦截（杀软/组策略），查「事件查看器 → Windows 日志 → 安全」与杀软日志 |

`wevtutil` 只看错误级条目可以加过滤（PowerShell 里执行，注意引号）：

```powershell
wevtutil qe Application /q:"*[System[(Level=2)]]" /c:5 /rd:true /f:text
```

### 1.5 一次性自检脚本（PowerShell 2.0 兼容）

把下面内容保存为 `check-win7.ps1`（与 exe 同目录），然后在该目录执行：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File .\check-win7.ps1
```

脚本只用 Win7 自带的 PowerShell 2.0 能力（**不用** `Get-FileHash`、`Get-CimInstance`、`$PSScriptRoot`），哈希用 .NET 的 `SHA256` 计算。
脚本正文与输出**全为 ASCII**：PS 2.0 按 ANSI(GBK) 读取 .ps1，若文件含中文且被存成 UTF-8（无 BOM），中文字符的字节会被拆错甚至提前闭合引号，直接报语法错误。全 ASCII 后无论记事本存 ANSI 还是 UTF-8 都能跑。

```powershell
param([string]$Exe = 'D:\SquareWin7\Square-Win7.exe')

$script:fail = 0

function Show([string]$k, [string]$v, [string]$e) {
    "{0,-26} {1,-56} {2}" -f $k, $v, $e
}
function Mark([bool]$ok) {
    if (-not $ok) { $script:fail = $script:fail + 1 }
    if ($ok) { return 'PASS' } else { return 'FAIL' }
}

"=== Square-Win7 environment check ==="
"time: " + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
""
"{0,-26} {1,-56} {2}" -f 'ITEM', 'ACTUAL', 'EXPECTED'
"------------------------------------------------------------------------------------------------------"

$os = Get-WmiObject Win32_OperatingSystem
$csd = '(none)'
if ($os.CSDVersion) { $csd = $os.CSDVersion }
Show 'OS Version' $os.Version '6.1.7601'
Show 'OS Caption' $os.Caption 'Windows 7 ...'
Show 'Service Pack' $csd 'Service Pack 1'
"  sp1 verdict: " + (Mark ($os.Version -eq '6.1.7601'))

$arch = $env:PROCESSOR_ARCHITECTURE
$arch2 = '(empty)'
if ($env:PROCESSOR_ARCHITEW6432) { $arch2 = $env:PROCESSOR_ARCHITEW6432 }
Show 'PROCESSOR_ARCHITECTURE' $arch 'AMD64'
Show 'PROCESSOR_ARCHITEW6432' $arch2 'AMD64 or (empty)'
Show 'OSArchitecture' $os.OSArchitecture 'contains 64'
$is64 = ((($arch -eq 'AMD64') -or ($arch2 -eq 'AMD64')) -and ($os.OSArchitecture -match '64'))
"  arch verdict: " + (Mark $is64)
""

$u1 = 'C:\Windows\System32\ucrtbase.dll'
$u2 = 'C:\Windows\System32\api-ms-win-crt-runtime-l1-1-0.dll'
$uv = '(missing)'
if (Test-Path $u1) { $uv = (Get-Item $u1).VersionInfo.FileVersion }
Show 'ucrtbase.dll' ((Test-Path $u1).ToString() + '  ver=' + $uv) 'True / ver >= 10.0.10240'
Show 'api-ms-win-crt-runtime' (Test-Path $u2) 'True (Win7)'
$u2ok = Test-Path $u2
if (-not $u2ok) { "  note: on Win10/11 this file is absent because the API set is virtualized; it must exist on Win7." }
$hasUcrt = ((Test-Path $u1) -and ($u2ok -or ($os.Version -like '10.*')))
"  UCRT verdict: " + (Mark $hasUcrt)
""

$m = 'C:\Windows\System32\msvcr120.dll'
$mv = '(missing)'
if (Test-Path $m) { $mv = (Get-Item $m).VersionInfo.FileVersion }
Show 'msvcr120.dll' ((Test-Path $m).ToString() + '  ver=' + $mv) 'True'
$hasVc = Test-Path $m

$keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
          'HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
$found = @()
foreach ($k in $keys) {
    if (Test-Path $k) {
        $items = Get-ChildItem $k | ForEach-Object { Get-ItemProperty $_.PSPath }
        foreach ($i in $items) {
            if ($i.DisplayName -like '*Visual C++ 2013*') { $found = $found + $i.DisplayName }
        }
    }
}
if ($found.Length -eq 0) { Show 'VC++2013 uninstall' '(no entry)' 'contains x64' }
foreach ($n in $found) { Show 'VC++2013 uninstall' $n 'contains x64' }
"  VC++2013 verdict: " + (Mark $hasVc)
""

if (Test-Path $Exe) {
    $len = (Get-Item $Exe).Length
    Show 'exe size' ($len.ToString() + ' bytes') '24319773'
    $fs = [System.IO.File]::OpenRead($Exe)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash($fs)
    $fs.Close()
    $hex = ''
    foreach ($b in $bytes) { $hex = $hex + $b.ToString('x2') }
    $hex = $hex.ToUpper()
    Show 'SHA256' $hex '28B41032...DEDADB'
    $want = '28B410321A4A6297D7D5AE7A23CEF4937732D9B01264737557594B2ADCDEDADB'
    $hashOk = ((($hex -eq $want) -and ($len -eq 24319773)))
    "  file verdict: " + (Mark $hashOk)
} else {
    Show 'exe path' $Exe '(not found)'
    "  file verdict: FAIL"
    $script:fail = $script:fail + 1
}
""
"=== summary: failed items " + $script:fail + " ==="
if ($script:fail -eq 0) { "verdict: environment and file OK, start from section 2." }
else { "verdict: unmet items found, fix per 1.2.2 then rerun." }
```

> 脚本里的 `$Exe` 默认路径要改成实际存放位置；路径含空格时用 `-Exe "D:\My Apps\Square-Win7.exe"`。

## 2. A 启动与窗口渲染

### A1 冷启动

- 操作：双击 `Square-Win7.exe`（onefile 首次启动要解包，3–10 s 属正常）
- 预期：出现标题为「方寸 · Square」的窗口，客户区约 793×572 物理像素（100% DPI 下）；左右两栏「预览」「文本输入」，顶部页签「生成器 / 解码器」；预览区居中显示灰字「输入文本后点击「生成二维码」」；无任何错误弹窗
- 失败记录：完整错误框截图（必须含标题栏与 DLL 名）、任务管理器里 `Square-Win7.exe` 是否还有进程、事件查看器 → Windows 日志 → 应用程序 中最近 5 分钟的「错误」级条目全文

- [ ] 结果：

### A2 二次启动（热缓存）

- 操作：关闭窗口，等 5 s，再次双击
- 预期：启动更快；窗口与首次一致；不出现两个主窗口
- 失败记录：任务管理器截图（记录进程数：onefile 正常是 2 个同名进程，父进程负责解包）、`%TEMP%` 下是否残留 `_MEIxxxxx` 目录

- [ ] 结果：

### A3 关闭与任务栏

- 操作：点窗口右上角 ×；再从任务栏启动
- 预期：进程完全退出（任务管理器中两个 `Square-Win7.exe` 都消失）；任务栏按钮为程序自带图标而非默认白纸图标
- 失败记录：任务管理器截图、`%TEMP%` 中 `_MEI*` 是否残留

- [ ] 结果：

## 3. B DPI 缩放（100% 与 125% 各一轮）

> 目的：验证 `square/gui/dpi.py` 在无 `shcore.dll` 的 Win7 上确实生效（见第 10 节 R3）。
> 计量窗口物理尺寸：

```powershell
Add-Type @"
using System;using System.Runtime.InteropServices;
public class W{[DllImport("user32.dll")]public static extern bool GetWindowRect(IntPtr h,out R r);public struct R{public int L,T,Rt,B;}}
"@
$p = Get-Process Square-Win7 | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
$r = New-Object W+R
[W]::GetWindowRect($p.MainWindowHandle,[ref]$r) | Out-Null
"W=$($r.Rt-$r.L) H=$($r.B-$r.T)"
```

### B1 100% 下的整体渲染

- 操作：DPI 设为 100%（注销重登），启动，量窗口尺寸并截图整窗
- 预期：窗口约 793×572±20；标题、页签、下拉框、按钮文字完整不被截断；文字边缘锐利
- 失败记录：整窗截图 + 上面命令输出的 W/H

- [ ] 结果：

### B2 125% 下的整体渲染

- 操作：DPI 设为 125%（注销重登），启动，量窗口尺寸并截图整窗
- 预期：窗口物理尺寸约为 B1 的 **1.25 倍**（约 991×715）；文字与控件同步放大且仍不截断；文字边缘锐利（若模糊发虚，说明进程没拿到 DPI 感知，属缺陷）
- 失败记录：整窗截图 + W/H；同时记录 B1 的 W/H 用于比值

- [ ] 结果：

### B3 125% 下参数区不被裁切

- 操作：在 125% 下把「纠错率 / 清晰度 / 编码策略」三个下拉逐个展开再收起
- 预期：三行标签与下拉框文字完整（「最清晰（分片最多，单码最疏）」这种最长的也不被切）；底部「生成二维码 / 保存二维码」两颗按钮完整
- 失败记录：参数区局部截图（含底部按钮）

- [ ] 结果：

### B4 125% 下状态行与解码器页

- 操作：切到「解码器」页，观察状态行
- 预期：状态行默认显示「等待输入图片」；右侧「截图识别 / 选择图片 / 剪贴板 / 清空收集」四颗按钮文字完整、不重叠
- 失败记录：解码器页整页截图

- [ ] 结果：

## 4. C 区域截图框选

### C1 遮罩与提示

- 操作：生成器页输入任意文字 → 生成 → 点预览区右上角的截图图标（悬停提示为「截图：框选屏幕区域后送至解码器」）
- 预期：全屏半透明遮罩铺满**整块虚拟桌面**（多屏时覆盖所有屏幕）；顶部提示文字「拖拽框选二维码区域；按 Esc 或右键取消」；鼠标变为十字；主窗口不隐藏
- 失败记录：整屏截图（含所有显示器；用 PrintScreen 而非窗口截图）

- [ ] 结果：

### C2 拖拽框选与尺寸显示

- 操作：拖拽一个包含预览二维码的矩形；拖拽过程中观察
- 预期：出现虚线选框，光标右下角实时显示 `宽×高` 数字；松开后遮罩消失，自动切到「解码器」页并开始识别
- 失败记录：拖拽过程中的整屏截图

- [ ] 结果：

### C3 框选过小

- 操作：拖拽一个 5×5 像素左右的极小区域
- 预期：弹出「提示 / 框选区域过小，请重新框选。」，点确定后回到主界面，遮罩不残留
- 失败记录：提示框截图 + 弹窗关闭后整窗截图（确认遮罩已消失）

- [ ] 结果：

### C4 Esc 取消

- 操作：再次点截图图标 → 只移动鼠标不拖拽 → 按 Esc
- 预期：遮罩立即消失，回到原页面；**不弹任何提示**；不产生截图；主窗口可继续操作
- 失败记录：按键后 3 s 的整屏截图

- [ ] 结果：

### C5 右键取消（含拖拽中取消）

- 操作：点截图图标 → 右键单击；再重来一次，拖拽到一半时右键
- 预期：两种情况遮罩都消失；拖拽中右键后再松开左键也不会触发识别
- 失败记录：操作后整屏截图 + 解码器页状态行文字

- [ ] 结果：

## 5. D 跨屏截图（需至少两台显示器）

### D1 副屏在主屏右侧

- 操作：把主窗口与预览图拖到副屏（坐标为正值区），点截图图标
- 预期：遮罩覆盖副屏；框选副屏上的二维码能正确识别；识别结果与框选区域一致（不偏移、不缩放到主屏尺寸）
- 失败记录：整屏截图 + 框选时的尺寸数字 + 识别后状态行文字

- [ ] 结果：

### D2 副屏在主屏左侧（负坐标）

- 操作：把副屏设为主屏左侧（副屏 x 为负），重复 D1
- 预期：遮罩覆盖负坐标区域且完整；框选后识别正确、不错位
- 失败记录：整屏截图（必须包含负坐标副屏）+ 状态行文字

- [ ] 结果：

### D3 跨屏框选

- 操作：从主屏拖到副屏框一个跨屏矩形
- 预期：选框跨屏连续、尺寸数字正确；若区域内无二维码，弹「提示 / 未识别到二维码，请重新框选」
- 失败记录：拖拽中整屏截图 + 提示框截图

- [ ] 结果：

### D4 双屏不同分辨率

- 操作：两台显示器分辨率不同（如 1920×1080 + 1366×768），在低分辨率屏上框选
- 预期：选框位置与实际鼠标位置一致；识别正确
- 失败记录：整屏截图 + 两屏分辨率

- [ ] 结果：

## 6. E 剪贴板写入 CF_DIB

### E1 复制全部后是否可粘贴

- 操作：生成一个二维码 → 点预览区打开大图弹窗 → 点「复制全部」→ 打开「画图」→ Ctrl+V
- 预期：画图中出现与弹窗一致的二维码图（白底黑码，不透明错乱、不空白）
- 失败记录：画图窗口截图 + 弹窗截图对照

- [ ] 结果：

### E2 粘贴到微信

- 操作：重复 E1 的复制，然后在微信聊天窗口 Ctrl+V（PC 微信或企业微信任一）
- 预期：图片正常出现在输入框并能发送；对方收到后可长按识别二维码
- 失败记录：微信输入框截图

- [ ] 结果：

### E3 无图剪贴板

- 操作：先复制一段文字，再切到解码器页点「剪贴板」
- 预期：弹出「无法读取图片 / 剪贴板中没有图片。」，状态行显示「剪贴板中没有图片」；程序不崩
- 失败记录：提示框截图

- [ ] 结果：

### E4 大图复制在 Win7 上是否退化

- 操作：用多片（≥3 片）生成 → 大图弹窗 → 复制全部 → 粘贴到画图
- 预期：粘贴出的拼图与弹窗一致，像素数足够打印识别
- 失败记录：画图与弹窗的对照截图（标注两者尺寸）

- [ ] 结果：

## 7. F 单码生成与手机扫码

### F1 短文本单码

- 操作：输入「冻干粉大富大贵」→ 点「生成二维码」
- 预期：预览出现二维码，下方出现「点击可查看大图」；按钮文字在生成期间显示「生成中……」后恢复为「生成二维码」；参数区无红色/异常提示
- 失败记录：整窗截图

- [ ] 结果：

### F2 手机实测扫码

- 操作：用手机相机/扫码 App 扫屏幕上的二维码
- 预期：扫出内容与输入文本一字不差（中文正确、无乱码）
- 失败记录：手机扫码结果截图 + 输入的原文

- [ ] 结果：

### F3 参数档位提示

- 操作：①「纠错率」设为「较高（约 25% 可恢复）」，「清晰度」设为「紧凑（分片少，码密）」，输入 `docs/win7-testdata/F3_long_cn_hint.txt` 观察参数区；②再把「编码策略」切到「压缩+分片」看第二条提示
- 预期：① 出现「当前纠错率「较高（约 25% 可恢复）」下单码容量有限，每片上限已由 1700 字符降为 1639 字符。」；② 追加「压缩码仅可本软件还原，通用扫码工具读取到的内容为编码字符串非原始文本。」；两行都完整不被截断
- 判读要点：提示只在「纠错率单码容量 − 24 < 清晰度档位」时出现。默认「中等」容量 2307，压不低任何档位，**此时没有提示属正确行为**；「最高（H）+ 紧凑」会显示「降为 1249 字符」
- 失败记录：参数区截图

- [ ] 结果：

### F3-R 策略切换稳定性（复测「切到压缩+分片卡死」）

- 操作：在「纠错率 / 清晰度 / 编码策略」三个下拉之间来回切，四个策略都覆盖：自动 → 强制单码 → 强制分片 → 压缩+分片 → 自动……**连续 10 轮（40 次）**，每次只切下拉、不点生成
- 预期：每次切换后界面立即响应；参数区提示随档位正确出现/消失；窗口尺寸不变、文字不抖；全程不出现无响应、白屏、哑色矩形
- 卡住时怎么做：**不要关程序**，先按 `Win+R` → `%TEMP%` 看有没有 `square-error.log`。正常运行时程序不写任何日志，**该文件不存在即说明本轮没有回调异常**；存在则把它整个取回（每次异常一段，段首为 `===== 时间 =====`）
- 判读要点：日志里只有段首 `=====` 加 traceback，末行是异常类型与消息，往上一两行即出错的文件与行号 —— 有它说明是异常，不是阻塞；没有文件而界面仍无响应，则属阻塞，只能靠异常前的最后一步操作与截图定位（`docs/win7-testdata/usage.md` 的「出问题后」一节）
- 失败记录：`square-error.log` 全文（若存在）+ 整窗截图

- [ ] 结果：

## 8. G 多片生成与预览片号

### G1 触发多片

- 操作：输入约 3000 字符的不可压缩文本（例如把一段随机英文/十六进制串粘贴进去），点生成
- 预期：预览区显示由多张二维码拼成的拼图（片数与拼图格子数一致）；生成耗时在数秒内
- 失败记录：整窗截图 + 输入文本长度

> 预期口径说明：当前版本的生成器预览**不叠加片号数字**，片号只以拼图顺序体现；「共 N 片 / 已收集 M 片」的片号文案出现在解码器页进度行。若验收要求「生成器预览上直接标 1/5、2/5」，此版本不满足，按失败记录（这属于需求差异，不是 Win7 缺陷）。

- [ ] 结果：

### G2 片数正确性

- 操作：同一个文本分别在 3.13 线产物与现代系统线正常运行环境各生成一次（若有条件），对比片数
- 预期：两条线片数相同（segno/pyzbar 同版本）
- 失败记录：两次生成的整窗截图对照

- [ ] 结果：

### G3 大图里看完整拼图

- 操作：点预览区打开大图弹窗
- 预期：弹窗内显示完整拼图（所有片都在，无空白格、无重复）；顶部「缩放」「100%」「适应窗口」「复制全部」「保存原图」齐全
- 失败记录：弹窗截图

- [ ] 结果：

### G4 极端长文本

- 操作：粘贴 20000 字符以上文本
- 预期：要么正常出多片，要么给出明确提示；不得静默失败或崩溃
- 失败记录：状态/提示文字 + 任务管理器进程状态

- [ ] 结果：

## 9. H 导出图片与解码往返

### H1 保存二维码

- 操作：生成单码 → 点「保存二维码」→ 存为 PNG
- 预期：保存成功且无错误框；文件可用系统图片查看器打开，尺寸与预览一致
- 失败记录：保存对话框与保存后目录截图

- [ ] 结果：

### H2 用解码器选择图片往返

- 操作：切到「解码器」→ 点「选择图片」→ 选中 H1 的 PNG
- 预期：状态行先「正在识别图片……」，随后出现「已识别到 1 个二维码」类信息；「还原文本」区内容与原文逐字一致
- 失败记录：解码器页整页截图（含状态行与还原文本区）

- [ ] 结果：

### H3 多片往返

- 操作：把 G1 的多片分别保存/逐张用「选择图片」送入（或一次选包含多片的整图）
- 预期：状态行显示「共 N 片，已收集 M 片，缺失 K 片」并随片数增加收敛；收齐后自动还原，文本逐字一致
- 失败记录：每次识别后的状态行文字（截图或手抄）

- [ ] 结果：

### H4 清空收集

- 操作：点「清空收集」
- 预期：状态行变为「已清空收集分片，可重新选择图片」；随后单张识别不再混入旧分片
- 失败记录：状态行截图

- [ ] 结果：

## 10. I 大图弹窗缩放与滚动

### I1 缩放滑块

- 操作：打开大图弹窗，把「缩放」滑块从最小拖到最大
- 预期：图片连续缩放，百分比数字同步；不出现黑白块、不闪烁、不崩溃
- 失败记录：缩放中/最大/最小三张截图

- [ ] 结果：

### I2 适应窗口

- 操作：把窗口拉小再点「适应窗口」
- 预期：图片按视口自适应完整可见
- 失败记录：截图

- [ ] 结果：

### I3 滚动条按视口显隐

- 操作：放大到超出视口，观察竖/横滚动条；再缩小回视口内
- 预期：超出时出现对应滚动条、缩回时消失；拖滚动条能看全图；不出现「滚动条显隐导致来回抖动」
- 失败记录：放大/缩小两组截图

- [ ] 结果：

### I4 关闭弹窗

- 操作：点弹窗 ×；再重开一次按 Esc
- 预期：弹窗关闭且主窗口不受影响（不跟着退出）
- 失败记录：关闭后主窗口截图 + 任务管理器进程数

- [ ] 结果：

## 11. 已知风险观察项

### R1 构建期那次未复现的异常退出

背景：在 Windows 11 上对同一份冻结产物做烟测时，出现过一次窗口自行消失（无崩溃对话框、事件日志无条目、无 traceback），后续反复未能复现。

- 观察方式：全程记录每次启动/关闭时刻；一旦窗口自行消失，立即按顺序采集：
  1. 事件查看器 → Windows 日志 → 应用程序，最近 2 分钟内「错误/警告」条目全文（重点看来源 `Application Error`、`Windows Error Reporting`、`.NET Runtime`）
  2. 任务管理器中 `Square-Win7.exe` 是否仍有残留进程（onefile 正常为 2 个）
  3. `%TEMP%` 下是否残留 `_MEI*` 解包目录
  4. 关闭前最后一步操作（页面、按钮、输入内容）
- 判定：能稳定复现 → 记录最小复现步骤；不能复现 → 记「偶发，未复现」，并注明本次连续运行时长与操作次数

- [ ] 结果：

### R2 `python38.dll` 对 `api-ms-win-crt-*` 的依赖

背景：包内已剔除 `api-ms-win-*` 与 `ucrtbase.dll`，这两类 DLL 必须由目标系统提供（KB2999226）。缺失时的报错形态与旧版 3.13 线相同，但根因完全不同。

- 观察方式：启动失败时读完整报错，**记录具体 DLL 名**：
  - 报 `python38.dll` + 「找不到指定的模块」→ 系统缺 UCRT，装 KB2999226
  - 报 `api-ms-win-core-path-l1-1-0.dll` 且系统是 Win7 → 说明拿错了产物（那是 3.13 线，必须给 Win7 用 `Square-Win7.exe`）
  - 报 `MSVCR120.dll` → 装 VC++ 2013 x64
- 判定：本项通过 = 在满足 1.2 前置条件的机器上能启动且无上述任一报错

- [ ] 结果：

### R3 CTk 垫片是否真的生效（Win7 无 shcore）

背景：`customtkinter 6.0.0` 无条件调用 `shcore.SetProcessDpiAwareness` / `shcore.GetDpiForMonitor`，Win7 没有 `shcore.dll`。程序在 `ctk.CTk()` 之前用 `square/gui/dpi.py` 的 `patch_ctk_scaling()` 把这两个方法换掉。

- 先确认这台 Win7 确实没有 shcore（否则本项没有意义）：

```powershell
Test-Path C:\Windows\System32\shcore.dll
```

  预期 `False`。

- 生效的三条可观测证据（三条都要成立）：
  1. 程序能出主窗口，**没有**弹 `OSError [WinError 127]`、`找不到指定的程序` 之类错误 → 说明 `activate_high_dpi_awareness` 已被置空，CTk 没再碰 shcore
  2. 125% DPI 下窗口物理宽高 ≈ 100% 下的 1.25 倍（用第 3 节的 GetWindowRect 命令各量一次）→ 说明 `get_window_dpi_scaling` 走的是 GDI 取值、不是恒为 1
  3. 125% 下文字锐利不模糊 → 说明 `SetProcessDPIAware()` 这一级兜底被命中

- 判定：三条全成立 = 垫片生效。若第 1 条成立但第 2 条不成立（125% 与 100% 尺寸一样），说明缩放从 GDI 取到的是 1.0，界面会偏小，记为缺陷。若第 3 条不成立（文字模糊），说明 DPI 感知没开，区域截图会按错误坐标取像素，必须记缺陷并检查 C 节结果。

- [ ] 结果：

## 12. 回传信息模板

复制下面内容填写后回传，每项都要有「通过/失败/阻塞」，失败项必须给证据位置。

```
## 环境
- Windows 版本（winver 全文）：
- ver 输出：
- ucrtbase.dll / api-ms-win-crt-runtime-l1-1-0.dll / msvcr120.dll 是否存在：
- Get-HotFix KB2999226 输出：
- shcore.dll 是否存在：
- 显示器数量 / 分辨率 / 相对位置：
- 100% 时 AppliedDPI：
- 125% 时 AppliedDPI：
- 被测文件 SHA256（certutil 输出）：
- 被测文件路径：
- 测试日期与测试人：

## 结果汇总
| 编号 | 项目 | 结果 | 证据位置 |
| --- | --- | --- | --- |
| A1 | 冷启动 | 通过/失败/阻塞 | |
| A2 | 二次启动 | | |
| A3 | 关闭与任务栏 | | |
| B1 | 100% 渲染 | | |
| B2 | 125% 渲染（含 W/H 比值） | | |
| B3 | 125% 参数区不裁切 | | |
| B4 | 125% 解码器页 | | |
| C1 | 遮罩与提示 | | |
| C2 | 拖拽框选 | | |
| C3 | 框选过小 | | |
| C4 | Esc 取消 | | |
| C5 | 右键取消 | | |
| D1 | 副屏右侧 | | |
| D2 | 副屏左侧（负坐标） | | |
| D3 | 跨屏框选 | | |
| D4 | 双屏不同分辨率 | | |
| E1 | 复制→画图粘贴 | | |
| E2 | 复制→微信粘贴 | | |
| E3 | 无图剪贴板 | | |
| E4 | 多片复制粘贴 | | |
| F1 | 单码生成 | | |
| F2 | 手机扫码 | | |
| F3 | 参数档位提示 | | |
| G1 | 触发多片 | | |
| G2 | 片数一致性 | | |
| G3 | 大图完整拼图 | | |
| G4 | 极端长文本 | | |
| H1 | 保存二维码 | | |
| H2 | 单码解码往返 | | |
| H3 | 多片往返收敛 | | |
| H4 | 清空收集 | | |
| I1 | 缩放滑块 | | |
| I2 | 适应窗口 | | |
| I3 | 滚动条显隐 | | |
| I4 | 关闭弹窗 | | |
| R1 | 异常退出观察 | | |
| R2 | UCRT 依赖 | | |
| R3 | CTk 垫片生效 | | |

## 失败项详情（每项一段）
- 编号：
- 复现步骤：
- 实际现象：
- 报错原文 / 状态行文字：
- 事件查看器条目（全文）：
- 证据文件路径：
- 是否为必现：

## 其他观察
（任何与本清单不符的行为、耗时异常、界面错位，按「现象 + 截图路径」记录）
```

## 13. 判定标准

- **可发布**：A–I 全部通过，R2、R3 三条证据成立，R1 记为偶发或未出现
- **有条件发布**：仅 B2/B3 之类缩放轻微问题，且功能项全通过（在 README 里写明已知限制）
- **不可发布**：C2/C3/D1/D2 任一失败（区域截图错位）、R3 第 3 条不成立（DPI 感知缺失导致截图坐标错）、或启动失败
