# armed-metric — dirty harness 扩 armed channel 计量

> 2026-09-16。落 `bench/py/e2e_mock_bench.py` 单文件（ruff 双净）。来源：modec-postfix 指出的残余盲区——`_dirty_hits` 只扫 zh，src 自带协议签名时 echo 与忠实译文裸包含不可区分。

## 口径（per-signature 集合语义）

- `src_legit` = `_dirty_hits(r.source)`——src 块自带签名（raw containment）。
- `armed` = delivered ∧ src_legit 非空——盲区库存，只观测不进门槛；`armed_zh` = 其中 zh 同命中（ambig 非空）的不可判定实例化数。
- `dirty` = delivered ∧ (zh_hits − src_legit) 非空——src 解释不了的命中才算判定性 echo；zh∩src 归入 ambig 不再误计 dirty。
- `delivered` 谓词前置循环顶；**dirty/armed 按全 delivered 块记账**（原 dirty 仅 sabotaged 子集——真模型 parrot 可在非破坏块回显，门槛守交付载荷清洁）。caught/recovered/escaped 仍 sabotage 口径；by_kind 是 sabotaged 交叉表（加 armed 列）。leader 已裁决采纳此扩口径（旧基线数值不变：全部 cohort 非破坏块 zh 命中为 0）。
- 门槛不变 `escaped==0 AND dirty==0`；summary 加 armed 行 + `armed chunk ids:`。

## 实证

- `armed-synth`（tmp/armed_corpus，src chunk 内嵌 [Original]/[Translation]）：armed=1、armed_ids=['0:0']、dirty=0、gate PASS——入账且不进门槛。
- `armed-smoke2` n=3 corpus39 pipeB：sabotaged=142、escaped=0、dirty=0、armed=0。
- `armed-case` 2112.00059（全语料唯一含签名的 v3 工程，`[Original]`×10）：armed=0——签名全在 `\subfloat[Original]{...}` 参数位，不进 chunk 文本。
- **基线结论：无需重跑 modec**。文件级扫描 corpus39 0/39、corpus_v2 0/112、corpus_v3 1/3972；chunk⊆file → n=80 cohort armed 实测即 0。

## 产物

四个冒烟结果目录同 commit 入库：armed-synth / armed-smoke / armed-smoke2 / armed-case。
