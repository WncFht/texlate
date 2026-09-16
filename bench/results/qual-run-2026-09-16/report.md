# qualbench — 译文质量 LLM-judge

- judge_model: `swe-2-medium`（mock=False）
- source: state · seed=42 · papers=30 · judged=360 chunks
- started: 2026-09-16T06:35:58.215577+00:00

## 总分（model × judge）

| model × judge | n | mean | median | 分布 5→1 |
| --- | --- | --- | --- | --- |
| swe-2-medium × judge=swe-2-medium | 360 | 4.85 | 5 | 5:313 4:41 3:6 2:0 1:0 |

## flag 频率（全体 judged chunk）

- `term_inconsistency`: 17
- `untranslated_spans`: 11
- `grammar`: 2

## per-kind

| kind | n | mean | median | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| caption | 119 | 4.81 | 5 | 5:100 4:15 3:4 2:0 1:0 | term_inconsistency×8, untranslated_spans×5, grammar×2 |
| para | 138 | 4.81 | 5 | 5:114 4:22 3:2 2:0 1:0 | term_inconsistency×8, untranslated_spans×6 |
| section_title | 103 | 4.96 | 5 | 5:99 4:4 3:0 2:0 1:0 | term_inconsistency×1 |

## per-paper

| paper | model | n | mean | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| 0707.4363 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 0707.4465 | swe-2-medium | 12 | 4.75 | 5:9 4:3 3:0 2:0 1:0 | — |
| 0905.4439 | swe-2-medium | 12 | 4.75 | 5:10 4:1 3:1 2:0 1:0 | term_inconsistency×1, untranslated_spans×1 |
| 0905.4781 | swe-2-medium | 12 | 4.83 | 5:10 4:2 3:0 2:0 1:0 | — |
| 0905.4793 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 1003.1383 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 1003.4522 | swe-2-medium | 12 | 4.75 | 5:10 4:1 3:1 2:0 1:0 | term_inconsistency×1, grammar×1 |
| 1109.5963 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 1206.5428 | swe-2-medium | 12 | 4.75 | 5:9 4:3 3:0 2:0 1:0 | term_inconsistency×1 |
| 1206.5702 | swe-2-medium | 12 | 4.75 | 5:10 4:1 3:1 2:0 1:0 | grammar×1, untranslated_spans×1 |
| 1306.2177 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | — |
| 1306.5813 | swe-2-medium | 12 | 4.67 | 5:8 4:4 3:0 2:0 1:0 | term_inconsistency×2 |
| 1404.5720 | swe-2-medium | 12 | 4.75 | 5:9 4:3 3:0 2:0 1:0 | untranslated_spans×2 |
| 1404.5834 | swe-2-medium | 12 | 4.67 | 5:9 4:2 3:1 2:0 1:0 | untranslated_spans×2 |
| 1404.6133 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 1502.01820 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 1511.02820 | swe-2-medium | 12 | 4.83 | 5:10 4:2 3:0 2:0 1:0 | — |
| 1511.06879 | swe-2-medium | 12 | 4.83 | 5:10 4:2 3:0 2:0 1:0 | term_inconsistency×1, untranslated_spans×1 |
| 1803.09046 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 2105.03740 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 2105.03750 | swe-2-medium | 12 | 4.58 | 5:8 4:3 3:1 2:0 1:0 | term_inconsistency×3, untranslated_spans×1 |
| 2105.11495 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 2203.04385 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 2203.13012 | swe-2-medium | 12 | 4.92 | 5:11 4:1 3:0 2:0 1:0 | term_inconsistency×1 |
| 2211.04574 | swe-2-medium | 12 | 4.83 | 5:11 4:0 3:1 2:0 1:0 | term_inconsistency×1 |
| 2308.12597 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| 2410.17967 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |
| hep-lat/0111009 | swe-2-medium | 12 | 4.58 | 5:7 4:5 3:0 2:0 1:0 | untranslated_spans×2 |
| hep-ph/0111218 | swe-2-medium | 12 | 4.83 | 5:10 4:2 3:0 2:0 1:0 | term_inconsistency×1, untranslated_spans×1 |
| hep-ph/9910403 | swe-2-medium | 12 | 5.00 | 5:12 4:0 3:0 2:0 1:0 | — |

## 最差 chunk（score 升序前 30）

| paper | chunk | kind | score | flags | note |
| --- | --- | --- | --- | --- | --- |
| 1206.5702 | 0:7 | caption | 3 | grammar | 定语从句译反：应为不确定性原理使人规避分支定域性之后果 |
| 2211.04574 | 0:55 | caption | 3 | term_inconsistency | throughput 误译为“吞吐量”，光学语境应为“通量/透过率” |
| 0905.4439 | 0:3 | para | 3 | term_inconsistency | bolometric luminosity mistranslated as 玻尔兹曼光度 (Boltzmann); s |
| 1404.5834 | 0:12 | para | 3 | untranslated_spans | 'chicken or the egg' 未译，应为“先有鸡还是先有蛋” |
| 1003.4522 | 0:22 | caption | 3 | grammar | 多处语序生硬；末句REF位置错乱（应为图~[[REF_240]]的图注） |
| 2105.03750 | 0:85 | caption | 3 | term_inconsistency | 'bulge' mistranslated as 银晕 (halo); should be 核球/银核 |
| 1109.5963 | 0:55 | caption | 4 | term_inconsistency | “能谱”应为“横动量谱”，transverse momentum spectrum非能量谱 |
| 1306.5813 | 0:16 | caption | 4 | term_inconsistency | 'optoacoustic' rendered 声光 (acousto-optic); likely should be |
| 1511.06879 | 0:43 | caption | 4 | term_inconsistency | "lattices" rendered as 格点 (sites); better 晶格/点阵 to distingui |
| 2105.03750 | 0:3 | caption | 4 | term_inconsistency | RR Lyrae 标准译名为天琴座RR型变星，其余准确 |
| 1206.5428 | 0:118 | para | 4 | term_inconsistency | 'more-peripheral' rendered 更外围; standard term is 更边缘(碰撞) |
| hep-ph/0111218 | 0:24 | para | 4 | term_inconsistency | 'energy definition' rendered as 能散度定义; 'isobar' as 同量异位素 is  |
| 2105.03740 | 0:18 | para | 4 | term_inconsistency | "pockets" rendered literally as 口袋; 费米面口袋/极值轨道 clearer |
| hep-lat/0111009 | 0:9 | caption | 4 | untranslated_spans | 'Ref.' left in English; could be '文献' |
| 1404.5720 | 0:24 | caption | 4 | untranslated_spans | 'trombone' left in English; otherwise accurate and fluent |
| 1511.06879 | 0:50 | caption | 4 | untranslated_spans | 'panel' left in English; otherwise accurate and fluent |
| 2105.03750 | 0:78 | caption | 4 | term_inconsistency | 'quality class'译作'质量等级'易与质量(mass)混淆，宜作'品质等级' |
| hep-lat/0111009 | 0:22 | para | 4 | untranslated_spans | 'hairpin' left in English; otherwise faithful and fluent |
| 2203.04385 | 0:24 | para | 4 | term_inconsistency | “emission measure”宜译“发射量度/发射积分”，译作“发射量”欠准 |
| hep-ph/0111218 | 0:6 | para | 4 | untranslated_spans | 'twist-2' left in English; otherwise accurate and fluent |
| 1306.5813 | 0:4 | para | 4 | term_inconsistency | qudit 译为“量子位”易与 qubit 混淆，建议保留 qudit 或译“多维量子位” |
| 2203.13012 | 2:58 | section_title | 4 | term_inconsistency | “Feynman”宜译作“费曼图”，保留英文略欠规范 |
| 1003.4522 | 0:14 | para | 4 | term_inconsistency | 'unblended' rendered as 未混合; better 未受谱线混合/无混线 |
| 2105.03750 | 0:54 | para | 4 | untranslated_spans | 'walkers' and 'burn-in' left in English; otherwise accurate  |
| 0905.4439 | 0:102 | caption | 4 | untranslated_spans | units 'counts s' left in English; otherwise accurate and flu |
| 1206.5702 | 0:29 | para | 4 | untranslated_spans | 'technical appendix' left in English; should be 技术附录 |
| 1404.5720 | 0:23 | caption | 4 | untranslated_spans | 'trombone' left in English; otherwise accurate and fluent |
| 1404.5834 | 0:9 | para | 4 | untranslated_spans | \textit{chicken or the egg} left in English; otherwise faith |
| 0707.4363 | 0:43 | caption | 4 | term_inconsistency | autocorrelation 标准译法为“自相关”，译作“自关联”略欠规范 |
| 0905.4793 | 0:93 | para | 4 | term_inconsistency | “component”译为“组件”，网络语境宜用“连通分量”；其余准确流畅 |

## B4b 补充分析（post-hoc，对照 e2e-real-n100-postcutover results.json）

### 抽样设计

source=state（`bench/work_e2ereal/_xlat_state`），按 pipe-fix verdict 分层定抽样：clean 12 / partial 7（全取，母体仅 7）/ fail 11，共 30 篇；`--per-paper 12 --seed 42`，kind 轮转保类型多样，得 360 chunk（para 138 / caption 119 / section_title 103）。judge 与被评模型同为 swe-2-medium（judge temperature=0.1）。

### verdict 分层 × 质量

| pipe-fix verdict | papers | chunks | mean | 分布 5→1 | 带 flag | flags 明细 |
| --- | --- | --- | --- | --- | --- | --- |
| clean | 12 | 144 | 4.89 | 5:130 4:12 3:2 2:0 1:0 | 9 (6.2%) | term_inconsistency×4, untranslated_spans×4, grammar×1 |
| partial | 7 | 84 | 4.87 | 5:74 4:9 3:1 2:0 1:0 | 7 (8.3%) | term_inconsistency×4, untranslated_spans×2, grammar×1 |
| fail | 11 | 132 | 4.80 | 5:109 4:20 3:3 2:0 1:0 | 14 (10.6%) | term_inconsistency×9, untranslated_spans×5 |

质量随编译 verdict 分层基本平坦（4.80–4.89）——翻译质量在编译上游，fail 篇的判分不差反略低只因抽样波动；**编译 fail 不等于译文差**，反之亦然。

### 六类 flag 发生率（hjfy 类目）

| flag | chunks | 发生率 |
| --- | --- | --- |
| `untranslated_spans` | 11 | 3.1% |
| `placeholder_broken` | 0 | 0.0% |
| `term_inconsistency` | 17 | 4.7% |
| `over_translation` | 0 | 0.0% |
| `hallucinated_content` | 0 | 0.0% |
| `grammar` | 2 | 0.6% |

### B4b 核心问题：L0 契约 ok 但质量差的比例

- 样本 30 篇 paper 级 L0 契约（pipe-xel.translate）：2962 chunk 全部 leftover_ph=0、parse_fail=0；judged 360 块 ph_missing/ph_invented 全 0 → **契约保持率 100%**。
- 契约 ok 且质量差（score≤3 或带 flag）：**30/360 = 8.3%**；其中 score=3 仅 6 块（1.7%），无 score≤2。
- 契约 ok 且质量好（score=5 无 flag）：313/360 = 86.9%。

结论：B4b 要回答的缺口真实存在但小——L0 结构契约全绿时，仍有 ~8% chunk 被 judge 挑出质量瑕疵，**全部是「轻症」**：术语选词不标准（term_inconsistency 4.7%，如 throughput→吞吐量、bolometric→玻尔兹曼光度、bulge→银晕）与低危英文残留（untranslated_spans 3.1%，多为 Ref./trombone/walkers 类单词而非整句漏翻）。幻觉/增译（hallucinated_content）与占位符破坏（placeholder_broken）零检出。

### score≤3 失败模式摘录（全 6 例）

**1206.5702 `0:7` caption score=3 flags=['grammar']**

> EN:  {\bf The Mach-Zehnder interferometer}: Branch locality, the restriction whose consequences the uncertainty principle enables escape from, states that if the (p
>
> ZH: {\bf 马赫-曾德尔干涉仪}：分支定域性——正是其限制使得不确定性原理的后果得以被规避——指出，如果（可能是后量子的）粒子以概率 1 将被发现于干涉仪的某一分支中，那么对另一空间上不相交分支的操作不能改变该粒子的（操作意义上的）状态。
>
> judge: 定语从句译反：应为不确定性原理使人规避分支定域性之后果

**2211.04574 `0:55` caption score=3 flags=['term_inconsistency']**

> EN: Detector throughput used in total noise calculation \:   Key: nm = nanometres. Estimates of throughputs by wavelengths obtained from private communications with
>
> ZH: 总噪声计算中使用的探测器吞吐量 \: 说明：nm = 纳米。各波长吞吐量的估计值来自与 PLATO 仪器信号与噪声预算团队成员的私人通信。
>
> judge: throughput 误译为“吞吐量”，光学语境应为“通量/透过率”

**0905.4439 `0:3` para score=3 flags=['term_inconsistency']**

> EN: Active galactic nuclei (AGN) are believed to be powered by accretion of gas onto the black hole located at the centre of galaxies.  The AGN bolometric luminosit
>
> ZH: 活动星系核（AGN）被认为是由气体吸积到位于星系中心的黑洞上提供能量的。AGN 的玻尔兹曼光度（L[[MATH_8]]）取决于质量吸积率以及引力能转化为辐射的效率。在这一图景中，黑洞产生的光度存在一个物理上限，即爱丁顿极限（L[[MATH_9]][[MATH_10]]1.3[[MATH_11]]10[[MATH_12]
>
> judge: bolometric luminosity mistranslated as 玻尔兹曼光度 (Boltzmann); should be 热光度

**1404.5834 `0:12` para score=3 flags=['untranslated_spans']**

> EN: The \textit{chicken or the egg} dilemma can be represented as the superposition of two mutually exclusive entities [[MATH_22]] and [[MATH_23]] in the non-spatia
>
> ZH: \textit{chicken or the egg} 困境可以表示为两个互斥实体 [[MATH_22]] 与 [[MATH_23]] 在非空间维度 [[MATH_24]] 上的叠加：
>
> judge: 'chicken or the egg' 未译，应为“先有鸡还是先有蛋”

**1003.4522 `0:22` caption score=3 flags=['grammar']**

> EN: 
[[LABEL_230]]
Neutron-capture abundance distributions in \bd\ and \hd.
Detections are indicated by filled symbols, and upper limits
are indicated by downward-f
>
> ZH: 
[[LABEL_230]]
\bd 中的中子俘获丰度分布\ 和 \hd 。
探测结果以实心符号表示，上限
以朝下的空心三角形表示。
顶部面板中的粗蓝线代表核坍缩
超新星高熵中微子风的计算结果，来自 [[CITE_231]]（根据其图~3估计），归一化至 
Sr（[[MATH_232]]~38).
每个面板中的实线表示
>
> judge: 多处语序生硬；末句REF位置错乱（应为图~[[REF_240]]的图注）

**2105.03750 `0:85` caption score=3 flags=['term_inconsistency']**

> EN: Top: eccentricity distribution of the bulge RRL binary candidate sample.
    Middle: distribution of the (logarithmic) mass function. In addition, the
    purpl
>
> ZH: 上图：银晕 RRL 双星候选样本的偏心率分布。
    中图：（对数）质量函数的分布。此外，紫色、黄色和青色曲线分别表示伴星质量为 0.6、0.2 和 [[MATH_1033]] 时预期的质量函数分布，这些取值被选取以重现观测样本的三个峰。
    注意，顶部坐标轴给出的是在假设 RRL 质量为 [[MATH_1034
>
> judge: 'bulge' mistranslated as 银晕 (halo); should be 核球/银核

### 复现

```sh
uv run python bench/py/qualbench.py run --source state \
  --state-root bench/work_e2ereal/_xlat_state \
  --ids <30 ids 见 run_meta.json papers> --per-paper 12 --seed 42 \
  --judge-model swe-2-medium --concurrency 2 \
  --out bench/results/qual-run-2026-09-16 --tag qualrun
uv run python bench/py/qualbench.py report bench/results/qual-run-2026-09-16
```

records.jsonl append 续跑：同 key 已有 score 跳过，error 行重跑。本节为 post-hoc 追加，`report` 子命令重生成会覆盖——先 `report` 再重跑本节脚本可复原。