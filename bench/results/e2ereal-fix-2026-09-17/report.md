# e2ereal-fix — e2e_real_bench 续跑完整性 4 修

> 2026-09-17 收口。scope：`bench/py/e2e_real_bench.py`（+66/-14）。消化 scout-e2ereal 取证 9 风险中的可修面。leader 复核：diff 逐 hunk 对账一致。

## 修复项

1. **`--date` 跨日分叉守卫**（`_warn_date_fork`）：默认 --date=当天 UTC——崩溃隔日重启会新建空目录全量重跑、结果劈两目录。目标目录不存在且同 tag 有其他日期目录时，醒目 WARNING 列最近目录并提示 `--date <那天>` 续跑；全新首跑静默不误警。
2. **产码印章钉快照**（`_code_stamp`）：`TEXLATE_SRC` 冻结快照根带 `snapshot-manifest.txt` 时印章=`snap-{manifest_sha256[:12]}`——bench 期间 repo 无关 commit/dirty 不再误判全格 stale；快照换字节→manifest 换哈希→陈旧格必被 `--recode` 抓。无 manifest 回退 repo 戳。
3. **results 整格替换**：`results[rel].update(rec)` 浅合并 → `results[rel] = rec` 整替换（与 records.jsonl 末行胜同口径）——旧格不再产的臂键（pipe-fix/base-xel/error/reject_at）残留成 matrix 幻影行的洞堵上。
4. **原子写**（`_atomic_write` mkstemp+os.replace+失败清理）：results.json / run_meta.json / matrix.md / summary.md 五处全量重写不再留撕写窗（live 消费方安全；与 `xlat.state.atomic_json` 同式，tmp 名带随机后缀防同路径并发）。

## 未消化（仍 open）

scout-e2ereal 取证残余：rc≥128 信号归因逃逸（bwrap SIGPIPE rc=141 vs killed_signal 语义——已转 项目体验方式 judge 车道）、cases 双行、空 records 种子、抽样漂移、auth 不停车。

## 验证

- `ruff format --check` + `ruff check`：净（bench/py per-file-ignores 内）。
- 行为面：`--date` 守卫纯新增 warning 不改流程；印章函数有 manifest/无 manifest 双路；原子写 tmp 同目录保证 os.replace 同文件系统。
