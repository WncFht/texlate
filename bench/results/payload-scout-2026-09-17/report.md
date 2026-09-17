# payload-scout — `<verdict>:<payload>` 幻 payload 定位报告

> 2026-09-17 收口（overseer 移交单，~30min scout）。只读调查零代码改动。**结论：机制确认**——verdict sig 的 payload 抓的是 `l.N` 调用点行末位 cs，宏展开时真肇事者在上下文**顶行**末位。波及 284/1146 stored excerpts（24.8%）。修法为 ~6 行 yaml 改动 + 零 Python，已对全部 1146 条存证 log_excerpt 验证 100% 对齐顶行 oracle。

## 1. 提取位点

- `rules.yaml:306-311`——generic `undefined_cs` 条目，`pattern: "Undefined control sequence(?:[\\s\\S]*?l\\.\\d+[^\\n]*\\\\([a-zA-Z@]+))?"`，`payload_group: 1`。:304-305 注释错误断言肇事者在 `l.N` 行末。
- `rules.yaml:297-302`——空 `l.N` 变体（2026-09-16 为 `headerps@out` 加），先评估，同取向。
- `logparse.py:181`——`head = rep.first + "\n" + rep.ctx`；`rep.ctx`（:107）从错误行起，故 `! Undefined control sequence.` 出现**两次**（index 0/1），真上下文顶行在 index 2。`pay = _payload(entry, m)` :186；`subclassify` allowed-set `{pay} ∪ _ctx_tail_css(ctx)` :193-202。
- `stagerun.py:1301-1305`——`fpay` = reversed(rounds) 首个非空 pay/payload；:1324-1330 合成 `sig = f"{fv}:{fpay}"` 写 `rec["errors"]`。
- 同一 `Taxonomy.classify` 喂全链：fixloop engine（engine.py:1332，rounds 存 category/payload :1350-1351，stuck-sig `f"{cat}:{pay}"` :1383）、judge（judge.py:173-191 经 classify_error，engine.py:372-386）、compile 段 `verdict_sig`（benchlib.py:165-199）。**一处 yaml 改全链愈。**

## 2. 机制——实证确认

TeX 帮助文本自述肇事者在错误上下文**顶行**（错误行后第一行）末位 cs；`l.N` 行仅在无宏展开时等于顶行。宏展开中 `l.N` 是调用点——`l.\d+[^\n]*\\cs` 抓到调用者（`\end`/`\maketitle`/`\begin`/`\author`/`\section`…）而非失败 cs。

真 log 实证（顶行 vs 记录 payload）：

- 0806.2022：顶行 `\@elseads ... \@@tmp } (Victor Kalvin\thanksref` → 真凶 `thanksref`；`l.217 \end{frontmatter}` → 记 `acceptable_pdf:end`。
- 0806.3220 / astro-ph/0307062：`\maketitle` 展开 → 记 `maketitle`，真凶 `email`。
- cond-mat/0111097：`\@maketitle ... \@recdate` → 记 `maketitle`，真凶 `@recdate`。
- 1206.1993：`\Bar ->\bar` → 记 `Bar`，真凶 `bar`。
- realn200 `endsl` 案 → 记 `end`。

观测幻影 payload 分布（`end`/`maketitle`/`begin`/`author`/`section`/`Bar`/`relax`/`usepackage`/`kern`/`hsize`/`pi`/`cortext`/`includegraphics`/`name`/`dodoi`）全是教科书调用点 cs 名——无其他机制能产此分布。

## 3. 波及面

Oracle = 顶行末位 cs vs `l.N` 行末位 cs，对全部存证 `log_excerpt` 含 "Undefined control sequence" 行（bench/results/*/cases.jsonl + cells.jsonl）：

| run dir | phantom / ucs-excerpt rows | % |
|---|---|---|
| stagerun-loop1-2026-09-16 | 248 / 1027 | 24.1 |
| fixloop-cbv4 | 8 / 42 | 19.0 |
| fixloop-v2-rules | 6 / 15 | 40.0 |
| fixloop-corpusv2 | 6 / 12 | 50.0 |
| verifier-batch8 | 4 / 8 | 50.0 |
| fixloop-zh-cbv3 | 4 / 10 | 40.0 |
| docstyle (2 dirs) | 4 / 4 | 100 |
| missing-file-r2 | 2 / 12 | 16.7 |
| polyfill-journal | 1 / 4 | 25.0 |
| realn200-2026-09-17 | 1 / 3 | 33.3 |
| **total** | **284 / 1146** | **24.8** |

stagerun-loop1 记录内 sig 级坠落：304 个幻键 sig——`acceptable_pdf:end`×49、`acceptable_pdf:maketitle`×33、`best_effort_pdf:begin`×26、`best_effort_pdf:maketitle`×20、`undefined_cs:begin`×20、`best_effort_pdf:author`×11、`best_effort_pdf:end`×11、`undefined_cs:end`×11、`undefined_cs:maketitle`×10、`acceptable_pdf:section`×8 + 尾。按 verdict：acceptable_pdf 108 / best_effort_pdf 115 / undefined_cs 78 / unfixable 3。

幻影下被掩盖的真凶（顶行末位 cs）：`email`×32、`thanksref`×23、`collaboration@sw`×17、`bar`×16、`addressmark`×16、`corauthref`×15、`current@color`×10、`pdfcolorstack`×9、`authorblockN`×8、`@recdate`×8、`NoHyper`×8、`pdfoutput`×6、`pdffilesize`×4、`pdfshellescape`×4、`@kludgeins`×4。

**功能面影响（不止标签妆）**：

- **pdftex_prim 欠路由**：`subclassify` `\\(pdf…)` 要求命中 ∈ `{pay} ∪ _ctx_tail_css(ctx)`——~23 格真凶为 `pdf*`（pdfcolorstack/pdfoutput/pdffilesize/pdfshellescape）的滞留 undefined_cs，prim_guard 规则不可达。
- **stuck-sig 坍缩**：`sig = f"{cat}:{pay}"` 对不同真凶同 sig → 3 轮后假阳 stuck（engine.py:1383）。
- **dedup_key 坍缩**：`"{rule_id}:{payload}"`（rules.yaml:57-58）把异族肇事并入一簇——`acceptable_pdf:end`×49 实为 ≥4 族。
- **payload 键修复表不可达**：`cs_targeted_fix`/`journal_cs_polyfill`（builtins.py:1259+/1307+）永远看不到 `email`/`corauthref`/`@recdate`——payload 说的是 `maketitle`。

**邻接缺陷（独立一行）**：`stagerun.py:1144`——`"payload": v.get("payload") or tail["compile"].get("first_error")` 在 payload None 时把整条 `abs/path/file.tex:N: msg` 当 payload 存 → 5 条 `undefined_cs:/home/...` 状 sig——每篇一键的聚类毒药。

## 4. 修法建议

替换 rules.yaml:297-311 两个 `undefined_cs` head 条目：

```yaml
  # 冒犯 cs 取上下文"顶行"末位 (TeX 约定: top line 末 token 即肇事者;
  # 宏展开时 l.N 行只是调用点)。head 内错误行重复两次 (first + ctx[0]),
  # 必有后行; 顶行无 \cs 时本行不命中, 由下行裸短语兜底 payload=None。
  - id: undefined_cs
    scope: head
    pattern: "Undefined control sequence[^\\n]*\\n[^\\n]*\\\\([a-zA-Z@]+)[^\\\\\\n]*(?:\\n|$)"
    payload_group: 1
    subclassify:
      { pattern: "\\\\(pdf[a-zA-Z@]+)", into: pdftex_prim, payload_group: 1 }
  - { id: undefined_cs, scope: head, pattern: "Undefined control sequence" }
```

尾部必须**必需**非可选——可选组会在行 0（first）短语命中即匹配空串，永不再锚到行 1 副本。已对全部 1146 存证 excerpt 验证：**1146/1146 与顶行 oracle 一致（100%）**，payload None 恰在顶行无 cs 的 6 行。边界抽查：空 `l.N` `headerps@out` fixture → `headerps@out`（旧 :297 变体完全被吞并可删）；裸错误行 → `None`；截断 ctx（顶行为尾行无 `\n`）→ `$` 尾命中 cs。`tests/test_fixloop_logparse.py:154,185-206` 全部钉样语义保持。

成本：~6 yaml 行净改 + ~10 测试行；taxonomy 路径**零 Python 改动**。`_ctx_tail_css`（logparse.py:135-152）无需动——修复后 `pay` 已带真凶供 subclassify；其 `l.N` 行成员保留为无害过纳（同今日）。可选同行一行修：stagerun.py:1144 丢 `or tail["compile"].get("first_error")`。

破坏面：仅重跑时 sig 键稳定——存证记录保旧 sig；triage 簇按真凶重键（幻影簇解散）；stuck/dedup 键变精确（同凶轮仍正确坍缩）；pdftex_prim 路由 ~23 格改善。
