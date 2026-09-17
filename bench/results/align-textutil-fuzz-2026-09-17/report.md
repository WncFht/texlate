# align-textutil-fuzz — align.py + textutil.py 性质 fuzz（交付 tests/test_fuzz_align.py + test_fuzz_textutil.py）

> 2026-09-17 收口。25 用例全绿，0 xfail 在账；1 个确认缺陷在飞期间已被修复（align.py `except Exception` 08c022d），转为回归钉。全离线，ruff 双净。

## 缺陷台账

- [已修复/回归钉] `align.py` `_dest_yfrac`（~line 100）：窄捕获 `(AttributeError, TypeError, ValueError)` 漏 `OverflowError`——畸形 named dest 的巨型整数 `/Top`（`NumberObject(10**400)`，`float()` → OverflowError）穿透捕获，把整侧锚点提取作废（违背「坏 dest 当缺锚」的逐锚隔离语义）。severity：medium（真实语料罕见，但违反单点故障隔离契约）。在飞期间 leader 已放宽为 `except Exception`（08c022d）；回归测试 `tests/test_fuzz_align.py::test_reader_landmarks_giant_int_top` 钉「giant /Top → yfrac=None 只丢该锚，section.1/2 照收」。
- 无其他确认缺陷；无 xfail 挂单。

## 覆盖亮点（全部独立 oracle/不变量，不复用 impl 代码路径）

- align：PdfWriter 合成随机双 PDF（共享锚子集 + FitH/Fit /Top + 图像 XObject + 偶发 /Rotate）→ 结构不变量 + 双调逐字节确定；垃圾/截断/目录/空/缺失路径恒不抛恒合法；stub reader 白盒打畸形 /Top（nan/inf/文本/Null/缺席）+ 异型页高 + 越界页号，单 dest 坏不拖侧、`page.N` 恒排除；`_monotonic_chain` 对 n≤8 全子集暴力枚举证 DP 最优 + 双侧单调；`_multiply` 对 3×3 行向量矩阵乘 oracle（恒等/结合/等价）；`_category` 权重族归口 + 大小写不敏感。
- textutil：`mask_comments` 对独立「反斜杠 run 奇偶」oracle 逐位全等 + 等长 + 幂等；`mask_tex` 三 flag 组合幂等 + 逐字白名单 + 换行位不动，受限 alphabet 上与 `mask_comments` 全等；`lev_capped` 对无上限 DP oracle `== min(真距离, cap+1)` × 20k；`decode_tex`/`sniff` 对抗字节汤（BOM/utf-16/截断 utf-8/gb18030/big5/shift_jis/假声明头）恒不抛 + 确定性 + verdict 形态；合法 UTF-8 round-trip（`\x00`/文首 U+FEFF 为内禀歧义面，发生器回避并注明）；`ph_in_cs_net`/`bare_cs_net` 反对称 + 自净差空 + 键形态/计数上界；`_eol_norm` regex oracle；VERBATIM/DEAD/MATH_CS/CJK 注册表互洽钉。

裁决项：无。
