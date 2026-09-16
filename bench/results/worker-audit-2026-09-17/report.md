# worker-audit — server/worker.py 审计交付

> 2026-09-17 收口。落地 `2c92a7b`（worker.py + test_worker_audit_fixes.py，+347/-24）。自验 `pytest -k "worker or share"` 219 绿、ruff 双净。leader 追加：`_stage_share_apply` 同款哨兵补丁（预留在飞区已解封，方法复用 `_invalidate_splice`）。

## 修复清单（7+1）

1. **`.splice-done` 过期哨兵**：retry/resume 重进 translating 段改 chunks 行（pending→ok/重译），旧哨兵让 `_build_zh` 直跳、旧译文永留产物。`_teardown_translate`（finally 全路径）比对 pre/post `(status,translation)` 快照，变即摘哨兵；`_build_zh` rmtree zh/ 时 `.compile-done` 同死重编。无变化不动，resume 直进编译臂。
2. **`_stage_share_apply` 同款哨兵**（leader 追加，原报为未修项）：share 任务 retry 换包重对账改 chunks 行同样致哨兵过期。`_share_apply` 前后快照 + `_invalidate_splice` 复用。
3. **`_sync_fixed_sources` 删除侧漏 `_` 前缀排除**：copy 侧排除 `_*` 顶层项但删除侧没有——`zh/_tect_out/`/`_minted-*/` 内 `.tex` 被误删。两侧同口径。
4. **`unpack_zip` 成员级损坏**：`zf.read` 的 BadZipFile/NotImplementedError/RuntimeError/OSError 上浮 → `internal` 可重试 fault（腐坏包重试必再败）。归 `UnpackError`（不可重试侧）。顺带拆 `_zip_member_payload` 解 C901。
5. **`_aclose_clients` 单点失败**：任一 aclose 抛错中断余下清理且盖掉 finally 里真异常。逐 client try/except + debug log；`_teardown_translate` 改复用。
6. **`_make_cache` user 层按内容进指纹**：原 cfg 材料是 glossary 路径字符串——同径换内容串桶、异径同内容分桶、`USER_GLOSSARY_PATH` 缺省层缺席。新 `_resolve_glossary_path`：confine 解析→内容 sha256[:12]→`u:{sig}`，与 `_share_glossary_hash` 同口径。
7. **`_run_fixloop` 缺 `compile_timeout`**：fixloop 内部重编用引擎默认而非任务配置（e2e parity 缺口）。补 `compile_timeout=self._compile_timeout`。
8. **`_fixloop_summary` 丢 `log_excerpt`**：fixloop cell 终态错误上下文（≤2000 字符）未进摘要 → fixloop 事件/error_json 缺 triage 料。

## 新测试（+8 类）

TestSyncFixedSourcesUnderscore、TestUnpackZipMemberCorruption（真 CRC 翻转）、TestAcloseClientsResilience、TestSpliceSentinelInvalidation（改/不改两臂）、TestCacheUserGlossarySig（三桶态）、TestRunFixloopWiring（timeout+log_excerpt）；`test_teardown_cancels_pending_run_task` 补 `pre_rows={}`。

## 未修 / 外部路由

- **摘哨兵后陈旧产物面**：splice 失效重编失败时 `files` 表旧 zh_pdf/zh_src_zip/dual_json/compile_log 行与磁盘件仍在 → partial 发旧译文 pdf。根治需 store 加 `delete_file`（store.py/app.py 跨域）。
- **app.py main-change retry**：只删 chunks + rmtree base/zh/build-*，`files` 行/en.pdf/md.zip/`.fetch-done` 全留——换 main 后 en 侧陈旧照发。同卡 `delete_file`。
- **spec 决策**：`cache_key_for` reuse 键不含 glossary/base_url/engine/l2 等出参 options——spec §4.3 明文「故意不含」，但 glossary 任务可命中无 glossary 产出，与「产物是确定性函数」前提相抵。收不收进 reuse 键需 spec 层定夺。
- e2e parity 已核：cross-engine halt_on_error=False、L2→fixloop 序、reject→partial+reject_at、env_judge/scan_tree 分流两侧对齐。
- `_stage_fetch` 哨兵与 `reuse_hit` 摘除间崩溃留陈旧 audit 标记——纯 cosmetic。
