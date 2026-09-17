# fallback_unverified 存量与判别口径（2026-09-17）

派工口径：这桶在台账挂了很久没人定性——摸清存量分布与判别口径，判定该销项还是补洞。**只产报告，src/git 未动**。

## 结论

**定性 (a)：正常中间态**。flag 是诚实记账位（「回落后第三态源树尚未重编，验证责任结构性移交 fixloop」），实测代验兑现率 **229/229 = 100%**。真空洞存在但仅条件触发（fixloop 关/崩/precheck-reject），且已被 textutil-e2e-audit 记为文档化产品裁决。flag 键本身**零下游消费方**（纯观测位）。

## 判别口径（代码路径级）

赋值链（两臂同语义 `e2e.py:695-742` / `worker/compile.py:708-762`）：首编非 clean → `_l2_localize` 归因 → 重译 → resplice → 重编（res2）→ 仍非 clean → 二次归因 → `still_bad=hits2∩adopted` 块译文弹出回原文 → 二次 resplice → **置 flag、不再编**。flag=真 ⇒ 盘上是「部分块回英文」的第三态，而 res2 对应的是重译态。

下游验证链：`_compile_zh`（compile.py:906-911）与 `_repair_chain`（e2e.py:881-892）同序 `v≠clean→fixloop`；fixloop **r1 恒全新编译**（engine.py:1322 `res=eng.compile(wdir,...)` 不复用旧 log）⇒ 第三态必被验。消费面仅 events.py:216 报 `fallback_src` 长度进 SSE。

## 存量（bench/results/**/records.jsonl 逐 arm 扫描）

**229 arm-格 / 133 篇 / 11 run**：modec-expand 66、postfix 46、v3-tailfix 40、sabotage 20、tec-v3 14、v3 14、core 13、sabotage/v3 8、tail 6、repro-0806 2。终态 clean 95 / partial 109 / fail 25；fixloop verdict 以 acceptable_pdf(92)+best_effort(39)+clean(35) 为主。**fl_ran=229，fl_off=0，fl_missing=0**。stagerun-loop1 无此 flag（无 L2 臂，结构性不产生）。server 实证 live-smoke2/poll2.log：fallback→fixloop r1 clean。

## 空洞判定（三条可达路径）

共同后果 = zh-src.zip 装未验证第三态 + zh.pdf 对应重译态 → **pdf≠src≠chunks 表三方分歧**：

1. `options.fixloop=false`/`TEXLATE_NO_FIXLOOP`（用户可控）
2. fixloop 崩溃 → worker `except→return first`（compile.py:515）回传 res2
3. **precheck reject**：r1 编译前返回（engine.py:1310-1318）——观测实证 1 格 `1306.1931 pipe-tec` reject:pstricks_route，终态 partial

根因时序：`_l2_repair_zh` 在 fixloop **之前** `_sync_fixed_sources`+`_zip_zh`（compile.py:763-767）。此前 textutil-e2e-audit 已记「文档化取舍」、normalize-polish 标「stale-PDF 照发属下游裁决面」悬置——本次补上量化闭环。

## 建议

1. **台账销项**：定性「正常中间态」，flag=观测位非缺陷
2. 低优先级小修（~10 行）：三条条件路径下 fallback 后补一次裸编译，或将 `_sync_fixed_sources`+`_zip_zh` 延到 fixloop 回报后——消灭 provenance 分歧
3. **测试缺口**：`fallback_unverified` 全测试面零断言（仅 test_fuzz_worker.py stats mock 命中键名），修 #2 顺手补 fixloop-off 断言
4. repro-2501 证实归因洞（任务 #78 族）错归 preamble 错误→白烧重译+制造不必要 fallback——归因修复会压缩此桶

30min 内交付。侦察：fb-scout（sid8 代写落盘）。
