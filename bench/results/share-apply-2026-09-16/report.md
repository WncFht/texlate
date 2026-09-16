# share 消费侧实装报告 — share-apply-2026-09-16

- 生成: 2026-09-16 · 范围: `POST /api/share/import` 端点 + worker `kind="share"` 重验链（`docs/research/product/shared-cache.md` §5 消费侧）
- 涉及文件: `src/texlate/server/app.py`、`src/texlate/server/worker.py`、`src/texlate/server/store.py`、`tests/test_share_apply.py`（新）
- 验证: `pytest tests/test_share_apply.py` 12 全绿；`pytest -k "server or share or app"` 362 过；`ruff check`/`format` 干净

## 端点契约

`POST /api/share/import`，multipart 表单，`file` 字段收 `.share.zip`（`pack_share`/CLI `share pack` 产物）。响应沿用 §2.1 统一形状：202 `{task_id, status, events_url, reader_url}` 新入队；200 + `{reused: true}` 命中已有产物行；409 `duplicate_active` 撞活跃同键；4xx `share_invalid` 包级校验失败（此时不落任务行、不入队，临时目录整体清除）。

端点只做机械校验，不做内容裁决：`unpack_share` 承担 zip 可读性、manifest `format`/`share_key` 自洽重算、逐产物 sha256+size 对账（白名单抽取，天然免 zip-slip）；随后 `_share_parts_checked` 闸 key_parts 白名单——`arxiv_id` 必须裸 id（嵌 `vN` 即 400，版本只走 `version` 键）、`target_lang ∈ TARGET_LANGS`、`model` 过 `validate_model`、`version` 只收 `vN` 钉版形或空串。解包落 `tasks/{tid}/share/`（产物成员）+ `tasks/{tid}/upload/bundle.share.zip`（原始包留存，不登记 files 表、不可经 `/api/files` 取到）。

## 信任模型落地（§5：重验 vs 信任边界）

消费链 `kind="share"` → `_run_share`：`_stage_fetch`（本地重新 fetch arxiv 源，manifest 钉版）→ `_stage_parse`（本地半解析建 chunks）→ `_stage_share_apply`（translating 臂替换：包内 `dual.json.chunks` 按 `(src_file, en==src_text)` 对账本地 pending 块）→ `_stage_compile(share=True)`（splice→inject→en/zh 双侧编译→judge→dual.json 全链本地重跑）。

| 包内物件 | 消费侧处置 | 理由 |
| --- | --- | --- |
| `dual.json.chunks` | 对账译文源：命中且过 `validate_pair` → `ok`；命中但 L0 不过 → `fallback_orig`+`validate`；本地无包条目 → `fallback_orig`+`share_miss` | 唯一被采纳的内容载荷，且逐块过与 LLM 产出同款判据 |
| `zh.pdf` | 不信不取（仍须过 sha256 对账才解包，解出即弃） | §5 核心：读者看到的每字节须本地再生 |
| `zh-src.zip` | 不解不用 | 它是 splice 输出物——展开即信任贡献者整棵 TeX 树（preamble `\write18`/`\input` 面），信任模型即空 |
| `manifest.key_parts` | 只用于建行元数据 + cache_key 寻址，不承担内容信任 | 内容真值由对账/重编裁决 |

拒绝面：对账零命中（`matched==0`，包与本源不对应）→ `_ShareRejectError` → partial + `reject_at="share_verify"`，块表不写库；重编不出 pdf → `_reject` 同形收口（`detail` 带 l2/fixloop 摘要），降级 `md_zip` 照发。任一失败的最坏代价 = 白跑一次编译，读者拿不到坏 PDF、零 token 消耗。

## dual/en 侧决策

brief 曾问 en.pdf 是否需 arxiv 重拉/重编、`dual_verified:false` 兜底可否——结论：§5 本地 fetch 本来就是强制的（否则连「包对应的是不是这篇论文」都无法证明），`_compile_en`/`_build_dual` 顺手就在链内，边际成本≈0，故不需要 fallback 标记，导入产物的 dual.json 一律本地重建（`build_alignment(en.pdf, zh.pdf)` 全真）。

其余决策：任务行 `model`/`target_lang`/`arxiv_id`/`version` 一律记 manifest 生产者真值——包自描述，与导入者自身配置不一致**不拒**（导入者配置不进寻址）；`cache_key` 按钉版形态 `cache_key_for(base, ver, …)` 重算，后来的 `id@vN` 请求经 `find_reusable` 真命中本产物（裸 id/latest 形态不命中，与正常流同语义）；pipeline_ver 不一致不拒——对账零命中天然收口，审计字段 `options.share`（share_key/contributor/created_at/key_parts 快照，端点强制覆盖防调用方伪造）留痕；v1 不做 miss 块自译回退（保持导入零 token）。

## 测试矩阵（`tests/test_share_apply.py`，12 例全绿）

生产/导入双 app 实例（独立 data_dir+SourceCache、同一 FakeFetcher 载荷）模拟跨实例共享；包由生产端真管线跑出再 `pack_share`。

| 用例 | 断言 |
| --- | --- |
| `test_import_done` | 全链 done；kind/arxiv_id/model/lang 正确；产物六件（src_tar/en_pdf/zh_pdf/zh_src_zip/dual_json/compile_log）；reader 200 view=pdf；dual.json chunks 全带 zh |
| `test_import_reuse_and_later_request_hit` | 同包再导入 200 reused；后来 `POST /api/arxiv/idv1/translate` 200 reused 命中导入行 |
| `test_import_manifest_provenance` | manifest model 与上传者设置不同不拒，任务行记生产者真值 |
| `test_import_validate_fail_falls_back` | 包内 zh 注 `}` 坏 brace → 块级 fallback_orig+validate，partial + `error.share.dropped=1` |
| `test_import_zero_match_reject` | 合成包 chunks 与本地零命中 → partial + `code=share_verify` + `reject_at=share_verify` |
| `test_import_compile_fail_reject` | 引擎不出 pdf（fixloop/L2 关）→ partial + share_verify + md_zip 降级件在 |
| `test_import_tampered_artifact` | zh.pdf 成员篡改 → 400 share_invalid |
| `test_import_tampered_manifest` | key_parts.model 篡改致 share_key 不自洽 → 400 |
| `test_import_not_zip` / `test_import_missing_file` | 非 zip / 缺 file 字段 → 400 |
| `test_import_bad_lang` / `test_import_bad_version_form` | key_parts lang∉白名单 / version 非 vN 形 → 400 |
