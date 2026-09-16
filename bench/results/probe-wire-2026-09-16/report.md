# probe-wire：target_probe 接入 worker 编译链（2026-09-16）

`compile/probe.py`（静态依赖探针）接入 `PipelineWorker` 编译路径，全程 best-effort fail-open——probe 崩溃只留 `probe crashed:` 日志行，不阻塞编译。

## 接线点

- `worker.py` runtime import `dep_seen, deps_diff, target_probe`；`PipelineWorker(deps_index=None)` 注入面——None 时 probe 内部 `TlpdbIndex.ensure` 惰性装载（fixloop 的 Ctan.index 私有不可复用）
- `_probe_target`：编译前 `target_probe(work, main_rel, deps_index=…)`
- `_probe_diff`：编译后 `deps_diff(expected=inputs∪local details, res.deps)` + missing 复核 + flags_dropped 播报
- `_compile_en`/`_compile_zh`：probe → compile(flags=rep.flags) → diff（diff 只针对首编，L2/fixloop 重编不复核——探针预测对象是声明态工程）

## 信号消费决策表

| probe 输出 | 消费方式 |
| --- | --- |
| `rep.flags`（minted→-shell-escape） | 透传 `compile(flags=…)`——xelatex argv last-wins 压 -no-shell-escape；tectonic 拒放落 flags_dropped 记行 |
| `rep.prefer_engine` | 只记日志（摘要行 + 与 ctx.engine_name 分歧时加「仅记录不切换」）——引擎决策已由 route_project 完成 |
| `rep.missing` | notes 透传 + 编译后 recorded/unseen 复核——fixloop missing_file 前置情报，不自己装包 |
| `rep.tl_packages` | `probe tl_pkg: …` 播报行 |
| latex209_suspect | notes 透传；试编+fixloop gate 兜底是既定策略 |
| `deps_diff` | `probe diff: seen=N unread=M undeclared=K` 聚合行（截断上限 8）；deps=None → 差分不可判 |

摘要全走 log 事件（SSE 自动可见），不入 task stats——最小侵入。

## 验证

- `tests/test_probe_wire.py` 9 条全绿：摘要/missing/flags 透传/prefer_engine 分歧/权威集差分（seen=2 undeclared=1 ghost.tex=unseen amsmath.sty=recorded）/deps=None 不可判/fail-open/en 侧同款幂等跳过/deps_index 注入命中 tl_pkg
- 回归 `test_server_{byok,l2,sse,wave2,security,store}` + `test_server_polish` 103+19 绿
- `ruff check` + `ruff format --check` 净
