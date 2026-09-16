# web-tests — 三个 web 特性 vitest 补测

> 2026-09-17。scope：web/src/test/ 新增三补角文件。vitest 17 files/118 tests 全绿、tsc/eslint 净，未 commit。

## 重要勘正

三特性**并非零覆盖**——`sharePack.test.ts`（web-sharebtn）、`homeByok.test.ts`（web-followup）、`taskStats.test.ts` 已在库，覆盖了主路径（分享钮三挂载点/成功/409+rejected+artifacts、translate 路 key 透传+清空、merge 优先级/兜底/空态）。新建三个补角文件填缺口，未动既有文件。

## 新文件（均 web/src/test/，camelCase 对齐惯例）

- `sharePackEdge.test.ts`（11 tests）：门补 3 态（translating 活动态无钮、cancelled 横幅 rp-actions 无钮、needs_auth auth 行在无钮）；错误映射补 6 支（share_pack_failed、映射外 code 回退 detail、无 code → [share_pack] 前缀、非 ApiError TypeError、409 无 code 仍映 shareErrState、空 detail 不加括注）；busy 态（pending 时 disabled+「打包中…」）；失败后重试点击二次调用且错误清空。
- `homeByokUpload.test.ts`（6 tests）：upload(.tex) 与 shareImport(.share.zip) 两路第三参 {apiKey} 透传+成功清空+nav；无 key → undefined；**失败保留字段值**（upload/translate 两路，「成功即清」契约反向锁定）；上传路 putSettings 零调用。
- `taskStatsEdge.test.ts`（8 tests）：逐字段独立兜底（stats.tokens 胜 + counters.failed 补位）、?? 语义（chunks_failed=0/tokens=0 不回退）、usage 零值点亮、usage 仅 model → null、done.stats 未知附加键 → null、仅 seconds 点亮、toStrictEqual 锁七键形状。

## 结果

- `npx vitest run` 全量：**17 files / 118 tests 全绿**（含 web-idem 在飞的 idempotency.test.ts，无干扰）
- `npx tsc --noEmit`：exit 0
- `npx eslint <3 files>`：exit 0

## 产品 bug

无。顺带观察（非 bug）：submit() 409 冲突跳已存任务时早退未清 optKey——组件随即 unmount，无实际影响，未锁定该行为进测试。
