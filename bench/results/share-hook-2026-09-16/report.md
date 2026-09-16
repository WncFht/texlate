# share-hook — #92 share 完成钩（worker opt-in 打包 + index.jsonl 落行）

> 2026-09-16。入库 `746e87f`：worker.py(+122)、settings.py(+13)、tests/test_share_hook.py(11 用例)。全量 2190 pass / 4 skip。

## 落地

- `worker.py` `_maybe_share_pack(ctx)`（~2961，async 钩壳）：`kind=="share"` 永不自包 + `options.share_pack` 真值门；`asyncio.to_thread` 跑打包（Fix6 先例）；异常 → `warning{code:"share_pack"}` 事件，不动终态。
- `_share_pack_try(ctx)`（~2977，worker 线程）：key_parts 从库内行现值派生——`normalize_arxiv_id` 拆钉版 `{id}v{N}`、model/target_lang 取任务行、`PROMPT_VERSION`/`PIPELINE_VERSION` 常量、`glossary_hash` 按**生效层**派生（配置路径经 `_glossary_path` confine，缺省回落 `USER_GLOSSARY_PATH`，`base/glossary.local.yaml` 恒进——与 `_make_glossary` 同口径）。`pack_share` → `unpack_share` **全量回验**（scratch `.share-verify` 随验随清——写盘损坏不进索引）→ `index_append(share_dir/"index.jsonl", mf, url=bundle.name, bytes)`。
- 接线：`_stage_compile` 三终态出口全覆盖（fixloop reject partial / `_no_pdf_finish` / done-partial 主路径，均在 transition+done 事件后）。
- `settings.py` `share_dir()`：`TEXLATE_SHARE_DIR` env > `<data_dir>/share`，惰性建目录。
- `app.py`/`schemas.py` 零改动——options 自由 dict 透传 `options_json`，三路（arxiv JSON/upload options/retry merge）自动带 `share_pack`。

## 判定调用（leader 已知情）

1. 「usable zh.pdf」放宽为 spec 现口径：`REQUIRED_ARTIFACTS`（zh-src.zip+dual.json）在场即打——fault/reject 终态也产 partial 包（§9 放行 fixloop_exhausted 传播价值）。若只要 done/partial-with-pdf，删 `_no_pdf_finish` 后调用行即可。
2. reuse_hit（#74）天然不包——`_stage_fetch` 提前 return。刻意：命中任务的生效术语表不可知，错标 glossary_hash 比不包更糟。
3. index `url` = 包文件名相对形（§7 文件级托管模型，v1 无真 host）。
4. `contributor` 每包生成 `c-<16hex>`（最大化 unlinkability，spec 允许）。

## 测试（11 全绿）

opt-in done→包+index 行+七组分钉值+unpack 回环；opt-out/"off" 不产；share kind 永不自包；无 arxiv_id 记行跳过；zh-src.zip 缺席→warning+status 仍 done；直调 ShareError；fault-no-pdf→partial 包+index 行；glossary_hash 三层（local/空/confine）。注入 `TlpdbIndex({})` 保 probe hermetic。
