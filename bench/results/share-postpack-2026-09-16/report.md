# share-postpack — `POST /api/task/{id}/share/pack` 事后打包端点

> 2026-09-16。scope：server/app.py + server/worker.py + test_share_postpack.py（新 12 例）。指定套件 124 过、ruff 净。shared-cache.md §6「完成后提示分享」服务端面闭环——此前只有建任务时 `options.share_pack` 与 CLI share pack。

## 端点契约（app.py:921 `share_pack`）

- 200 `{share_key, url, bytes}`——`url` 与 index 行同口径（扁平包文件名，`{share_key}.share.zip` 落 `share_dir(data_dir)`）。
- 404 任务不在/他租户（`_get_task` 三检）。
- 409 非终态（非 done/partial，`code=invalid_state`）。
- 422：`share_pack_rejected`（kind=share / options.reuse_hit 在场 / 无 arxiv_id）；`share_pack_artifacts`（缺 REQUIRED_ARTIFACTS，detail 列清单）；`share_pack_failed`（pack_share ShareError 透传）。
- 守卫序：404 → kind=share → reuse_hit → 状态 → arxiv_id → 幂等命中 → 产物缺失 → 打包。

## 幂等语义

manifest 派生 share_key → `index_lookup`：命中且 url 为扁平名、包文件在场 → 直接 200（不重打、不追加 index 行）；命中但包文件被清 → 落回打包路径重发（append-only last-wins 自愈）；索引行损坏 → warning 后重打不挡路。index url 扁平名校验（拒 `/` `\`）防越界探测。

## 与完成钩的复用方式（worker.py）

- `share_pack_manifest(self, ctx, row)`（:3028）——key_parts 七组分派生抽出，钩与端点共用；None = 无 arxiv_id。
- `share_pack_publish(work_dir, manifest, out_dir)`（:1092，模块级）——pack_share → unpack 回验 → index_append 纯 FS 段，不触 store/bus，端点 `asyncio.to_thread` 直调（store conn loop 线程亲和，入线程路径零 DB 触达）。
- `_share_pack_try`（:3075）改两段组合，钩行为不变（test_share_hook 11 例原样过）。
- 产物定位同钩口径：`ctx.root`(tasks/{id}/) 下 REQUIRED_ARTIFACTS，zh.pdf 缺席落 partial 包；glossary_hash 走 `_share_glossary_hash`（USER+local 层复合指纹）。

## reuse_hit 行级标记（本 diff 唯一行为扩展）

`_finish_reuse`（:1632）把 `options_json.reuse_hit = <hit_task_id>` 落库（ctx.row 同步，同 arxiv_categories 写回纪律）；`_stage_fetch`（:1479）真跑取源落 `.fetch-done` 时摘除——标记只描述当前产物来历，重试后自产不误拒。此前 reuse_hit 只存内存 ctx，端点无从判定；串事件日志扫描有重试后残留误报，故走 options 标记。

## 测试

新文件 12 例：done 打包+index 落行+key_parts 对账、幂等二次（单包单行）、partial 无 zh.pdf、opt_out 不挡显式打包、404/409/缺产物/kind=share/reuse_hit/无 arxiv_id 各一、`_finish_reuse` 写标记 + `.fetch-done` 摘标记。`uv run pytest tests/test_share_postpack.py test_share_hook.py test_share_apply.py test_server_api.py test_server_worker.py test_worker_audit_fixes.py -q` → 124 passed。

## 残余

web 侧「分享本译文」按钮（done 面板）对接面即本端点，已立项派发。schemas.py 不存在——schema 内联在 app.py，未新建。
