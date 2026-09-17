# worker-fuzz — worker.py 管线边界对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_worker.py`（1163 行，commit `ea4b148`）：**53 passed + 12 xfailed(strict, 0 xpass)**，ruff check/format 双净。纯离线、确定性、无真实子进程/网络。

## 覆盖面（53 绿面）

unpack_zip 名称矩阵+200 组 fuzz confinement/caps/NUL/加密成员→UnpackError；sniff 矩阵；_share_row 4000 例 outcome∈枚举+upd JSON-able+非 pending 不重判、validate 闸；_share_apply 零命中/doc 形状拒绝不写库、非 str src_file str()-归一命中；_share_lookup 伪造 mark 摘除+正 key 复原 hit；load 容忍非 list warnings、跳过 pending/未知状态；_flush_translate 事务落盘+publish 在 commit 后；EventBus 溢出 _RESYNC+摘订阅+落盘可重放；verdict 巨型非 ASCII detail error_json 字节级 round-trip；transition 不可序列化 error 零污染；_log/_warning secret scrub；_on_loop 同线程直调/跨线程回弹；_md_member 4000 例段级安全；chunk_error_code 归因域。

## 缺陷台账（7 族/12 xfail，docstring 含 file:line/repro/impact/fix）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| W1 | `zf.read("mimetype")` 只捕 KeyError | worker.py:1012 `sniff_upload`/`_zip_kind` | 加密成员 zip（flag bit0 置位）抛 RuntimeError 逃逸 → 上传边界 500 | 补捕 RuntimeError 或退 upload_tex 交解包处报错 |
| W2 | `_scrub_deep` 只递归 list/dict 值 | worker.py:288-291 | tuple 成员与 dict 键原样放行，json.dumps 后 secret 明文进 error_json/task_events | `(list, tuple)` 递归 + 键也 scrub |
| W3 | flush/teardown 四面失序 | worker.py:2080, 2039-2041 | (a) `state.buffer=[]` 在 flush_chunk_batch 之前清空——瞬逝 DB 错永久丢已译记录；(b) teardown flush 一炸跳过 `_invalidate_splice`→哨兵行滞留→下轮编译出陈旧 zh；(c) 同炸跳过 `_aclose_clients`→httpx 池泄漏；(d) flush 异常盖掉触发 teardown 的原始异常（AuthTripped 错标 internal）。同款 finally 形状还在 2589/3071/3651 三处 `_persist_usage→aclose` | buffer 成功后清；teardown flush 包 try/log 续 invalidate+aclose |
| W4 | `float(ctx.row["created_at"])` 无兜底 | worker.py:1343 `_stats` | 腐化 created_at 时 _fail/_reject/cancel 臂在 transition 落终态之后、publish done 之前炸 → 行已终态但 done 永缺，stream() 活订阅者挂死 | 容错 float |
| W5 | `DBStateBridge.load` 无兜底 | worker.py:716-717 | `json.loads(warnings)`/`int(attempts)` 对腐化格（'{bad json'/BLOB/'abc'）炸 → run() 归 parse retryable=False → 同一腐化行任务永 fault、库内译文不可恢复 | 坏格容错 []/0 或行降级 |
| W6 | translation 落 BLOB → atomic_json TypeError | worker.py:3267/3272 `_build_dual` | compile 收尾炸、dual.json 不落 | DB→doc 边界 coerce 非 str |
| W7 | zip 成员名缺 NAME_MAX 闸 | worker.py:990-998 `unpack_zip` | 单段超 255B 的合法 zip 名在 `target.is_dir()` 炸 ENAMETOOLONG OSError 逃逸解包循环（前序成员已部分落盘）→ run() 归 parse 整单 fault | 成员写体包 try OSError → reject 告警跳过 |

## 未钉观察项

- `store.snapshot`（store.py:~874）error_json `json.loads` 无兜底——app 面 scope，交 app 侧裁决。
- `_share_lookup`（worker.py:2287）：share mark 有效时覆写非 share: 的 `reuse_hit`（dedup 来历被 clobber）——可达性低。
- `_on_loop` 对已 close 的 loop 走 call_soon_threadsafe → RuntimeError；schedule-后-close 会 fut.result() 挂死——shutdown 竞态，未钉。
- BLOB src_text 经 str() 落 fallback_orig 译文产生 repr 垃圾（静默腐化面，非崩溃）。
- 非 list warnings（'123'/'"x"'）载入不崩但 warnings 语义漂移——绿面已钉不崩。

探针在 `tmp/worker-fuzz/`（gitignored）。
