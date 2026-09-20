# ADR-0012 缓存与共享译文：三级本地缓存 + share_key 七组分 + 零 token 信任模型

> **状态**：现行（公共 registry 已否决——见 ADR-0019）
> **日期**：2026-09-15（05 裁决 9）| 更新 2026-09-16（zh.pdf 改可选）、2026-09-18（registry 否决）、2026-09-20（隐式命中接线）

## 上下文

hjfy 的「已译论文匿名随便看」是平台付费 token 换来的中心化资产。texlate 走 BYOK，同一篇论文会被 N 个用户重复付费翻译——共享缓存把已付 token 沉淀成社区资产，但译文来自不可信对端，直接渲染等于把未知字节喂给阅读器。需要回答：键怎么寻址（版本漂移、术语表差异）、包怎么分发、消费端凭什么敢用。

## 裁决

- **本地三级缓存**：源级 `arxiv_id@resolved_ver` → e-print 解压树；产物级 `sha256(id@ver|model|pipeline_ver|lang)` → 整任务 dedup 复用（`per_key` scope 可按凭证指纹分桶，消除缓存存在性 oracle）；段级 `{cfg16}:{seg_key}` → 单 chunk 译文（cfg 指纹含 model|prompt_ver|lang|glossary）。dedup 只复用 done 任务产物，partial 不传播毒。
- **share_key 七组分**：`sha256(arxiv_id|resolved_ver|model|prompt_ver|target_lang|glossary_hash|pipeline_ver)`——与 dedup 键同构但**永不拼凭证/租户成分**；model 组分是「译文生产者」特性而非缺陷（用户只检索信任的模型池）；术语表进键天然隔离私有配置。
- **包格式**：`{share_key}.share.zip` = `manifest.json`（key_parts 自校验 + artifacts sha256/bytes 对账）+ `dual.json`（信任边界载荷：`chunks[]` 的 `src_file`/`en`/`zh` 逐段对）+ `zh-src.zip`（冗余形态，人可直接取用）+ 可选 `zh.pdf`（贡献者侧编译证据，非交付物）。
- **信任模型（核心）**：下载译文**不直接渲染**——本地照常 fetch 源码，`dual.json.chunks[]` 按 `src_file`+`en` 对账到本地 parse chunks，对不上回 `fallback_orig`；splice/L0/L1/compile/judge **全部本地重跑**；编译不过按普通 partial/reject 收口。恶意包最坏结果 = 浪费一次编译，不会产出坏 PDF、不消耗 token（v1 零 token 结构承诺：导入链永不回退自译补段）。
- **上传 opt-in**：默认关；Reader 按钮/`POST /api/task/{id}/share/pack`/CLI `texlate share pack` 三挂载点；contributor 用本地生成 `c-<16hex>` 匿名 id（不复用 key 指纹，防跨包关联）。
- **服务端 v1 不锁定**：任意静态托管/对象存储 + `index.jsonl`（share_key/url/key_parts/bytes/created_at/contributor 行，last-wins、坏行跳过）——价值在数据不在服务。
- **隐式命中**：普通任务 parse 后自动查本地 index，命中走 share_apply 对账通道；对账拒绝**摘标记回退自译**（隐式命中是优化不是承诺）。

## 理由

- 「只信翻译内容，不信任何下游产物」：dual.json 恰是 xlat 阶段输出物形态，消费端从 splice 起重跑——编译不撒谎，防伪靠重跑而非签名（hjfy `{id}_zh_CN.tgz` 公开下载同构信任）。
- zh.pdf 可选放行的理由：fixloop_exhausted 型任务的 L2 修复译文经包传播有实证价值，贡献者编不过只是少证据件。
- 证据：调研档案 `research/product/shared-cache.md`；主仓 `docs/05` E15（缓存键设计）。

## 演变

- 2026-09-16：pack/unpack 放行 partial 包（zh.pdf 缺席合法）；share_pack 三挂载点落地。
- 2026-09-18：**公共 registry/已译浏览面否决**——roadmap 中期工单 MT1（共享缓存分发层，原文误记为「M1 里程碑」）不做公共实例与匿名浏览（决策理由见 ADR-0019）；share 协议保留为单机/自托管形态。
- 2026-09-19→20：隐式命中接线（`_run_tex` 在 parse 后 `_share_lookup` → `_stage_share_apply` 零 token；`_ShareRejectError` 回退自译），共享缓存从「显式导入」升级为「默认查」。

## 现状

实现落在 `share.py`（share_key/pack_share/unpack_share/index_append/index_lookup，包校验全链：manifest ≤1MB、产物名扁平白名单、逐成员 sha256 对账、临时目录原子 rename）+ `server/routers/share.py`（`/api/share/import`、`/api/task/{id}/share/pack`）+ `server/worker/share.py`（`_maybe_share_pack` 完成钩、`_share_lookup`/`_share_apply`/`_share_unmark`）+ `server/worker/core.py::_run_tex|_run_share`。research/product/shared-cache.md §8「隐式命中未接线」注记已过时（代码已接）。
