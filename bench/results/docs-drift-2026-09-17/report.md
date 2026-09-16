# docs-drift — docs/06–10 + README + HANDOFF 对 src/texlate/ 全量核对（漂移清单）

> 2026-09-17 收口。只读侦察，零代码改动。漂移按严重度排序：语义错误 > 计数/签名 > 接线状态过期 > 行号/措辞。行号均为当前工作区实测。

## A. 语义错误（spec 断言与代码行为矛盾）

### A1. \input 路径解析基准序 —— 三处口径互不一致
- docs/06 §2.4 errata(~:102) 与 locate.py docstring(:14-16)：基准序 = **编译 CWD(主文件目录) → 项目根 → including 目录**；locate.py `_bases`(:222-228) 实装同此。
- docs/07 §7(~:316) 与 flatten.py:55-89 / gullet.py:2208：基准序 = **including 目录 → 项目根 → top_dir → basename+.tex → 裸名**（多 top_dir 与 basename 两级，无 CWD 首探）。
- 现实：locate 建图用序 B，gullet 展开用序 C——同一 `\input` 在两阶段可解析到不同文件。docs/06 与 docs/07 直接互相矛盾。
- 建议：统一成一份权威表述（gullet 序是现行展开语义），另一处加交叉引用。

### A2. \ifmmode / math_depth —— spec 描述求值，实现硬编码 False
- docs/07 §8.2 称 GulletState 有 math_depth 字段、§8.6 称 \ifmmode 按 math_depth>0 求值。
- 实际 gullet.py:2387-2390：`\ifmmode` 恒 False，GulletState 无 math_depth 字段。
- 建议：§8.2 删 math_depth、§8.6 改「\ifmmode 硬置 False（v2 不追踪数学深度，实测未踩坑）」或补实现。

### A3. report.json 状态机（docs/06 §4.2:151-160）无实现对应物
- spec：`pending→downloading→unpacking→locating→parsing→translating→validating→compiling→done` + 终态 `no_source|pdf_only|stub|parse_failed|translate_failed|compile_failed|degraded_html|degraded_pdf`。
- 实际：store.py:150-162 是另一套 11 态机；e2e.py report["status"] 用 clean/partial 裁决词表；meta.py DegradeReason/DegradeTier 只是碎片对应。
- 建议：§4.2 标注「目标态机，现行实现 = server store 11 态（docs/08 §6）+ degrade 三层」，或改 spec 对齐 store。

### A4. C9 占位符保护条款「同步」断言失实 + 间距族两次越 errata
- docs/08 §1.1/§1.3 C9 文本列 `[[SL]]/[[PL]]/[[SP]]`（errata 补了 NBSP/THINSP 但不同步）。
- prompts.py:176-183 PLACEHOLDER_CLAUSE 实际列 5 枚；placeholders.py:64-95 保护族实为 **6 成员**（+MEDSP/THICKSP/NEGSP，各带 _RAW+sentinel）。prompt 措辞也不提 MEDSP/THICKSP/NEGSP。
- 另 spec 公式外子句未记档：`_FUSION_CLAUSE`(C8a)、`_HEADER`、`_BATCH_CLAUSE`。
- 建议：C9 条款重抄为 6 成员全表 + 声明「prompt 只列前 5」的实测现状。

### A5. docs/08 §1.5 env_judge 温度 —— spec T=0，实现 0.01
- prompts.py:347 ENV_JUDGE_TEMPERATURE=0.01，注释载明原因（3003 网关 temp=0 触发 502）。实现有理、spec 未追记 → §1.5 加 errata。

### A6. ratelimit 断路器口径 —— spec §1.3「429×2」，实现 429 **和 406** 都计 strike
- ratelimit.py:237；docs/06:48 自记「~150 发/日后 406」配额惩罚——406 计 strike 合理，§1.3 表述漏了 → 改「429/406 ×2」。

## B. 计数 / 签名 / 枚举漂移

- **B1. fixloop 规模**：docs/08 §5.1 errata「42 taxonomy/52 规则」→ 实测 rules.yaml **39 taxonomy/32 category/55 规则**；TRANSFORM_FNS errata 18@:1686 → 实测 **21 @:1844**；REWRITE_FNS=2 @:142。16 条具名规则 phase/order 核实未变 ✓。
- **B2. docs/07 §2 vs model.py**：PhType spec 16 → 实际 **17**（漏 EXPAND）；Chunk.context 默认 spec `"paragraph"` → 实际 `"para"`；ScanWarning kind spec 5 → 实际 **13**；ArgspecEntry 整类未记档。
- **B3. Engine Protocol（docs/08 §4.1 vs engine.py:822-894）**：spec 5 方法+caps:set → 实际 9 成员（name/caps:frozenset/detect/compile/probe_file/install_file/rebuild_fontmaps→bool/filemap/parse_log）；spec 举 `"shell_escape"` cap 全代码无此 cap；XelatexEngine.caps={"kpsewhich","tlmgr","updmap","recorder"}。
- **B4. L0 校验表（docs/08 §2.1）7 → ~12**：l0.py 另有 `_check_ph_anchor`/`_check_item_glue`/`_check_ph_in_cs`/`_check_bare_cs`/`_check_protocol_echo` 未入表。
- **B5. product_tier 缓存键 6 → 7**（docs/06 §4.1 vs share.py:45-53）：KEY_PART_FIELDS 含 prompt_ver，spec 公式漏。
- **B6. PH_RX 捕获组**（docs/07 §2 vs placeholder.py:18）：spec 示两组 `([[A-Z_]+)_(\d+)`；实现无捕获组。
- **B7. docs/07 §1 文件布局 9 → 13**：mouth/gullet/segmenter/prose 未入布局表。
- **B8. normalize 命名/清单（docs/08 §3.4）**：spec `_transcode_aux_bib` → 实际 `_transcode_support_files`(:981)；spec 13 项手术全在 ✓，实现多 3 项未记档：`_neutralize_junk_files`/`_shadow_broken_system_packages`/`_sanitize_ps_comments`。
- **B9. docs/09 语料库**：expand 层 3800 篇整层未记档（§4 无 expand 章节、§6 布局表无 manifest_expand.jsonl）；「~1,200 篇 ≈4-5GB」过时——MANIFEST.md:7 已写 **5072 篇**（1000+200+3800+72）。另 docs/10 §8 corpus_v2「139 篇/224.tex」与 MANIFEST 一致但盘上 ~114 目录/223 .tex（gitignored 数据本地被清过，备查非 spec 错）。
- **B10. docs/06 §3.1 批量能力无实现**：「id_list ≤200篇/次」「OAI ListRecords+resumptionToken」——meta.py 只有单 id id_list(:251)+GetRecord(:260)。§3.1 宜标「单篇路径实装，批量为语料管线/远期」。
- **B11. docs/10 B2 测试路径**：spec `tests/latex/test_bench_regression.py` → 实际 `tests/test_bench_regression.py`。

## C. 接线状态过期

- **C1. HANDOFF §3 三条缺口全愈合未回销**：worker fixloop llm_hook 已传（:2619-2625，§6.4 自记但 §3 未销）；INLINE_MAX 死常量已除（仅 bench/work_* 快照存）；build_corpus_v3 第二套 unpack 已归并（unpack_blob :965-1008 委托 texlate.arxiv）。
- **C2. HANDOFF §0 pytest 1090** → 现 collect **2642**（量级翻倍，errata 值得记）。
- **C3. 行号引用批量漂移**（断言仍真仅 :NNN 失效，~30–130 行偏移）：inject upgrade_209 :463→:568；settings RedactFilter :490→:527；worker fixloop 接线→:2619、_env_judge :1677→~:2422、is_relative_to confine :1333→:1562/:1694；store 状态机 :124→:150-162；TRANSFORM_FNS :1686→:1844；e2e fixloop import :33→:34。建议 errata 行号改函数名锚或标时点。

## D. 措辞 / 低危

- D1. scanner.py `_dispatch_cmd`(:745) 下划线前缀 vs docs/07 §3.2 `dispatch_cmd`——v1 对照臂语境仅命名差。
- D2. docs/06:148 errata 自承产物命名不一致（glossary.json vs term_dict.json），§4.1 正文仍写旧名。
- D3. docs/06 §1.1 端点表/§6 渠道表为调研证据断言，本地不可机验。
- D4. xlat/client.py docstring 仍写 127.0.0.1（实际 settings.py:40 `http://100.105.212.52:3003`）——errata 已覆盖；spec §1.7 `claude-sonnet-5-medium` 付费对照模型全代码无踪迹（DEFAULT_MODEL_PREFERENCE=4 免费模型 :51+denylist :53），若有意取消可补一句。

## 核实「无漂移」高密度区（防重复劳动）

unpack 四常量、sniff 三态+pdf_wrapper、`_add_jobname_bbl`(:362-389) 已实装 spec jobname.bbl 主张、fetch RETRY_DELAYS/DL_CAP/UA/406∈TRANSIENT、tables BUDGET/MAX_GEN/MAX_INPUTS、retry SLOTS=8+⟪S⟫+三档 backoff、batch 300/2000、term default.csv 404 行+cs 五表、state.json/term_dict.json schema、segment_key 四成分公式、judge 三态判据、inject 三态、fixloop _ACTION_KINDS=7 与 verdict 词表、e2e B5 mock 函数齐、corpus_v3 manifest 1000/200/72/144、fixtures 33 件、客户端免费集动态发现链与 spec §1.7 全对得上。

## 处置建议（leader）

- 文档修复走 errata 惯例（追记不重写）；A1 需 1d 确认权威基准序表述（gullet 序是现行展开语义）。
- 修复执行归 leader（.md 拦子代理）——按 A→D 序做，B 类计数多为一句话订正。
