# e2e-real s40 round-2 对照（leader 三修复验证）

r2 = HEAD 冻结快照（`_src_snapshot_r2`，含 3bdd91c unicode_math_fix +
9c3d4e2 killed_signal + 98cfb11 sandbox profile + 593da2d W11 preamble；
不含 rules-v2 / mouth-gullet 在飞态）。同队列参数：n=40 seed=42 core
swe-2-medium budget 900s。翻译经 `_xlat_state` 复用（同译文），编译/判定全新跑。

## status 分布

| round | clean | fail | partial | reject |
|---|---|---|---|---|
| r1 | 16 | 14 | 6 | 4 |
| r2 | 19 | 15 | 4 | 2 |

chunk 翻译：r1 4354/4365 → r2 4547/4553（2 篇解除 reject 多翻了 ~200 chunk，
miss 11→6）；splice 占位符残留两轮均 0。

## 逐篇翻转

| id | r1 → r2 | 机制 |
|---|---|---|
| 1907.10324 | partial → clean | missing_character 消失——unicode_math_fix 生效 |
| 2211.13013 | partial → clean | SIGPIPE rc=-13 归零——sandbox profile 修复生效 |
| 0707.4363 | reject → partial | latex209_documentstyle 解除（W11 preamble 走 mask_tex 视图），现进入编译，pipe verdict clean、遗留 partial 来自 base 侧 |
| hep-ph/9910403 | reject → clean | 同上，且编译直接 clean（tr 99/100） |
| 2308.12712 | partial → **fail** | ⚠ 见下 |

SIGPIPE/killed/-13：r2 全库 0 命中（r1 三例）。missing_character：r2 全库 0。

## 2308.12712 退化待归因

`nicematrix.sty` 缺失（本地无此 CTAN 包）。r1 pipe 跑 **2 passes**——首引擎
missing_file 后 fallback 到能出 4.4MB PDF 的引擎（588 errors → partial）；
r2 pipe 只跑 **1 pass**，missing_file 即终局 no_pdf → fail。两轮
first_error 相同（hyperxmp/hyperref 序）。疑似 fence/kind 修复改了
missing_file 下的引擎 fallback 语义——若有意收紧（588-error PDF 本不该算
partial），此翻转为口径修正；若非有意，fallback 被吃掉了。

### leader 裁决（2026-09-15）：r2 为真值，r1 partial 系环境偶发

先纠正机制描述：两轮都只有 `pipe-xel` 单引擎，**无 fallback**——
`engine.py:518` `if p > 1 and not pdf.exists(): break`，r1 是 pass-1 产了
PDF 才跑进 pass-2；r2 pass-1 无 PDF 即停。差异在 pass-1 产不产 PDF。

逐项实证（本机现态）：`nicematrix.sty` 全机不存在（kpsewhich/mdfind/
tlmgr 安装日志均无，usermode 树最近安装停在 Sep 14）；同一源码分别在
无沙箱 / r1 旧 profile / r2 新 profile / 无限 stdin 下跑 pass-1，
**全部 emergency stop 零 PDF**。r1 的 4.4MB PDF 任何路径都复现不出。

结论：r1 的 partial 是环境偶发——最可能 stdin 里恰有字节应答了 TeX 的
缺文件问名提示（nonstopmode 下该 `\read` 照发），答上可加载名即继续。
顺带挖出真 bug：`run_process` 不钉 stdin，子进程继承 harness 的 stdin
→ 缺文件行为随父进程飘。已修：`stdin=DEVNULL` → 确定性 emergency
stop → missing_file 归因稳定。即便宽宥 r1 结果，缺包文档产 588-error
PDF 本就该归 fixloop missing_file 域而非计 partial——**r2 的 fail
才是该论文的真实判定**（修包后才谈得上 clean/partial）。

## 剩余 fail 面

r2 非 clean 21 篇：missing_file 15（rules-v2 修复域，14+新增 1）、
latex209_documentstyle reject 2（astro-ph/9703134、astro-ph/9703198——
真 2.09 文档，维持拒译正确）、pipe verdict clean 但 status partial 4
（0707.4363、1003.1464、2403.15096、2410.06025——base 侧遗留，非管线回归）。
