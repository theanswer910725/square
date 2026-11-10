# Win7 验收测试数据清单

Author: Lin。
Date: 2026-11-10 21:40:00

> 片数是本机用项目自身 `square.core.codec.encode()` 实测算出来的，不是估算；重跑脚本见同目录 `gen_testdata.py`。

## 实测条件

| 项 | 值 |
| --- | --- |
| 解释器 | Python 3.8.10 (`.venv-win7`) |
| segno | 1.6.6 |
| 纠错率 | 中等（M，2331 字节/单码） |
| 清晰度 | 清晰（1000 字符/片） |
| 策略 | 自动（推荐） |
| 每片有效载荷 | 976 字符（1000 − 24 帧头） |

**界面保持默认值（中等 + 清晰 + 自动）时，下表的片数与实测一致。**改动清晰度或纠错率会改变片数，属正常，见文末附表。

## 文件清单

| 条目 | 文件名 | 编码 | 换行 | 字符数 | 字节数 | 预期编码结果 | 用途 | SHA256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | `F1_single_cn.txt` | UTF-8 with BOM | 无（单行） | 7 | 24 | 单码（1 片，single-plain） | 生成器输入框直接粘贴。F1 生成、F2 手机扫码、H1 保存、H2 往返、E1/E2 复制都从这张开始 | `FF34CA420C6F05A2845EF6A0653C238BDE8C4DF9C274B833115DC0E559673465` |
| F2 | `F2_single_mixed.txt` | UTF-8 with BOM | 无（单行） | 42 | 67 | 单码（1 片，single-plain） | 手机扫码用这张：中/英/emoji 混排，验证 UTF-8 与 ECI 是否被手机端正确识别 | `75602CB4FC6FD60B2E97BE1E1674F3ECB17547B2F4F0AE55037F1A92EF8DC831` |
| F3 | `F3_long_cn_hint.txt` | UTF-8 with BOM | 无（单行） | 1200 | 2919 | 多片（4 片，plain-split） | 切「纠错率=较高」+「清晰度=紧凑」时观察档位被压低的提示；文本本身会分片，可顺带确认分片数量 | `34F46BE5530C7B01B798565973D17AB7DE2BE9DB1FE50C8F5FDB948191D30C11` |
| G1 | `G1_multi_5parts.txt` | UTF-8 with BOM | 无（单行） | 2929 | 2932 | 多片（5 片，plain-split） | 不可压缩十六进制随机串，固定 5 片；G1 生成、H3 收集、E4 复制都用它 | `8BF65926247D45FB2C527962F0EAB71967304B55826DCA5DB32A27E2F000CAEC` |
| G2 | `G2_multi_5parts.txt` | UTF-8 with BOM | 无（单行） | 2929 | 2932 | 多片（5 片，plain-split） | 与 G1 内容不同的另一份 5 片数据，两条线（3.8/3.13）各生成一次对比片数 | `CDB98ED141579285FDF70E62F9F6983062FF7DB05D4415F0151EFB6F61A0AB07` |
| G2 | `G2_multi_8parts.txt` | UTF-8 with BOM | 无（单行） | 5125 | 5128 | 多片（8 片，plain-split） | 8 片档：G2 片数对比、G3 大图弹窗、I1–I3 缩放与滚动都建议用这张（片多，视觉更明显） | `F7A53EB15800B6E990889A5371C59012CE12591E9FEDA26ADD3A551FAEA4515B` |
| G4 | `G4_extreme_20000.txt` | UTF-8 with BOM | 无（单行） | 20000 | 20003 | 多片（28 片，plain-split） | 极端长文本（20000 字符），验证大批量分片不崩、提示明确 | `CB1921A0A16B2D26D697CDFDBAA48C9674179C376EE8114AA2DDF6EDD9C2B94C` |
| H2 | `H2_roundtrip_multiline.txt` | UTF-8 with BOM | CRLF | 93 | 198 | 单码（1 片，single-plain） | 多行含空行：验证解码往返后换行与空行是否原样保留 | `C6BB3F09EE2F463694FA28550A0317862CB8DB5B38A83714E2641416E9709E54` |

## 编码与换行

- 所有 `.txt` 均为 **UTF-8 带 BOM**（3 字节 `EF BB BF`）。带 BOM 是为了 Win7 记事本能正确显示中文；记事本全选复制时不会把 BOM 带进剪贴板，粘贴内容与「字符数」一致。
- 除 `H2_roundtrip_multiline.txt` 用 **CRLF** 外，其余都是**单行文件，完全没有行尾字符**（不是 LF）。
- 所有文件**末尾都没有多余换行**：Ctrl+A / Ctrl+C 得到的就是「字符数」那么多字符。
- 字节数 = 文件实际字节（含 3 字节 BOM 与 CRLF 的 2 字节）。若把这些文件另存为 ANSI 或 LF，字节数会变，`certutil` 的哈希也会对不上。

### 校验方法

```bat
rem 逐个核对大小与哈希（在测试数据目录内执行）
for %f in (*.txt) do @certutil -hashfile "%f" SHA256 | findstr /v "哈希 CertUtil"
```

```powershell
rem PowerShell 2.0 可用：字符数与字节数
Get-ChildItem *.txt | ForEach-Object {
  $t = [System.IO.File]::ReadAllText($_.FullName)
  '{0}  {1} chars  {2} bytes' -f $_.Name, $t.Length, $_.Length
}
```

## 复用关系（不是缺文件）

| 条目 | 使用哪个文件 | 说明 |
| --- | --- | --- |
| H1 | `F1_single_cn.txt` | 单码保存，输入内容同上 |
| H2 | `F1_single_cn.txt`、`H2_roundtrip_multiline.txt` | 先跑单行，再跑多行含空行 |
| H3 | `G1_multi_5parts.txt` | 5 片：大图弹窗「保存原图」后「选择图片」选这张拼图，或逐片区域截图送入 |
| E1 / E2 | `F1_single_cn.txt` | 复制全部后粘到画图 / 微信 |
| E4 | `G1_multi_5parts.txt` | 多片拼图复制 |
| I1–I4 | `G2_multi_8parts.txt` | 8 片拼图，缩放/滚动观察更明显 |

## 附表：改清晰度后的片数（同样实测）

| 文件 | 紧凑 | 平衡 | 清晰（默认） | 最清晰 |
| --- | --- | --- | --- | --- |
| `G1_multi_5parts.txt` | 3 | 4 | 5 | 6 |
| `G2_multi_5parts.txt` | 3 | 4 | 5 | 6 |
| `G2_multi_8parts.txt` | 5 | 6 | 8 | 10 |
| `G4_extreme_20000.txt` | 16 | 21 | 28 | 37 |

> 纠错率也会影响：最高（H）下单码容量 1273 字节、每片载荷降为 1249，片数会再增加。
