# ADR-0007 fixloop：yaml 驱动的编译修复引擎 + 沉淀机制 + LLM 兜底

> **状态**：现行
> **日期**：2026-09-15（05 裁决 10/22）| 更新 2026-09-17（vendored_fetch 翻转定性）、2026-09-18（规则库扩面）

## 上下文

hjfy 的最大壁垒不是架构而是规则库厚度——~5000 篇人肉修复把编译错误率压到 ~5%，开源同类撑死 60%。texlate 的对位物必须满足：白盒可复现、社区可贡献、机制能沉淀。spike 期已实证 yaml 规则表救回率 16/16 = 100%（94% clean）。

## 裁决

**fixloop = yaml 规则引擎 + cases 沉淀机制 + LLM 修复器兜底**：

- 主循环：编译失败 → 解析 log（`!` 行 + 上下文 + `l.N` + 文件栈）→ taxonomy 分类 → 规则表匹配 → 命中应用固化修复 → 重编译；每轮一条规则、dedup、stuck×3 收敛；`undefined_cs_guess`（order 900 恒最后）未命中 → LLM 修复器（输入 log 摘录 + 源文件切片，输出最小 patch JSON，`old` 须精确匹配一次、只许改 wdir 内 `.tex/.sty/.cls`、banned 构造整条拒）。
- 规则基座四招（占触发 87%）：`static_precheck`（kpsewhich 预检 + 批量 tlmgr）/`install_file`/`install_tfm`/`install_sysfont`；引擎相关规则的降级路径显式登记（tectonic 无 tlmgr → `ctan_fetch`）。
- **ctan_fetch 原语**：tlpdb 离线索引（8148 包/138K basename、0.14s 构建）+ tlnet archive 解包 + cwd 平铺遮蔽 bundle——**仅限 TeX 输入层文件**；物理字体/xdvipdfmx 层走改写规则兜底（`font_sub_shim`：bbm→dsfont 类 Type1 近亲）；命中包先比 expl3/LaTeX2e 版本兼容（tlnet 只发最新，过新跳过）。
- **vendor 资产库**：off-CTAN 绝版期刊宏包（files 原件 + stubs 替身）入库按规则平铺遮蔽——「真凶不是 CTAN 缺件而是散件缺席」。
- **沉淀机制**：失败案例 → cases.jsonl → triage → yaml 规则 PR → 无回归门禁——hjfy 人肉库的开源众包等价物；mechanisms.jsonl 机制台账关联规则×机制映射。

## 理由

- E8:16 条 spike 规则无损 yaml 化；11 条引擎无关、5 条需降级（4 条汇到 ctan_fetch 原语）。
- E9/E17/E19 增补规则面：`pdftex_prim_polyfill`（读取型 `\ifnum\pdfoutput` 需 `\chardef` polyfill）、`vendored_sty_shadow`（按 ProvidesPackage 日期比较 + 错误触发 rename 隔离——同目录 IEEEtran.cls 是唯一来源盲删必死）、`minted_v3_rewrite`、`eps_route`、`non_utf8_source`（iconv 转码或注 `[latin*]{inputenc}`）、`pstricks_dvips_preflight`、`bbl_stub_shadow`（`\bibliography{x}`→`\input{main.bbl}` 阻断 stub 遮蔽）、`font_sub_shim`、ctan_fetch 版本兼容前置。
- 2026-09-17 vendored_fetch 实证：492 格全 fail 面一波打到 73.2% clean、scorecard clean +101——「机制归因 → 资产化 → 重跑」闭环打通。
- 证据：主仓 `docs/05` E8/E9/E17/E19；调研档案 `research/latex/fixloop-rules.md`、`research/latex/ctanfetch-probe.md`、`research/latex/pstricks-route.md`。

## 演变

- 规则数：spike 16 → 产品化 25（09-15）→ 31 → 70 → 96+（09-18，16 分片）；taxonomy 分类表同步扩至百余行，物化进 records。
- 2026-09-16：fixloop 接入 e2e/worker 产品链（此前只 bench 层跑）；同波 P0 安全修复（路径逃逸/glossary 读面/脱敏挂载）。
- 组织演进：rules.yaml 拆 `rules/` 16 分片（base/taxonomy/warnings/route/install/graphics/font/prim/misschar/encoding/pkgopt/syntax/bib/shim/shim-legacy/targeted），builtins 拆十二叶 facade + `vendor/` 资产目录；审计裁决维持「~100 规则时按域拆包」的治理位。
- LLM 修复器：`llm_hook.py` 实装精确匹配 patch 契约，模块级信号量压网关并发。

## 现状

实现落在 `compile/fixloop/` 包：`engine.py`（主循环 + LlmHook 协议）、`actions.py`、`ruleset.py` + `rules/` 16 分片（两百余条规则与 taxonomy，条目数以生成源为准）、`cases.py`（沉淀）、`llm_hook.py`、`_builtins_*` 十二叶 + `builtins.py` facade、`vendor/{files,shims,stubs}`（两百余件 off-CTAN 资产）；`ctan.py`（tlpdb/tlnet/cwd 遮蔽）与 `logparse.py` 已归位 `compile/` 层直引，不在包内。效果面：scorecard 5124 格 union pdf 97.89%、clean 84.99%（2026-09-18 口径），fixloop 是单一最大杠杆（接入当日 union pdf +18.9pt）。
