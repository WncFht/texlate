# overseer-selfimp 台账（append-only）

> selfimp 常驻环编排台账。leader=texlate-5d（archbox 本机）。每条一行事实：时间/车道/动作/证据指针。车道交付物在 `tmp/lane-<slug>/`，落账指 mechanisms.jsonl + rules/ + skeleton。

## 2026-09-18 环启动

- 09:10 基线口径复核：mechanisms.jsonl 210 条（covered 68 / partial 134 / implemented 8）；loop1 records 69535 行 5124 格 scorecard pdf 97.89% clean 84.99%；leak 0.040%（dollar 族 57 条残留）。
- 09:10 rt1 批（pid 4023412, xlat real arm, core+booster+hot）仍活：records 02:07 后无整篇 append 但 work/{id}/xlat-real.jsonl 09:10 仍在写——chunk 流式推进中，未 stall；nightwatch lane 接管监控。
- 09:11 跨会话边界（texlate-80 确认）：bench/py/qualbench.py judge 协议面归 texlate-80（GEMBA-MQM 化在飞）——selfimp A2 只做执行层跑批，不改 qualbench.py。texlate-37 已离线，其在飞 lane（revtex-209/o2-opaque-prose/early-eof-tax/gullet-at-scout）按未落地处理，冻结面：segmenter/args.py、builtins*.py、_builtins_shim.py（待核实死活后解冻）。
- 09:12 wave-1 发车 23 lane：A1-A5 测量面 / B1 mock 基线批 + B2 六篇回归 + B3a/b/c C-bucket 归因 / C1-scout partial 分族 / C2 dollar 族 / C3 fixloop 规则 / C4 术语表 / C7 server 裁决备忘 / C8 normalize 拆分 / C9 fuzz / C10 corpus expand+orphan / C11 上游挖掘 / RA reaudit-A 真bug批 / RB 单源收尾 / RD 测试钉 / RE 文档漂移。
- 冻结窗：C5(BATCH_MAX_CHARS)/C6(低分重翻) 分别待 A1/A2 落盘后发车；优化类改动在 Phase A 就绪前只允许归因/L0 钉/草案。

## 落账流水

（车道交付后逐条追加：lane | commit | 内容 | 门证据）
