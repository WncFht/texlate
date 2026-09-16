# share-wire — 隐式 share 命中接线完成

> 2026-09-17。scope：worker.py + 新建 test_share_wire.py（7 用例）。174 share/worker 测试绿、ruff 净。

translate 路径（kind=arxiv）parse 后自动查共享 index：命中 → `{key}.share.zip` 校验解包 → `_stage_share_apply` 对账通道（零 token）；miss/包缺失/包坏/对账零命中 → 回退正常自译，不 500、不替用户拒包。

## 改动文件

- `src/texlate/server/worker.py`（唯一改动的产品文件；share.py 无需补——index_lookup/unpack_share/share_key 接口够用）
- `tests/test_share_wire.py`（新建，7 用例）

## 设计决策

**触发点 = `_run_tex` 内 `_stage_parse` 之后、`_stage_translate` 之前**（非 fetch 后）。理由：share_key 七组分此刻才全齐且与翻译时同口径——`arxiv_id` 钉版在 fetch 落库，但 `glossary_hash` 的 local 层（`base/glossary.local.yaml`）与 `_glossary_path` confine 根都依赖 `_build_base` 产物；fetch 后即查会把生效术语表算漏 → 错键。且命中侧 parse 本来就要跑（对账需本地 chunks），post-parse 触发对命中零浪费。

**接线形态**：

- `_share_lookup(ctx)`（`asyncio.to_thread`，DB 经 `_on_loop`）：守卫阶梯 = kind≠arxiv / ctx.reuse_hit / prefer=fresh / 外来 reuse_hit / 零 chunks → 直返 False；`index_lookup` 命中 → 扁平名检查（同 app.py:991 口径）→ 包在场 → `unpack_share` 全量校验解包 `ctx.root/"share"` → 写 `options["share"]`（与导入端点同形审计载荷）+ `options["reuse_hit"]="share:{key}"`（share/pack 端点据以拒自包——app.py 未动，端点面零改）。
- `_run_tex` 命中分支：`_stage_share_apply` + `_stage_compile(share=True)`；`_ShareRejectError`（对账零命中）→ warning + `_share_unmark` 摘标记/清现场 → 落回 `_stage_translate`——隐式命中是优化不是承诺。
- `_share_unmark`：摘 `options.share` + `share:` 前缀的 `reuse_hit`（dedup 的 task-id 形标记不碰）+ rmtree `share/`。
- **零 token 闸门扩展**：新增模块级 `_share_sourced(ctx)`（kind=share 或 options.share 在场），替换 `_env_judge_enabled`/`_l2_enabled`/`_llm_hook_pack`/l2 reason 四处 `kind=="share"` 判定——隐式命中任务的 env_judge/L2/fixloop llm_hook 同被结构关闭（实测 MockTranslator.calls==0 走完全链）。
- `_maybe_share_pack` 加 `_share_sourced + reuse_hit` 守卫——原实现靠 dedup 早退挡自包，隐式命中会走到该钩，检查变承重。
- **幂等/自愈**：resume 时 marker+share/ 现场持久化，重验 key 符且 dual.json 在场即直返；retry 改 options 致 key 漂移、伪造 share 载荷 → unmark 后按现状重查（用户无法伪造 `share/dual.json` 盘位）；`reuse_hit` 被 fetch 摘除时 marked 路径补回，保拒自包面完整。

## 验证

- `uv run pytest tests/ -k "share or worker"`：**174 passed**
- 新文件 7 用例：命中 done+零 token+产物齐 / reuse_hit 标记→pack 端点 422 / index 无行 miss 自译 / 包字节坏回退 / 行在包不在回退 / prefer=fresh 不查 / 键命中但对账零命中→摘标记自译+可正常打包
- `ruff check` + `ruff format --check`：worker.py + test_share_wire.py 双净

## 未动面

app.py 端点面、share.py、rules.yaml、pipeline.py、latex209.py 均未碰。kind=share 显式导入链（`_run_share`）行为不变。
