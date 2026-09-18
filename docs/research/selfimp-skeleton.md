# selfimp skeleton — 假设/想法储备池

> 每轮 Phase C 车道假设从这里取；rejected 假设留档防重复派。新条目必须本机验证过（有证据指针），上游搬运要标出处。状态：`open` / `adopted` / `rejected:<原因>` / `blocked:<依赖>`。

## open

- `C5-batch-amortize`：BATCH_MAX_CHARS 2000→~8000ch，prompt 摊销 68%→<40%。证据：xlatbench cost-model（review-2026-09-18 §3）。blocked:A1 计时落盘后裁决。
- `M8-lowscore-rexlat`：judge<3 chunk 换 swe-2-high 重翻闭环。blocked:A2 基线。
- `prose-recall-opaque`：`_handle_unknown_cs`/`_handle_argspec_cs` `[[CMD]]` 探针臂同型蒸发散文参（1803.00127 实证）；复用 `_opaque_arg_prose` 判据。注意 args.py 冻结窗（37 遗产核实）。
- `missing-file-x23`：first_error 大头 missing_file×23 → vendor/stubs 扩面或 tlmgr usertree 热包预装。
- `loader-withoptions`：RequirePackageWithOptions/LoadClassWithOptions 召回缺口（w2 裁决：刻意子集外真缺口，wave-3 项）。
- `passoptions-class-misfile`：PassOptionsToClass 类名误入 packages 集（normalize .sty 探测恒 miss，预先存在缺口）。
- `stale-stub-shadowing`：fixloop precheck「文件已在」跳过重投 → 旧 noop stub 遮蔽新真 stub（1907.03745 实证，37 移交）。修法=注入件指纹+precheck 比对。
- `en-residue-rexlat-redline`：EN 残留率 >X% 进 L2 重翻红线（repair_l2.py，untranslated_spans 主因缩写/专名，en_residue 免费信号）。
- `c0-json-strip`：LLM 输出裸 C0 字符双杀——slots JSON `json.loads` strict 拒收整批弃置（8 槽一轮归零，两轮后 fallback_orig），纯文本路径 C0 落进 .tex → compile `invalid_char` 且 `non_utf8_recode` 不修（合法 UTF-8 控制符不在其域）。修法 = translate_fn/slots_fn 入口剥 `[\x00-\x08\x0b-\x1f\x7f]`。证据：pipeline.py:664 `json.loads(_strip_json_fence(raw))` 无清洗 + 本机复现 `\x0b` 入串 → JSONDecodeError → `return {}`（tmp/lane-c11-upstream 实验）；上游 BabelDOC PR #612 "Strip C0 control characters from LLM JSON output" 生产实证同坑。
- `auto-extract-glossary`：LLM 逐篇术语抽取喂 glossary（上游 babeldoc `auto_extract_glossary` 默认开：automatic_term_extractor.py 术语师 prompt 限定 ≤5 词域名词/具名实体、排数学项、JSON `{src,tgt}` 出，逐篇共享上下文去重 + **同 term 多批抽中不同译名→多数表决**（translation_config.py:99-119 finalize_auto_extracted_glossary `Counter.most_common`）；消费侧 `get_active_entries_for_text` 按批过滤注入——与 texlate `doc_filter` 同构）。texlate 侧消费件全在（glossary.py 五层装载含 `glossary.local.yaml` 层 + doc_filter 烤进稳定 system prompt），缺的只是生产臂；terms/ 仅 cs.* 五表 ~1790 行（physics/math/cond-mat/quant-ph 零覆盖 = C4 手工扩面瓶颈），抽取臂天然覆盖全 arXiv 类目。证据：tmp/refs/BabelDOC automatic_term_extractor.py:31-66 prompt 全文 + translation_config.py:72-119 抽取/表决/成表三件 + glossary.py 消费件；本机 `ls xlat/terms/` 仅 cs.AI/CV/LG/ML/RO+default。
- `abstract-context`：论文摘要（≤~6k 字符截断）作 `paper_context` 注入请求——主题/术语锚定，"only for topic and terminology, never append"。texlate system prompt 无文档级上下文槽（prompts.py:213-245 仅 kind 条款 + glossary 尾块）；摘要已是 `kind="abstract"` chunk 可直接从 ScanResult 取，烤进 system prompt 不破坏逐篇恒定（前缀缓存前提保住，与 doc_filter 同构）。证据：tmp/refs/texglot app/llm.py:349-381 paper_context 注入面 + jobs.py:518 extract_paper_context（不执行 TeX 的截断抽取）；BabelDOC 同族实现 `contextual_hints_block`——每批注入论文首个 title + 最近 section title（il_translator_llm_only.py:909-934）；prompts.py 全文无 doc-context 槽。
- `delim-param-args`：`\def\x#1<delim>` 定界参宏调用侧参数不消费 → 参数散文 + 定界符双双裸落正文（`\def\formula#1\stop{$#1$}` 调 `\formula x^2+y^2 \stop` → `[[MACRO_1]]` + `x^2+y^2 \stop` 原样进 chunk——数学内容漏译风险 + `\stop` 裸 cs 落译文）。证据：segmenter/args.py:1096-1119 `_handle_opaque_macro` gullet Arg→ArgSpec 映射 `delim`/`until_group`→零宽 `ArgSpec("b")`（1099-1100 注释自证）+ 本机复现（delim-math 实验，content 含裸 `x^2+y^2 \stop`）+ corpus_v3 15+ 文件含定界参 def（0806.3247 用户级 `\def\bbra#1,#2,#3` 数学包装、0707.2151 `\FetchLabel@#1(#2)#3\\`）；上游 texglot collect_math_aliases 专门收 `#1<delim>` 数学包装 → DelimitedMath（latex.py:893-926）。注意 args.py 冻结窗（37 遗产核实）。
- `quoted-input-filename`：`\input{"a b.tex"}` 引号文件名不解析 → `missing_input` warning + 目标文件内容静默漏翻。证据：tables.py:504-506 `FILENAME_CHARS` 无 `"`（braced 形 fname 带引号进 `_resolve_input` 恒 miss；bare 形 `"` 不入字符集直接不触发）；本机复现 tmp/lane-c11-upstream/quoted/——`input:"sub file.tex"` warning 在但 included 内容缺席 chunks；上游 latexpand `$ARGQUOTED` 专支 `\input{"f n.tex"}`/`\input"f n.tex"` 两形（gitlab.com/latexpand/latexpand 源）。
- `original-repair-carry`：先编译原文、诊断修复（缺包 stub/编码/模板冲突）带入翻译管线——LLM 读已修源 + 译文编译少重发现修复 + 不可修篇烧模型前就拒。texlate 现状 = normalize→translate→compile（e2e.py:571-599，fixloop 只见译文文档），`base_condition` 原编臂存在但 bench 归因专用（e2e.py:622）——机制都在，产品管线不跑。成本 +1 原编周期。上游 texglot 1.0.4 "Carry original-compilation repairs into target-language preflight, translation, source exports and cached retries" + 1.0.2 "Validate source reconstruction and target-language layout before model requests" 双版本实证此设计（CHANGELOG）。

## rejected（留档防重派）

- M1 公共缓存 registry — 2026-09-18 用户裁决否决。
- Electron 客户端 — 同上否决。
- 横向扩库 →10k/50k — review-2026-09-18 §4：边际已塌，只定点扩盲区。
- parse_tex_v1(None) 严格化对齐 v2 — w2 结案：保持不对称各有据。
- LOADER 词表逐字节全并 — w2 裁决：各站刻意子集，真缺口只有 *WithOptions 两站（见 open）。

## blocked（等依赖）

- C5/C6 见上。qualbench judge 协议面改动 → texlate-80 车道，本池只提需求单。
