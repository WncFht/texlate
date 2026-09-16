# pipeC/pipeB 尾段拉齐 — harness 口径修复（2026-09-16）

`e2e_mock_bench.py` 的 Mode B/C 臂此前止于首编 verdict，与 pipe 臂（首编 + L2 回灌 + fixloop 修复）口径不对称，pipeC 存活率被系统性低估。本次把两臂接上同一尾段，并重跑退化 8 篇验证归因转移。

## 改动（bench/py/e2e_mock_bench.py，+95/−28）

**`translate_tree` 重写为 `e2e._translate_tree` 完全同构**：

- 补 `chunk_to_in(ph_map=res.ph_map)`——旧版漏传，`ph_fragments=None`，阶梯「抄回修复臂」（recover_copied_tokens）在 Mode B/C 臂根本没武装。这是任务点名的两处之外的**第三处隐性不对称**，直接影响 Mode B `recovered` 账目真实性（旧口径 recovered 被低估、caught 被高估）。
- env_judge 复用 `e2e._env_judge_pass`（默认关，与产品同 `TEXLATE_ENV_JUDGE` 开关）。
- 返回 `(stats, _TreeRun, results)`——`_TreeRun` 与产品臂同一运行态形状，供 L2 回灌消费。

**`pipe_mode_condition` 尾段换成 `pipe_condition` 同一条链**：

- inject reject 口径 `reject` → `partial` + `reject_at="inject"`（产品 F3 口径）。
- 首编 `e2e._compile_judge` → 非 clean 时 `e2e._l2_repair` → `e2e._run_fixloop`；`TEXLATE_NO_L2`/`TEXLATE_NO_FIXLOOP` 开关面一致。
- ledger 修正：env_judge 回落块视同未进 splice（防 Mode B `escaped` 虚报）；破坏注入面不变（translator 层），L2 重译经 `_unwrap_seg` 还原 seg 保确定性。
- 删 bench 本地 `_compile_judge` 死代码；`route_engines` 穿透 fixloop 跨引擎消费。

## missing cls/sty 归因澄清

**不是工作区拷贝问题**——copytree 全量复制，`JHEP3.cls`/`psfig.sty` 源树本就不存在（base-xel 同错实证）。pipe-xel 救回靠 fixloop `missing_file` → `legacy_pkg_shim` stub 注入（两篇 CTAN 均无此文件，`installed: []` + advisory）。pipeC 旧版止于首编没机会跑 fixloop，尾段接通后自然恢复。

## 重跑验证（本目录）

`--corpus bench/corpus_v3 --ids <退化8篇> --conditions base-xel,pipe-xel,pipeB-xel,pipeC-xel`

| id | 旧 pipeC | 新 pipeC | pipe-xel | 归因 |
|---|---|---|---|---|
| 0806.3472 | partial | partial | partial | 不变（参照组） |
| astro-ph/0104134 | reject@inject | partial@inject | partial@inject | 口径拉齐 |
| astro-ph/0501428 | reject@inject | partial@inject | partial@inject | 口径拉齐 |
| cond-mat/9910284 | reject@inject | partial@inject | partial@inject | 口径拉齐 |
| hep-th/0408076 | fail（missing JHEP3.cls） | partial（fixloop stub→pdf，7 err） | clean（同路径，2 err） | **真实挪位代价** |
| math/9901064 | reject@inject | partial@inject | partial@inject | 口径拉齐 |
| nucl-th/0307063 | reject@inject | partial@inject | partial@inject | 口径拉齐 |
| quant-ph/0307209 | fail（missing psfig.sty） | clean（fixloop stub→pdf） | clean | 完全恢复，路径一致 |

pipeB 臂同受益：4 篇 reject→partial、hep-th fail→partial、quant-ph fail→clean、0806.3472 partial→clean（fixloop 修净）。

## 口径结论

- 8 篇子集新 pipeC **8/8 出 pdf、零退化**；Mode B `escaped==0` PASS 保持（323 破坏块：caught 271 / recovered 52）。
- `hep-th/0408076` 的 clean→partial gap 是**有效信号非噪声**：58 块挪位全进 splice，fixloop 同路径补出 pdf 后残留 7 错 > judge 阈值 3 → partial；pipe 臂同路径残留 2 错 → clean。这 5 个净增错误正是 Mode C 要量化的 splice 错位编译代价。
- 7 篇旧「退化」确认全为 harness 归因：5 篇纯标签不对称（同 `InjectRejectError(latex209)` 事件产品臂 partial vs bench 臂 reject）+ 2 篇 fixloop 缺失。

后续：全量 50 篇复跑刷新 modec-v3 基线数字（可并入下一轮 bench 批）。
