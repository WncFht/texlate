# validate-audit — src/texlate/validate/ 审计交付

> 2026-09-17 收口。落地 `2ed90e9`（l0/l1/l2 + 三测试文件，+391/-80）。自验 `-k "valid or l0 or l1 or l2 or judge"` 284 passed/1 skipped、ruff 双净。探针 tmp/validate-audit/（fp/l0_key/l0_misc/l2/post 五组）。
> **归因注记**：l2.py 与 test_validate_l2.py 含 compile-core-audit 在飞 hunks（`_MISSING_CHAR_RX` 双格式/`fffd_glyph` 类/`_classify_warning` 分支 + 2 测试）——合并态绿、随本提交先落，commit body 已注双来源。

## 修复清单（11 项）

### l0.py（误报清扫，全部实证）

1. `PH_FUZZY_RX` 三臂加 ASCII lookahead——`【图1】`/`[[图]]` 中文自然全角用法原全报占位符 error 白触发重译；真变体 `【MATH_1】` 仍被 lev 捕获。
2. `_pair_placeholder_typos` lev 改 `upper()` 折叠——小写变体配对成「拼错+修复建议」，不再双报缺失+多余。
3. `KEY_CMD_RX` 收口 `*cite` 后缀族（parencite/footcite/textcite…`[a-zA-Z@]*cite[a-zA-Z]*` 前后缀）+ `addbibresource`/`addsectionbib` + `*bibliography(style)?` + `*refrange` 双 key 臂——原前缀形漏掉整个 biblatex 后缀族。
4. `_key_multiset` group 1-3 逐组点算（refrange 双 key）。
5. `_cs_names` bs token `\`+空白归一 `\\ `——TeX 控制空格等价互换不再误报（`Bahdanau\␤et al.` 双向实证）。
6. `_check_item_glue` 后缀须含大写——`\itemsep`/`\itemize` 合法 cs 不再误报；`\itemFSU` 仍中。
7. `_check_env` end 名偏多 warn 先过滤再截断——cap-before-filter 曾把真 warn 挤掉。
8. `validate_pair` docstring「十组」→「11 组」。

### l1.py（通道健壮性）

9. 依赖双查 `tree-sitter` + `@pfoerster/tree-sitter-latex`——原文法缺失时 available() 误判。
10. `_pump` EOF/死进程投 None 哨兵；`_one` poll() 死进程→透明降级批处理；响应按 id 配对循环（迟到/错序丢弃续等）；EOF 立即 L1Error 不白挂 timeout；`TsResult.from_dict` None 安全。

### l2.py

11. `_REDLINE_CLASSES` 补泛 `missing_glyph`（非 CJK/非 FFFD/码点不可解）——`("3B)` 2 位码点等此前完全逃逸红线；`{4,6}` hex 保持（2-3 位由 generic 兜住）。

## 新测试（+15）

l0×8（全角 FP/小写变体/*cite 后缀族/refrange 双参/addbibresource/item_glue 豁免/间距等价/env cap）、l1×4（双依赖/id 配对迟到行/EOF 哨兵/死进程降级）、l2×3（U+8BD1→missing_glyph_cjk 红线、U+FFFD、非 CJK missing_glyph）+ 2 条 compile-core 同文件增量。

## 未修（理由） / 外部路由

- `file_not_found` 红线宽于 spec 具名集——缺资源方向 fail-safe 保留；`$x$`↔`\(x\)` 双 math error 是 spec 计数一致性明文；`ph_in_cs` 尾邻字母盲区 docstring 已记档（拿不到 ph_map 判不了类型）；`report.py` 休眠模块不动；l1 错序响应只弃不重派（REPL 无重放语义）。
- **三份并行 parse_log 口径漂移**：engine.py / fixloop/logparse.py / l2.py 错误计数与红线语义各写各的（judge WARNING_RED_LINES vs engine `_ERR_FILELINE_RE` 不同步）→ 已转项目体验方式（logparse owner）。
- **docs/08 §2.1「十规则」→11 + §4.3 红线描述** → leader 已修。
- judge `warnings_hit` 无条件 vs `expect_cjk` 只闸 render——与 spec 一致仅记录。
