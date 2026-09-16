# repro-2410b — 2410.17957 Mode-B escaped=0 仍编译死

## 1. 致命现场

`bench/work_e2emock/corpus_v3/pipeB-xel/2410.17957/docs/2-introdution.tex:12-28`

源块 = chunk `2:3`（file idx 2, chunk id 3, env=figure, span 4357–4710），被 `\caption{` … `}` 结构包裹：

```text
SRC chunk: 'Enabling BERT on MCUs faces memory challenges: (a) the Flash storage \n    limits … memory;\n    [[COMMENT_14]]\n    (c) for long sequence lengths, … become bottleneck.'
ph_map[[COMMENT_14]] = '% (c) peak memory for BERT-tiny inference with different sequence lengths.}'   ← 展开自带 %} 注释内 }
span 前: '…vation.pdf}\n    \\caption{'   span 后: '}\n    \\label{fig:intro:mem_challenge}'
```

pipeB 实际落盘（replay 逐字节复现一致）：

```text
\caption{[这是译文]
这是译文: (这是译文) 这是译文
    这是译文; (这是译文) 这是译文;
                       ← [[COMMENT_14]] 原位被 drop（空行）
    (这是译文) 这是译文
    这是译文 (这是译文) 这是译文.
[这是译文]
<body 重复一遍>           ← corrector prompt 的 [Translation] 段 echo
[这是译文]
占位符缺失: % (c) peak memory for BERT-tiny inference with different sequence lengths.}}
    \label{fig:intro:mem_challenge}
```

杀点：`占位符缺失: ` 后 `[[COMMENT_14]]` splice 成 `% …lengths.}`，同行紧跟 chunk 外结构 `}` → `%` 把**两个 }** 都注释掉 → `\caption{` 永不闭合 → `\caption@xdblarg` 扫描到文件尾 → `main.tex:347 \input{docs/2-introdution}` 报 early_eof。pipe-xel 同位是 `\caption{这是译文: … [[COMMENT_14]]→%行 … 这是译文.}`——结构 `}` 落在无注释行，正常闭合。

## 2. caught vs recovered 归因

**recovered**（drop_ph 臂，recovered=3 之一）。确定性 replay（`replay-2-3.txt`）：

- `_plan_b(chunk)` = drop_ph（blake2s 定死，`_h("B",canon)`）
- attempt1: mock(src) → drop `[[COMMENT_14]]` → L0 `占位符缺失: [[COMMENT_14]]`
- attempt2 = corrector_fn（`_one_chunk` 恒提供 → `_stage_whole` 第二试必走三段式）→ user = `[Original]\n<src>\n[Translation]\n<zh1>\n[Error]\n占位符缺失: [[COMMENT_14]]` → **MockTranslator 整段照翻**：节标 `[Original]/[Translation]/[Error]`→`[这是译文]`，反馈行 CJK 原样保留；drop_ph 再触发，2 份 `[[COMMENT_14]]`（src echo 体 + 反馈行）里 `ms[h%2]` 丢了 body 那份 → 交付 zh 恰剩反馈行 1 份 → multiset 吻合 → status=ok → splice → 台账记 **recovered**。
- 同机制同篇至少 3 处：docs/6-Experiments.tex:17-22（`占位符缺失: \cite{…}` CITE ph）、:253-258（minipage 内第二处 `\caption{[这是译文]…占位符缺失: $t$}`——结构 `}` 幸存仅因该 ph 展开不带 `%`）。**Mode-B 下凡走 corrector 的 recovered 块结构必脏**（mock 把协议 prompt 当正文翻）。

## 3. 判决

**主判：(a) harness 计量盲区**。`escaped` 只审计交付块的占位符 multiset 通道；本破坏经**内容载荷通道**逃逸——recovery 交付了协议 echo（节标+反馈行+重复 body），multiset 正确而载荷脏。escaped==0 的隐含假设「multiset 吻合 ⇒ 内容忠实」对含位置/结构副作用的破坏不成立。

**次生——暴露两个真实产品缺口**（不是纯 mock 幻影）：

- **L0 无协议回显防御**：交付 zh 含 `占位符缺失:`/节标回显照过 L0。真模型 parrot prompt furniture 是同款通道（`_intercept_leftover_ph` 只管「查无实体」的 token；`[[COMMENT_14]]` 在 src 集合内，穿透 B7 网）。
- **位置敏感占位符无锚定校验**：`_check_ph_anchor`（l0.py:311）已把 BIBITEM 类行首锚定做成 error 先例；COMMENT 类未覆盖——`%` 展开的 ph 脱位同行即可吞掉结构字节，multiset/序守恒都看不见（`src_ph` 还 sorted 掉了位置）。
- 放大器（已在编目 #78）：runaway 错报父文件 `\input` 行 → L2 把错误归到 `7:4`（main.tex）并 revert 了**健康块**，真正脏块 2:3 全程未被识别——本格是该洞的活实例。

## 4. 建议

**(a) 门扩展（harness，e2e_mock_bench.py 台账）**：新增 `dirty` 计数——sabotaged 且交付（`spliced_ok`）的块 zh 命中协议词汇表即记：L0 反馈字面 `占位符缺失:`/`多余\/未识别占位符:`/`占位符疑似拼错`/`结构占位符`/`注释区内臆造占位符` + 重试协议字面 `[Original]`/`[Translation]`/`[Error]`/`[previous_validation_error]`/`slot_validation_failures`（mock 臂反馈行 CJK 原样残留，签名稳定；`[这是译文]` 独行**不作**签名——源里 `[word]` 合法产出同款）。门改 `escaped==0 AND dirty==0`；顺带修一处反向漏账：`partial` 态交付块（`_delivered` 放行）被 `spliced_ok`（严 ok）记成 caught，脏 partial 连 escaped 都不进——ledger 谓词应与 `_delivered` 同口径。

**(b) 产品修复候选（小且真）**：交付侧守卫，与 `_intercept_leftover_ph` 同层——zh 含上述协议/反馈字面 → fault+回退。本例即翻成 caught→原文回退→可编。

**(c) 结构性补强（可选）**：`_check_ph_anchor` 的锚定判据从 BIBITEM 扩到 COMMENT 类：zh 中 `[[COMMENT_n]]` 所在行只允许 `^[ \t]*(\[\[COMMENT_\d+\]\][ \t]*)+$`（`%` 展开吞到 EOL，行内任何非注释邻居都是死字节）。无 echo 时也能拦「真模型把丢的注释 token 补在段尾」这同款杀法。

## 证据包

`replay-2-3.txt` — chunk 2:3 全链确定性 replay（plan_b/delivered zh/events/splice 尾部）；`pipeB-intro-head.txt` / `pipe-intro-head.txt` / `src-caption-block.txt` — 三态对照；`log-eof-error.txt` — main.log 报错段；`echo-sites.txt` — 同篇其余 echo 现场；`record-extract.json` — sabotage/l2/verdict 摘要。
