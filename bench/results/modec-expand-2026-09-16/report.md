# modec-expand-2026-09-16 — Mode B/C 破坏扩样复跑（expand 层 n=80）

## 运行面

- 样本：corpus_v3 expand 层 3800 在盘 → `--layers expand --sample 80 --seed 42`（rng.sample 作用于排序枚举，ids 全量在 sample.json 可复现）。
- 臂：base-xel,pipe-xel,pipeB-xel,pipeC-xel；timeout 240；nice 串行 ~35min。
- 代码面：**工作树直跑**（未设 TEXLATE_SRC），记录自洽于进程启动快照（17:37 装载一次）= **post-90aa823 三 bug 修复、pre-f5da4bf（F2/#77 尚未进工作树）**——与 tailfix 冻结快照口径不同。f5da4bf 与 1d 的 `_rappend_ph` 重构在跑批中途落地/进行，对已加载模块零影响。
- 产出：`bench/results/modec-expand-2026-09-16/`（results/records/matrix/summary/sample/run.log 全）；现场 `bench/work_e2emock/corpus_v3/<cond>/<sid>/`。

## verdict 分布

base-xel 44c/24p/12f；pipe-xel 54c/24p/2f；pipeB-xel 56c/21p/3f；pipeC-xel 47c/31p/2f。

## Mode B 门：escaped==0 PASS（保持）

3123 破坏块 / 10102 事件 → caught 2720 / recovered 403 / **escaped 0**。by_kind：fabricate 1591c/119r、drop 510c/283r、复合 619c/1r。

## Mode C：存活 78/78（100%，保持）

挪位 5368 / 涉块 2904 → splice 2822 / 回退 82。退化 7 篇全为 clean→partial，无断 pdf：1206.0197、1206.0358、1206.0526、2211.04436、2308.12593、2403.05542、2410.17957。

## 与 tailfix（core n=50）对照

escaped 0→0；存活 45/45→78/78；引入 2/50→**8/80（10%，密度上升）**；信号面 80 篇 fault_files=∅、leftover_ph=0（expand 层解析/泄漏全零）。

## 新失败聚类（代表 id + 一行根因假设）

1. **missing_chars = CJK 落 cmr 字体**（5/8 引入：0806.1984、0806.3144、0905.0795、1003.0112、1706.00265）——日志证实 `这/译/文/是` 在 cmr7/8/10 缺字形，中文落进非 ctex 覆盖位。与 #81 modec-misschar 同簇，扩样确认其为引入面主簇。对照 1d 全量 scout：739 格 missing_char 为 xeCJK 兜不到 cmr/psnfss 的系统性字体兜底问题（fixer-cjkfont 车道）。
2. **latex209 inject reject**（引入 1404.0527、hep-th/0408064；partial 共 9 篇）——F3 已知口径，非新缺口。
3. **aux 截断毒化**——1404.0275：`main.tex:117 File ended while scanning \@LN@`（\begin{document} 读 lineno 截断 aux）→ fixloop early_eof r2 自愈 partial。假设：中间 pass 中断留半条 `\def\@LN@column`。
4. **array tabular spec 破坏**——1306.0067：`Extra \or`（`>{\centering\arraybackslash}m{...}` 列 spec）pipe/B/C 三臂同点位确定性 fail、unfixable:syntax。base partial→no_pdf，疑似 segmenter/reconstruct 动列 spec 行。→ 已派 repro-1306。
5. **Mode-B 编译级代价（非 ph 逃逸）**——2410.17957：pipe clean → pipeB **fail**（`\caption@xdblarg` scan EOF，unfixable:early_eof）。45 破坏块 caught/recovered、escaped=0 仍编译死——「零 ph 逃逸 ≠ 零编译代价」实证，门槛口径外的破坏面。→ 已派 repro-2410b。
6. **Mode C `undefined_cs:<截断名>`** ×5/7（texti/endcsn/textb/noind/meth）——挪位 ph 落进 zh 侧 cs 名 → splice 截断，扰动设计内量测代价，非 bug。

## 反向观察

pipeB clean 56 > pipe 54：1404.0209/1404.0275/2410.00059 三篇 partial→clean——B 臂回退英文/重试译文恰好绕开 warn 位（误伤性自愈，非修复证据）。

## 派单去向

- 1306.0067 tabular spec 破坏（pipe 层确定性 fail）→ repro-1306
- 2410.17957 Mode-B recovered/caught 块编译击穿机理（escaped 口径之外的代价面）→ repro-2410b
- 1404.0275 aux 截断——early_eof 已自愈，降级观察项
- missing_chars 主簇（5 id）→ #81 modec-misschar 口径内，字体兜底面归 fixer-cjkfont

未修任何代码、无 git 写。
