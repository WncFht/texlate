# wave2-review — 本波全量 delta 回归终审（be9f93d..HEAD）

> 2026-09-17 收口。full.diff 5739 行 / ~43 文件 / 21 commits 逐 hunk 读完，现场 `tmp/wave2-review/`。

## 确认回归

**0 项。** 全部 ~15 个疑点均经 HEAD 源码实证消解（非读感）：

- segmenter `_preamble_doc_end` 的 `kind == "env_begin"`：`_resolve_macro` 返回 gullet MacroDef，kind 是普通 str —— 比较成立
- `register_newif` 只把 `\Xtrue/\Xfalse` 注册进 cmds、flag 进 ifflags，`\ifX` 不在 cmds —— `_is_if_opener` 顺序无遮蔽
- `scan_v2` 传 `g.file_texts` 本体（live list）—— F2 增量 ph_reserved 扫得见 `\input` 懒加载文件
- worker `_dispatch_loop` 新 `except Exception` 仅裹 setup 段（store.get/claim/ctx/create_task），行留 queued 供重启 replay，secrets.pop 到位，task_done 在 finally；StoreError import 删除后确无引用（仅注释提及）
- builtins `missing_char_fix` 消费 `params["exts"]`（engine.py:504 `tex_files` 接受任意扩展名元组，.bbl 可达）、`font_fallback` 消费 `fallback_ranges or _FB_RANGES`（builtins.py:1444 定义、1620 使用）
- conftest `make_app`/`upload_tex`/`MINI_TEX` 存在；app.py `server_mode`/`urlsplit` 已导入；web `request()` 透传 init，SPA JSON 变更全带 `content-type: application/json`、空体 POST 与 FormData 上传均过 CT 闸
- bench corpus `largest_remainder` 切片上界 `total - sum(q.values())` 为 int，无 float slice

## 低/info 发现（裁决建议）

1. [记档] app.py `_same_origin` 要求 scheme 相等：TLS 终结反代不转 proto 时 server-mode 浏览器同源变更会 403。当前部署形态（loopback/直连）不可达；日后上 TLS 反代需处理 forwarded proto。
2. [记档] app.py 从 `starlette._utils` 私有模块 import `get_route_path`：版本漂移风险，当前 pin 环境有此符号；升级 starlette 时留意。
3. [记档] local Host 闸盖全部路径（含静态 SPA）：DNS rebinding 收口是有意的，副作用是 LAN 主机名访问一律被拒，只能 localhost/127.0.0.1/[::1] 或显式 cors_origins。测试已钉死该口径。
4. [不动] unpack.py `_reconcile_aliases` 仅在任一侧为 symlink 时复制 kind/link：dir↔file 别名 kind 不一致不调和，但该形态 tar 实践中不可达（同 loc 冲突落盘者即 winner，mtree 记 winner 即正确）。
5. [不动] rules.yaml misschar/font_fallback `when` 加 warn_utf8：日志无 Missing char 时求值后 applied=False 直落，注释已声明，良性。

## 逐域净面

- bench/py + bench/ts + .pre-commit：净（双哈希校验、fetch_blob 短读复检、`Ruleset.load()` preflight 均核实）
- latex（gullet/segmenter/macro_table/flatten/scanner/tables）：净
- fixloop（rules.yaml + builtins 消费端）：净（yaml 单引号 `\\g<0>` 语义正确）
- compile/engine + arxiv/unpack（`_member_loc`/`_reconcile_aliases` 仅 _TarWalker.finish 调用，正确）：净
- server（app/settings/worker）+ share：净（SEC-1..7 闸序 Host→Origin→CT→auth；dispatcher/heartbeat except 面收窄正确；share _ZIP_ERRORS 收口 + publish precheck 在 try 内 finally 清 tmp）
- tests：净（4 个新 audit 文件钉的是新行为；TestClient base_url autouse monkeypatch 正确；`_rs()` lru_cache 惰性加载消除收集期 IO）

## 整体放行判定

**放行（静态审零回归）**，附一条未竟项：计划中的 pytest 兜底批次因环境级 Bash 故障（磁盘配额，全 agent 同现象）未能执行。恢复后补跑清单：

```
uv run pytest tests/test_server_gate.py tests/test_gullet_audit.py tests/test_segmenter_audit.py tests/test_macro_table_audit.py tests/test_v1arm_audit.py tests/test_fuzz_share.py tests/test_fuzz_unpack.py tests/test_fixloop_rules.py tests/test_fixloop_f1f2.py tests/test_fixloop_aux_eof.py tests/test_fixloop_spikereplay.py tests/test_worker_audit_fixes.py tests/test_share_hook.py tests/test_bench_regression.py tests/test_app_endpoints.py tests/test_server_api.py tests/test_server_byok.py tests/test_structpos_residual.py -x -q
```

全绿即无条件放行。静态维度本波可放。
