# tools/ — 可复用开发诊断工具（tracked）

一次性调查脚本去 `tmp/`（gitignored scratch）；**会再跑的度量/审计/暖存工具放这里**。
一律仓根执行、`.venv/bin/python` 直跑，输出默认写 `tmp/`。

## seqpos 对位度量组（reader EN↔ZH 映射质量）

| 工具                    | 作用                                                                                                     | 用法                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `seqpos_warm.py`        | 预算所有任务的 seqpos.json（reader 首开免懒算峰；幂等，缓存命中秒回）                                    | `.venv/bin/python tools/seqpos_warm.py`                                           |
| `seqpos_audit.py`       | **精度 oracle**：pymupdf `search_for` 字面搜索当真值，按侧×臂报 cov/wrong_page/p50/p90/miss + seq 缺席率 | `.venv/bin/python tools/seqpos_audit.py [task_id ...]` → `tmp/seqpos-audit2.json` |
| `seqpos_clicksim.py`    | **点击→seq 仿真**：nearest/floor_y/floor_c 三 picker 对照，逐块均匀取点报错选率                          | `.venv/bin/python tools/seqpos_clicksim.py`                                       |
| `mapper_audit.py`       | 滚动同步 mapper 复刻：相邻逆序率/锯齿幅度/LOO 兜底误差                                                   | `.venv/bin/python tools/mapper_audit.py`                                          |
| `seqpos_verify_mask.py` | occurrence 遮蔽检测：ambig 命中下 audit 是否把错 occurrence 洗成 0 误差                                  | `.venv/bin/python tools/seqpos_verify_mask.py`                                    |
| `mark_bias.py`          | 标记偏置量化：mark frac vs 首字形真值分布（stale-tm 回归探针）                                           | `.venv/bin/python tools/mark_bias.py`                                             |

度量基线（2026-09-24 修复前）：`tmp/seqpos-audit2-BEFORE.json`；修后重跑对比。

依赖关系：audit/clicksim/verify_mask 读 `~/.texlate/tasks/*/seqpos.json`+`dual.json`+双 PDF，
并 import `texlate.server.seqpos` 内部件（`_char_stream`/`_tex_strip`）——签名漂移时同步改这里。

## bench 质检重放

| 工具           | 作用                                                                                                                                       | 用法                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `qc_replay.py` | layoutqc 离线重放：vault 现行封件过**工作树**检测器，与账上旧口径逐格差分（检测器修订后的实测面；dedup 会跳 DONE 格，spec 重跑拿不到新数） | `.venv/bin/python tools/qc_replay.py [--out tmp/qc_replay] [--jobs 8] [--id X ...]` → `papers.jsonl`+`summary.json` |

口径注意：zh txlm 从 layoutqc 封件回填（splice 封件常缺）；artifact-only 封件遮
`layout:dropped_env` 并标 `env_masked`；账本 mode=ro、vault 硬链只读——零写账。
