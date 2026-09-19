# 基建类编译错误治理 — before/after 终态对照（2026-09-19）

## 背景

「基建类编译错误被 L2 误归因 / 毒化修复链」类问题的综合治理。实证事故 `t_f74894ebc691aaf4`：工程缺 `algpseudocodex.sty`（missing_file 基建错），进入 L2 归因面后文件级兜底把 `main.tex` 4 个块拖去重译/回退，终态 `partial`；该 partial 行又被 reuse 池克隆给 `t_74d635d226e68251`——腐产物毒传播。

根因三层：
1. L2 归因把基建错（缺包/嵌套 tar/构建 flag）错算成译文伤，resplice 拖垮干净块。
2. fixloop 的 `static_precheck` 相（装缺件/解 tar/收 flag）原来捆在 fixloop 内、跑在 L2 之后——本可在归因前消掉的错被 L2 先误处理。
3. reuse 池 `find_reusable` 把 `done`/`partial` 同列返回，`_finish_reuse` 原样镜像终态——partial 降级交付被克隆给后来者。

## 修复链三级阶梯（after）

```
编译 fail → precheck（装缺件，fixloop 第 0 招独立相，不改 .tex 源）
         → L2 回灌（译文伤归因重译 resplice）
         → fixloop（规则修源/基建残留）
```

顺序是设计约束：precheck 先消 missing_file 类基建失败（它们进 L2 只会拖块重译）；L2 先于 fixloop——fixloop 的 `regex_rewrite` 会被 L2 resplice 冲掉。

## 五个任务面改动

### 1. L2 归因豁免面完备（repair_l2.py）

`_INFRA_ERR_RX` 扩充——missing_file/嵌套 tar/构建 flag 类基建错永不归因（与 taxonomy 同步义务已注释）。`_STRUCT_ERR_RX` 严格含位，`_FILELEVEL_ERR_RX` 白名单兜底（文件级归因只认白名单，不再裸拖 main.tex 全块）。

### 2. precheck 相独立入口（engine.py / repair.py / pipecore.py）

`static_precheck` 相从 fixloop 抽出为可独立预跑：
- `engine._precheck_phase` — 逐规则评估 precheck 相（engine_spec mode 检查/cond/_apply），REJECT → `(reject:<rid>, route)`。
- `engine.precheck_pass` — 公开入口（LoopCtx + find_main_tex + _wire_engine → 摘要 dict）。
- `repair.run_precheck` / `pipecore.precheck_job` — 薄委托/结构化摘要（crash → `{"enabled": True, "error"}` 不毁主报告）。

### 3. L2 前预跑 + texmf 接线统一（e2e.py / pipecore.py / worker）

`_repair_chain` 阶梯：precheck 装上缺件或收割到 engine_flags 才重编（空转省一发），clean 早退跳过 L2/fixloop 两臂；`reject:<rid>` 不重编不跑 L2，交 fixloop 复现 + 跨引擎消费。

`_texmf` 盲区统一：`_texmf_wire`/`_texmf_eng`（pipecore）盖 `_compile_judge_job` 与 fixloop cross-engine `make_engine`；worker `_task_texmf` 盖 `_engine`/`_fixloop_engine`/`_run_fixloop` 三路——装件落任务级共享 `ctx.root/_texmf`（worker）/ `work/_texmf`（e2e），en/zh 互见、retry rmtree build-zh 不丢装件。

### 4. en 侧缺包致败治理（worker/compile.py）

共享 `ctx.root/_texmf` 接线使 en/zh 装件互见；并发会话 `_fixloop_en` 提供 en 侧 fixloop 直救（`_fixloop_pass` 共享核 `cond="en"/"zh"`）。en 侧编译缺包不再永久缺席。

### 5. partial 不进 reuse 池（store/_tasks.py / worker/fetch.py）

`find_reusable` 收窄 `status = 'done'`（原 `IN ('done','partial')`）——唯一判据点，enqueue（`deps.py:209`）与 post-resolve（`fetch.py` `_post_resolve_reuse`）共用，一处斩断毒克隆。`_finish_reuse` 同步收窄恒 `done`（移除 partial 镜像臂 + error_json 透传——不可达腐钩）。partial 命中方走真跑，修复链可能收敛成 done。

## before/after 终态对照

| 场景 | before | after |
| --- | --- | --- |
| 缺 `algpseudocodex` 类 missing_file | L2 文件级兜底拖 main.tex 4 块重译/回退 → partial | precheck `scan_install` 装上即重编 → clean，L2/fixloop 全省 |
| precheck `reject:<rid>`（如 pstricks 在 tectonic） | — | 不重编不跑 L2 → fixloop 复现拒绝 + `reject_route` 跨引擎消费 → partial（`reject_at=fixloop`） |
| partial 行被同 cache_key 请求命中 | `_finish_reuse` 镜像 partial + error_json → 克隆腐产物 | `find_reusable` 不返回 partial → 真跑（修复链可收敛） |
| en 侧编译缺包 | 永久缺席（en 无重试/装件面） | `_task_texmf` 共享装件 + `_fixloop_en` 直救 |
| fixloop cross-engine / compile_judge 新造引擎 | 看不见 `_texmf` 装件（盲区） | `_texmf_wire`/`_task_texmf` 统一接线，装件互见 |

## 测试证据

- `tests/test_l2_infra_attr.py`（新建）— 基建错豁免/文件级白名单归因。
- `tests/test_repair_chain_precheck.py`（新建，5 绿）— precheck 装件短路/noop 落 L2/reject 跳 L2 走 fixloop/compile_judge 引擎 texmf 接线/precheck crash 不毁报告。
- `tests/test_server_store.py::test_find_reusable_excludes_partial`（新增）— partial 不命中、done 照常命中。
- 修复链/缺包面回归：`test_repair_chain_precheck` + `test_l2_infra_attr` + `test_server_l2` + `test_fixloop_live_events` + `test_repair*` + `test_l2*` + `test_fixloop*` = **1379 passed, 2 skipped**。
- reuse/store/worker 面：`test_server_store` + `test_worker_cancel_protocol` + `test_server_api` + `test_server_api_fixes` = **136 passed**；share/worker/fetch/app 更广面 **463 passed**。
- 全量扫：**7673 passed**，4 个失败全在 `inject.py` 字体面（`test_inject_cjk_math`/`test_inject_hexquote`/`test_inject_theorem_anchor`/`test_bblwall_audit` real_compile）——并发会话在飞的 `\IfFontExistsTF`/`texlatecmu` 重构引入的回归，非本治理受面（未改 inject.py/cjkmap）。

## 交付文件清单

产品码：
- `src/texlate/repair_l2.py` — `_INFRA_ERR_RX`/`_STRUCT_ERR_RX`/`_FILELEVEL_ERR_RX` 三档归因。
- `src/texlate/repair.py` — `run_precheck` 薄委托。
- `src/texlate/pipecore.py` — `precheck_job`、`_texmf_wire`/`_texmf_eng`。
- `src/texlate/e2e.py` — `_repair_chain` 三级阶梯。
- `src/texlate/compile/fixloop/engine.py` — `_precheck_phase` + `precheck_pass`。
- `src/texlate/compile/fixloop/__init__.py` — `precheck_pass` 导出。
- `src/texlate/server/store/_tasks.py` — `find_reusable` 收窄 done。
- `src/texlate/server/worker/fetch.py` — `_finish_reuse` 恒 done。
- `src/texlate/server/worker/_common.py` — `ctx.precheck` 字段。
- `src/texlate/server/worker/compile.py` — `_task_texmf`/`_precheck_attempt`（+ 并发会话 `_fixloop_en`/`_fixloop_pass`）。

测试：
- `tests/test_l2_infra_attr.py`（新建）
- `tests/test_repair_chain_precheck.py`（新建）
- `tests/test_server_store.py`（+1 用例）

## 建议 commit msg

```
fix(compile): decouple infra errors from L2 attribution + repair chain

Three-tier repair chain — fixloop precheck (install missing files, never
touches .tex source) runs before L2 resplice so missing_file class errors
no longer get misattributed to translation chunks. L2 gains infra-error
exemptions + a file-level whitelist so infra failures can't drag clean
main.tex chunks into retranslation. find_reusable narrows to done-only so
partial degraded deliveries stop cloning to later tasks. _texmf wiring
unified across e2e/worker engine factories so installed packages are
visible to every recompile arm.

Refs: t_f74894ebc691aaf4
```
