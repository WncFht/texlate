# nominations → mechanisms.jsonl 合流报告（2026-09-16）

> 对应 HANDOFF §2.3。输入：`bench/corpus_v3/nominations/` 8 源
> （curator-a..e 提名 24/24/24/45/33 + mechs 提案 24/10/8/13/29；
> hunter-1..3 提名 138/89/181 + 提案 6/14/9）。产出：`mechanisms.jsonl`
> 143→**144 行**、新 fixtures 3 件、断言 +14 条。

## 1. 关键结论：提案的去重早已发生过

113 条 .mechs.jsonl 提案与台账逐条语义比对：**112/113 已覆盖**——台账
W01–W109 就是冲刺期合流的产物，编号按主题序重排，**与提案私编号不一
致**（例：hunter-3 提案 `W07`=plain-gz ↔ 台账 `W37`/`B07`；提案 `W11`=
路径逃逸 ↔ 台账 `W73`）。nominations 侧 `mech_tags` 用的是**台账编号**
（抽查 hunter-3 的 W02/W03 提名语义与台账一致），examples 回填按标签直
接归并是安全的。

提案→台账映射全集（每源 `提案键 → 台账id`）：

- curator-a 24 条 → W75–W97 一一对应（`primitive-redef` 边际并入 W45 notes：
  `\def` 重定义 TeX 原语 `\sp\sb\l\j` 比命令级重定义更底层）
- curator-b 10 条 → W08/W15–W23；curator-c 8 条 → W07–W14；
  curator-d 13 条 → W24–W36；curator-e 29 条 slug-id → W37–W61 全覆盖
- hunter-1 6 条 → W37/W66–W70；hunter-2 14 条 → W98–W109
  （`typein-interactive` 并入 W78——notes 原已含 `\typein` 判据）
- hunter-3 9 条（私编 W07–W15）→ W37/W71/W72/W13/W73/W52/W26/W74/W03

**唯一真新增 = W110**「\input 循环/超深链撞深度哨兵」：15 篇 verified 提
名的 `input_depth=32` 特征值（n_tex 小却深度满格 → 自环/互环代理指标），
flatten `_seen` 祖先栈已断环（行为面 covered），登记为独立机制便于语料
检索。examples 取 cond-mat/0501221、physics/0501018、hep-ex/0605023 等。

## 2. 台账终态

- 144 行，mech_id 唯一；`examples` 回填 **131 条**（verified 提名簇多样优
  先、cap 6）；`sources` 溯源 **128 条**（提名源 ∪ 提案源）。
- status 规范化：`found`→`partial` ×9（hunter-2 批，对齐 docs/09 词表
  wanted|partial|covered|exhausted）；B01–B07 全部 `wanted`→`partial`
  （verified 提名数 ≥ quota：80/59/64/38/88/28/62 vs 30/30/30/-/~25 级）。
- 终态分布：partial 119 + covered 25。
- 边际并入 notes：B07（单 gz 可承载 plain TeX）、W26（负载可为 vendored
  sty/cls）、W45（原语级重定义）。

## 3. QC 记录

- hunter-3 有 24 行 `verified="feature"`（非人工开文件）——examples 只收
  `verified==true`，feature 行不进证据位。
- 标签噪声存在：cs/0501042、1012.5411 打 W02 但 justification 述非 UTF-8
  （应为 B02）。examples 字段按标签归并未逐条复核语义——个别条目的
  examples 可能含噪声邻位，引用时注意。
- `curator-d 的 39 签名普查底材 /tmp/curd/sigmap.tsv` 在本机 /tmp 易失，
  未入台账；需要时按 W-mechanisms 的 detection 字段重扫。

## 4. fixtures 配额决策（新增 3 件 / +14 断言，全绿）

选型原则：**只收现行行为正确且值得锁的机制**——断言矩阵 fail=回归，红
fixture 会把已知缺陷固化成基线噪声。`bench/fixtures/`：

- `tricky-w.tex`（11 断言）：W11 usepackage 跨行夹注释、W15 enddoc 尾散
  文、W50 `\comment{}` 吞块、W67 `\begin {env}` 空格、W75 中缀分式、
  W82 无括号数学参数、W83 cs 换行分隔参数、W84 行尾%参数内拼接、W90
  区间键 cite、W91 `\-` 断词、W92 注释内伪定界符
- `tricky-w73/`（2 断言）：`\input{../shared/}` paper 内逃逸 +
  `\input{../../escape-outside.tex}` 出 paper 根——**锁现行语义：
  `_resolve` 字面跟随 `../`**，逃逸在 sandbox 边界外可解析
- `tricky-wenc.tex`（1 断言）：W72 混合编码字节件（latin1 `é` + 合法
  UTF-8 `é` 同文）——断言只锁 latin1 侧存活；identity 基准由
  `errors="replace"` 改为 `decode_tex`（与管线读取同源，对既有 UTF-8
  fixtures 输出不变）

harness 改动：`run_fixture` 的 flat 基准换 `decode_tex(path.read_bytes())`
（管线读取路径同源化，非 UTF-8 件才可对拍）；新增 assert_w/assert_w73/
assert_wenc + W_IDS/W73_IDS/WENC_IDS 登记 + 两个 matrix-complete 哨兵。

**落选与理由**：W27 changes `\deleted`、W24/W25 算法/代码 DSL、W07
comment env——现行行为会把体内容当可译文本（机制要求剔除/保护），断言
写绿=锁 bug，留为 ledger partial + 下方 action items。W73 越根外解析依
然允许（fixture 锁的是行为而非认可——是否加根界钳制是 flatten/gullet
侧决策）。

## 5. action items（对工程的直接影响）

- **latex 层真 bug**：filecontents 在 `\documentclass` 前/后 preamble 位
  → 整个 body chunk recall=0；在 body 内 → 吃掉前一段。W26 台账已注明
  「早于常规正文边界」，实测证实——segmenter v2 preamble 段应把
  filecontents 体当 literal/保护块处理。
- **flatten._resolve 无根界钳制**：`Path(dir)/'../x.tex'` 字面跟随可越
  archive 根（W73 fixture 已锁现行行为）；另有 basename 兜底会把
  `../BiblioMacros/macros.tex` 静默解析到根内同名文件——两行为都在
  fixtures 可复现范围内，收敛决策归 flatten/gullet 单源化一并处理。
- **features 层**：W108 `features.minted` 正则撞作者 `\mint` 宏、W109
  rg 命中注释掉的包名、non_utf8 flag 落点不定——detection 字段已在台账
  写明，features 实现侧要分档（宏定义内命中 ≠ 包载入）。
- **normalize 层**：W72 混合编码/W13 声明不符已由 decode_tex 判定链承接
  （EncodingVerdict 归因）；本 fixture 只锁单码现状，分档转码落地后
  W72_mixed_decoded 的断言面可收紧。
- **fixtures 之外的语料配额**：B04/B05 级 wanted 条目提名已超 quota，
  后续扩样（booster 层）可优先覆盖 W 系 partial 中 examples<3 的条目
  （W12/W14/W19/W20/W22/W30/W33/W34 等长尾）。

## 6. 复现

合流脚本为一次性工具（`/tmp/merge_mechs.py` 已弃）：台账可由
`git diff bench/corpus_v3/mechanisms.jsonl` 审计；fixtures 回归跑
`uv run pytest tests/test_bench_regression.py -k 'tricky or w73 or wenc or test_w'`（79 项全绿）。
