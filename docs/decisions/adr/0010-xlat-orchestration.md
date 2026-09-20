# ADR-0010 翻译编排与术语表：kind prompt + 批量协议 + 重试阶梯 + 三级术语

> **状态**：现行
> **日期**：2026-09-15（05 裁决 7/17）| 更新 2026-09-17（非锚定解析撤除 P0）

## 上下文

段落级翻译要同时解决四件事：LLM 必须逐字保留占位符（契约失败 = 内容静默消失或编译爆炸）、成本要可控（实测 prompt 摊销占输入 68%）、批量协议要可靠（编号对不齐会错配译文）、失败要有降级（不能让一篇论文整体失败）。hjfy 的双轨模型（便宜默认 + 反馈换档重翻）与 LaTeXTrans/texglot/ieeA 的编排件提供了可抄面。

## 裁决

- **Prompt 体系**：6 个 chunk-kind system prompt（公共条款 C1–C8 + C9 占位符契约永远置末 + C10 人名保留 + kind 子句追加）；模板措辞变更必须 bump `PROMPT_VERSION`（段级缓存键含此值）。前缀缓存友好：system prompt + 术语表 + 占位符契约放前缀并稳定排序。
- **术语表三级**：全局默认表 → `primary_category` 映射领域包 → 文档级过滤取并集烘进稳定 system prompt；**ph→ph 恒等注入**——全部占位符以 `ph→ph` 映射灌进 glossary，把占位符保护变成术语硬约束；`autogloss` 自动术语抽取（masked chunk → LLM 域名词表 → 多数表决）。
- **批量协议**：全量 chunk 入批、按 token 控批（约 2000–4000 token ≈ ≤8000 字符，K 量化等大装箱）+ `[n]` 编号 + `@@` 兜底行 + 整批失败折半梯子退单翻——批阈值是最大成本杠杆（E20：请求数降 ~10×、总 token 降 ~40%）；超大原子 chunk 先切分再入批。
- **重试阶梯**：整段 ×2（`previous_validation_error`/`slot_validation_failures` 字段化反馈）→ 行级修复 → slots JSON 兜底（`⟪S0000⟫` 槽位协议，失败槽只重问失败批）→ 三振 `fallback_orig` + `partial` 终态。
- **辅助**：LLM-judge 判未知 env 可译性（temp=0、True/False、few-shot、fail-open）；`recover_copied_tokens`（模型把受保护原文抄回时唯一出现才换回 token）；断点续翻 state 落盘；段级缓存内容寻址。
- HTTP 面：状态码分类表 + `Retry-After` 读取 + provider 无关 `redact()` 脱敏。

## 理由

- E13：prompt 成稿与 C1–C10 条款经占位符契约实测（12/12 全绿）；LaTeXTrans 的 `add_placeholder()` 恒等注入技巧直接可抄。
- E20 成本模型：批阈值放宽使请求数 17268→685、p50 总 token 9.1 万→5.4 万——同量级追平 hjfy 经济性的关键路径。
- 证据：主仓 `docs/05` E13/E16/E20；调研档案 `research/latex/prompt-glossary-spec.md`、`research/methods/xlat-quality-eval-2026-09-18.md`。

## 演变

- 2026-09-17：批量协议 P0 修复——**非锚定解析整体撤除**（译文静默错配通道封死）+ `@@` 泄漏闸；同批核销 4 条 P1。
- 术语表领域扩面：内建表从 cs 系扩到 8 张 CSV（cs.AI/CV/LG/ML/RO + cond-mat + quant-ph + default），`index.yaml` 做 arXiv category→CSV 映射；种子表来自 LaTeXTrans（MIT）。
- 质量基线待定：qualbench LLM-judge 停在冒烟规模，「优化翻译」尚无质量分布基线——全文级术语一致性、judge 低分重翻（hjfy「反馈换档」对等物）在可做池。

## 现状

实现落在 `xlat/` 包：`prompts.py`（`PROMPT_VERSION` 当前 v4）、`batch.py`（装箱 + 编号协议 + 折半）、`retry.py`（指数退避 + 四段语义阶梯）、`pipeline.py`（asyncio worker 池 + 首发单飞暖缓存）、`glossary.py` + `autogloss.py` + `terms/`（8 CSV + index.yaml）、`placeholders.py`（编解码与 src↔zh 对账）、`state.py`（段级缓存 + 断点）、`mock.py`（MockTranslator 确定性占位译文）、`client.py`（网关客户端，见 ADR-0011）。
