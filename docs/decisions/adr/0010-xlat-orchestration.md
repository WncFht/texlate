# ADR-0010 翻译编排与术语表：kind prompt + 批量协议 + 重试阶梯 + 三级术语

> **状态**：现行
> **日期**：2026-09-15（05 裁决 7/17）| 更新 2026-09-17（非锚定解析撤除 P0）| 更新 2026-09-28（prompt v5：删恒等注入层 + 扁平锚名编号）

## 上下文

段落级翻译要同时解决四件事：LLM 必须逐字保留占位符（契约失败 = 内容静默消失或编译爆炸）、成本要可控（实测 prompt 摊销占输入 68%）、批量协议要可靠（编号对不齐会错配译文）、失败要有降级（不能让一篇论文整体失败）。hjfy 的双轨模型（便宜默认 + 反馈换档重翻）与 LaTeXTrans/texglot/ieeA 的编排件提供了可抄面。

## 裁决

- **Prompt 体系**：6 个 chunk-kind system prompt（v5 起规则扁平编号 `1.–N.` 单行 `**Anchor.**` 锚名条款：Scope 簇 → kind 槽位 → Output → Punctuation and spacing（全角标点）→ Control-sequence boundary → Quality → Untrusted content → Placeholders → Person names（仅 para/abstract）→ Batch protocol 永远压轴；编号仅序位语义，锚名是稳定句柄 → 术语表块永远置末；有 `paper_context` 时任务句后另插摘要锚定块）；模板措辞变更必须 bump `PROMPT_VERSION`（段级缓存键含此值）。前缀缓存友好：system prompt + 术语表 + 占位符契约放前缀并稳定排序。
- **术语表四级**：全局默认表 → `primary_category` 映射领域包 → 文档级过滤取并集烘进稳定 system prompt；**ph 名单行**（v5 替代恒等注入）——`render_placeholder_manifest` 把全部文档占位符压成 `<Glossary>` 末行一条点名册（同 head 连号 `[[MATH_1]]..[[MATH_3]]`、超 4000c 退化无括号 `TYPE×n`），O(类型+连续段) 替代 O(占位符)×O(calls) 重发（实测恒等注入占新输入 ~85%，2026-09-28 网关回归：19506 stress 批 119802→4408 in-tok，152/152 保留）；`autogloss` 自动术语抽取（masked chunk → LLM 域名词表 → 多数表决）。
- **批量协议**：全量 chunk 入批、按字符硬顶 `BATCH_MAX_CHARS=12000` + 成员软顶 `BATCH_MAX_ITEMS=32` 控批（按 `n_req` K 量化等大装箱）+ `[n]` 编号 + `@@` 兜底行 + 整批失败直退单翻（无折半梯子——解析/调用失败的批成员直接落逐段单翻）——批阈值是最大成本杠杆（E20：请求数降 ~10×、总 token 降 ~40%）；超大原子 chunk 先切分再入批（`CHUNK_HARD_LIMIT=6000`）。
- **重试阶梯**：整段 ×2（`previous_validation_error`/`slot_validation_failures` 字段化反馈）→ 行级修复 → slots JSON 兜底（`⟪S0000⟫` 槽位协议，失败槽只重问失败批）→ 三振 `fallback_orig` + `partial` 终态。
- **辅助**：LLM-judge 判未知 env 可译性（temp=0、True/False、few-shot、fail-open）；`recover_copied_tokens`（模型把受保护原文抄回时唯一出现才换回 token）；断点续翻 state 落盘；段级缓存内容寻址。
- HTTP 面：状态码分类表 + `Retry-After` 读取 + provider 无关 `redact()` 脱敏。

## 理由

- E13：prompt 成稿与条款经占位符契约实测（12/12 全绿）；LaTeXTrans 的 `add_placeholder()` 恒等注入技巧直接可抄（v5 以其代价模型翻新：点名册一行替代逐条映射）。
- E20 成本模型：批阈值放宽使请求数 17268→685、p50 总 token 9.1 万→5.4 万——同量级追平 hjfy 经济性的关键路径。
- 证据：主仓 `docs/05` E13/E16/E20；调研档案 `research/latex/prompt-glossary-spec.md`、`research/methods/2026-09-18-xlat-quality-eval.md`。

## 演变

- 2026-09-17：批量协议 P0 修复——**非锚定解析整体撤除**（译文静默错配通道封死）+ `@@` 泄漏闸；同批核销 4 条 P1。
- 2026-09-28：prompt v5——⑤恒等注入层整体撤除（`Glossary.load(placeholders=)` kwarg 删除），改 `<Glossary>` 末行 manifest 名单（`placeholders.render_placeholder_manifest`，退化形无括号防 `BARE_PH_RX` 误判）；规则区从 C1–C10/B1 命名编号改扁平 `1.–N.` `**Anchor.**` 单行条款 + 新增全角标点条款（Punctuation and spacing）；`PROMPT_VERSION` bump `xlat-prompt-v4`→`xlat-prompt-v5`（三层缓存键随转）。网关回归 6/6 格绿：missing/invented/成员重翻/ASCII 标点残留全 0。
- 2026-09-18：batchmodel 改版——控批口径从「约 2000–4000 token ≈ ≤8000 字符」改为字符硬顶 `BATCH_MAX_CHARS=12000` + 成员软顶 `BATCH_MAX_ITEMS=32` + `n_req` 驱动 K 量化等大装箱；整批失败的折半梯子撤除，批成员直退逐段单翻（`pipeline.py`「整批退单翻」）。
- 术语表领域扩面：内建表从 cs 系扩到 8 张 CSV（cs.AI/CV/LG/ML/RO + cond-mat + quant-ph + default），`index.yaml` 做 arXiv category→CSV 映射；种子表来自 LaTeXTrans（MIT）。
- 质量基线待定：qualbench LLM-judge 停在冒烟规模，「优化翻译」尚无质量分布基线——全文级术语一致性、judge 低分重翻（hjfy「反馈换档」对等物）在可做池。

## 现状

实现落在 `xlat/` 包：`prompts.py`（`PROMPT_VERSION` 当前 v5）、`batch.py`（装箱 + 编号协议 + 整批退单翻）、`retry.py`（指数退避 + 四段语义阶梯）、`pipeline.py`（asyncio worker 池 + 首发单飞暖缓存）、`glossary.py` + `autogloss.py` + `terms/`（8 CSV + index.yaml）、`placeholders.py`（编解码与 src↔zh 对账）、`state.py`（段级缓存 + 断点）、`mock.py`（MockTranslator 确定性占位译文）、`client.py`（网关客户端，见 ADR-0011）。
