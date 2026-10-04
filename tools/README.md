# tools/ — 可复用开发诊断工具（tracked）

一次性调查脚本去 `tmp/`（gitignored scratch）；**会再跑的度量/审计/暖存工具放这里**。
一律仓根执行、`.venv/bin/python` 直跑，输出默认写 `tmp/`。

## seqpos 对位度量组（reader EN↔ZH 映射质量）

| 工具                    | 作用                                                                                                                     | 用法                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `seqpos_warm.py`        | 预算所有任务的 seqpos.json（reader 首开免懒算峰；幂等，缓存命中秒回）                                                    | `.venv/bin/python tools/seqpos_warm.py`                                           |
| `seqpos_audit.py`       | **精度 oracle**：pymupdf `search_for` 字面搜索当真值，按侧×臂报 cov/wrong_page/p50/p90/miss + seq 缺席率                 | `.venv/bin/python tools/seqpos_audit.py [task_id ...]` → `tmp/seqpos-audit2.json` |
| `seqpos_clicksim.py`    | **点击→seq 仿真**：nearest/floor_y/floor_c 三 picker 对照，逐块均匀取点报错选率                                          | `.venv/bin/python tools/seqpos_clicksim.py`                                       |
| `mapper_audit.py`       | 滚动同步 mapper 复刻：相邻逆序率/锯齿幅度/LOO 兜底误差                                                                   | `.venv/bin/python tools/mapper_audit.py`                                          |
| `seqpos_verify_mask.py` | occurrence 遮蔽检测：ambig 命中下 audit 是否把错 occurrence 洗成 0 误差                                                  | `.venv/bin/python tools/seqpos_verify_mask.py`                                    |
| `mark_bias.py`          | 标记偏置量化：mark frac vs 首字形真值分布（stale-tm 回归探针）                                                           | `.venv/bin/python tools/mark_bias.py`                                             |
| `seqpos_e2e_sim.py`     | **端到端点击→对侧落点仿真**：生产 PDF→PDF 链路复刻（seqAtPoint→jumpSeq→兜底链）逐块报错选率 + 栏型普查/x 覆盖/锚序倒置率 | `.venv/bin/python tools/seqpos_e2e_sim.py [task_id ...]` → `tmp/seqpos-e2e.json`  |

度量基线（2026-09-24 修复前）：`tmp/seqpos-audit2-BEFORE.json`；修后重跑对比。

依赖关系：audit/clicksim/verify_mask/e2e_sim 读 `~/.texlate/tasks/*/seqpos.json`+`dual.json`+双 PDF；
仿真共用件已收 `_seqpos_lib.py`（mapper/picker/真值探针单一事实源），并 import
`texlate.server.seqpos` 叶内私件（`seqpos.stream` 的 `_char_stream`/`_tex_strip` 等——私名经叶直引不经门面回引）——签名漂移时同步改这里。

## bench 质检重放

| 工具           | 作用                                                                                                                                       | 用法                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `qc_replay.py` | layoutqc 离线重放：vault 现行封件过**工作树**检测器，与账上旧口径逐格差分（检测器修订后的实测面；dedup 会跳 DONE 格，spec 重跑拿不到新数） | `.venv/bin/python tools/qc_replay.py [--out tmp/qc_replay] [--jobs 8] [--id X ...]` → `papers.jsonl`+`summary.json` |

口径注意：zh txlm 从 layoutqc 封件回填（splice 封件常缺）；artifact-only 封件遮
`layout:dropped_env` 并标 `env_masked`；账本 mode=ro、vault 硬链只读——零写账。

## 存量任务手术与湖账普查

| 工具                | 作用                                                                                                                                        | 用法                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `remark_rebuild.py` | 存量任务离线重注锚 + 重编译：base/ 重扫→双侧 marked splice→重编译→pdf/DB/dual 原子更新；parity 闸拒收 seq 错位任务（宁缺勿滥）              | `.venv/bin/python tools/remark_rebuild.py [task_id...] [--en-only\|--zh-only\|--zh-min-rate X\|--force]` |
| `reseg_rekey.py`    | 分段器演进致 rescan≠dual 时把 chunks 表/dual.json 重键到当前 chunk 流（remark parity 闸放行前置；单事务 + 旧行备份 `tmp/rekey-<tid>.json`） | `.venv/bin/python tools/reseg_rekey.py [task_id...]`（缺省=parity 失配全量）                             |
| `ph_remap.py`       | rekey 遗留 ph id 修复：读 rekey 备份按解析序逐位把译文 `[[X_n]]` 重映射到新编号（失配即弃映，幂等空转）                                     | `.venv/bin/python tools/ph_remap.py <task_id>...`                                                        |
| `xlat_pending.py`   | 存量任务 pending chunks 离线补译：XlatPipeline 走真实网关回写 chunks/dual.json/tasks（凭证取任务 config+settings 同构装配）                 | `.venv/bin/python tools/xlat_pending.py <task_id>...`                                                    |
| `repair_census.py`  | 修复普查：台账 events 驱动，never-passed 修复池按标记聚类 → `tmp/repair-census.json`+簇表                                                   | `.venv/bin/python tools/repair_census.py [--out ...] [--stage compile,fixloop]`                          |
| `arms_tokens.py`    | 双臂 token 对账：按任务时间窗切网关 `logs` 表（api+key+ms 窗隔离），逐臂逐篇出 calls/input/cache_read/output JSON                           | `.venv/bin/python tools/arms_tokens.py [--arms arms.json] [--out tmp/arms-tokens.json]`                  |

## 文档与文本工具

| 工具                   | 作用                                                                                                                 | 用法                                                                                     |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `docs_linkcheck.py`    | docs/ 相对链接检查：markdown 链接/图片/行内路径引用的目标存在性校验（exit 1 列死链）                                 | `.venv/bin/python tools/docs_linkcheck.py [--root docs]`                                 |
| `md_table_align.py`    | MD060 aligned 表风格重排器：按显示宽度（CJK=2，wcwidth 口径）把表块各列重排到统一列位，原位改写                      | `.venv/bin/python tools/md_table_align.py FILE [FILE ...]`                               |
| `vendor_census.py`     | fixloop `vendor/` 资产普查 + 可达性扫描：`vendor/MANIFEST.md` 的生成数据源（逐件 \ProvidesX 头 + 引用分类）          | `.venv/bin/python tools/vendor_census.py [out.jsonl]` → `tmp/vendor-census-<日期>.jsonl` |
| `make_readme_shots.py` | README 数据图再生：`shots/bench-token.png`（管线 vs agent 逐篇/总量账）+ `shots/bench-e2e.png`（留出集逐篇终态分解） | `uv run --with matplotlib python tools/make_readme_shots.py`                             |

## lib 件与系统级巡检（非手跑入口）

| 件                | 作用                                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_env.py`         | tools/ 脚本环境自举（lib 件非入口）：import 即把仓根 `src/` 推上 `sys.path`，外露 `TEXLATE_ROOT`/`TASKS`/`DB` 常量                                      |
| `_seqpos_lib.py`  | seqpos/alignment 仿真共用件（lib 件非入口）：mapper_audit/seqpos_e2e_sim/seqpos_clicksim 的 mapper、picker、lit 真值探针单一事实源                      |
| `_alignsim.py`    | 逐字位流仿真共用件（lib 件非入口）：seqpos_verify_mask/mark_bias 的 pymupdf rawdict→逐字 offset→(page,frac) 反查单源                                    |
| `bench_patrol.sh` | bench 巡检哨兵（系统级 cron/systemd timer 驱动的保底层，只量不判）：量 df/心跳/events 鲜度/records 进度/网关配额，越闸打 WARN 落 `tmp/bench-patrol.log` |

## 对照臂实验与网关对账

driver→wins→usage 两步链 + 离线臂重放/存活率审计；网关 `logs.time` 是毫秒 epoch，窗切按 api+key_hash 隔离（同 key 面须带 `--key` 防串窗）。

| 工具             | 作用                                                                                                                       | 用法                                                                                                                       |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `arm_driver.py`  | 对照臂驱动：逐篇 POST translate + 轮询终态落窗口 JSON（串行提交=窗不重叠，下游窗切前提）                                   | `.venv/bin/python tools/arm_driver.py --papers id1,id2[@file] [--prefer fresh] [--out tmp/arm-wins.json]`                  |
| `arm_usage.py`   | 逐臂逐篇网关账本对账（取代 `arms_tokens.py`）：ms 窗切 logs + task_usage/chunks 富化 + window_balanced 校验                | `.venv/bin/python tools/arm_usage.py --wins tmp/arm-wins.json --key <hash> [--date YYYY-MM-DD]`（多臂 `--arms arms.json`） |
| `replay_arm.py`  | prompt 臂离线重放：extract 树→kind 装箱→臂注册表 system/user→网关→parse+member 审计+raw 落盘                               | `.venv/bin/python tools/replay_arm.py <extract_dir> <kind> <arm> <all\|N\|NxR>` → `tmp/replay_raw_<arm>_<kind>/`           |
| `ph_survival.py` | ph id 存活率对照（只读统计）：`chunks.src_text` vs `translation` 的 `[[TYPE_n]]` 集合差分，同篇双臂配对 kept/missing/extra | `.venv/bin/python tools/ph_survival.py <a> <b> [...] [--labels v4,v5] [--out ...]`                                         |

lib 件（非入口）：`_arm_lib.py`（arm 组 +0800 hms 窗契约 TZ8/hms/hms_ms/DAY_MS 单源）、`_prompts_v4.py`/`_prompts_v5.py`（FROZEN prompt 套件快照——replay_arm v4/v5/v6 实验臂唯一事实源，刻意不随 `src/texlate/xlat/prompts.py` 漂移；产线现行形态走 `prod` 臂）。

## 批量接力与源码 codemod

| 工具                | 作用                                                                                                                          | 用法                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `chain_runs.sh`     | 触发件终态接力跑批：`--pid/--proc/--marker/--flag` 闸（默认全终态，`--any` 任一）→ `--then` 逐段裸 exec，START/EXIT/DONE 打戳 | `tools/chain_runs.sh --log tmp/x/run.log --log-dir tmp/x --pid 123 -- cmd1 --then cmd2` |
| `fix_raise_msgs.py` | raise 字面量外提 codemod：`raise E(<lit>)` → `msg` 外提批处理（TRY003/EM 消债；默认 dry-run，`--write` 落盘）                 | `.venv/bin/python tools/fix_raise_msgs.py [PATH ...] [--write]`                         |
| `ac_py_restore.py`  | autocorrect-on-py 手术回植：`--fix` 后把非 docstring 的字符串字面量按 token 对齐回植为 HEAD 原文（防夹具/协议串被平文改写）   | `.venv/bin/python tools/ac_py_restore.py FILE...`（在 `autocorrect --fix` 之后跑）      |
