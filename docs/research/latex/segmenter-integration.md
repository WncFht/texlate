# Segmenter 接线契约：scanner → token 流重写（设计与落地记录）

> **结论**：分段器重写为 token 流消费者——一切源消耗经 gullet `next_expanded()`，字节只在切 raw 片时按 token `(fid,start,end)` 取；叙事序虚拟文本 vtex 让下游（pieces 平铺/validate/reconstruct/parsebench identity）零改动；S1–S4 切片全部落地，corpus_v3 1955 文件 identity 100%、leak 收至 63 且全为良性族。
> **状态**：现行（已落地为 `latex/gullet/` + `latex/segmenter/`，v2 为唯一解析路径，v1 字节 scanner 已删除；规范见 `spec/latex-pipeline.md`）
> **日期**：2026-09-15

记录 v1 字节状态机分段器重写为 `next_expanded()` 消费者的设计契约与 S2–S4 落地实测——gullet 侧规格见 `expansion-design.md`；开发机 bench 现场（parsebench 归档、双跑 diff）不随库发布。

## 0. 总形状

```
file bytes ──► Mouth（逐文件 tokenize，catcode 共享表）
           ──► Gullet（不动点展开 + \if 选支 + \input 压栈 + def 登记）
           ──► Segmenter（消费 token 流 → pieces/chunks/ph_map/warnings）
```

分段器**永不直接前读字节**：一切源消耗经 token 流；字节只在「切 raw 片」时按 token 的 `(fid, start, end)` 从 `file_texts[fid]` 取。保住三条铁律：字节级 identity、注释不可见即边界、展开只做分类不做物化（`gen>0` token 的 pos 不做 splice，`origin`/`src` 才做）。

## 1. vtex——叙事序虚拟文本（position mapping）

**决定**：不按 `(file_id, offset)` 改造下游，而在分段器里增量物化一条 vtex（virtual text）= `flatten_inputs` 产出的同构文本；一切 piece/chunk/span 用 vtex 坐标——`pieces` 平铺 `[0, len(vtex))` 不变式、validate_result、reconstruct、parsebench identity 全部零改动。

- 每文件维护消费前沿 `cons[fid]`；源区间 `(fid,a,b)` 被「覆盖」时 `vtex_parts.append(file_texts[fid][a:b])`，vtex 区间 `[vlen, vlen+b-a)`，`cons[fid]=b`。
- 覆盖驱动 = token 到达：gen=0 token `(fid,a,b)` 到达时先覆盖 `[cons[fid], b]`——**间隙字节（注释/折叠空白）随覆盖自动进 vtex**，这是 Mouth 吞注释后 identity 不破的机制。
- `\input` 成功：调用点字节不进 vtex（marker piece 记 `inputs[]`，输出物不含 `\input` 行——与 flatten 替换语义一致，不双重 include）；子文件字节随其 token 到达序接进 vtex → 叙事序天然正确。
- 单文件 `vtex == tex`；多文件 `vtex == flatten_inputs(main)`（模 `\endinput` 行保留之差，已接受留档）。
- 乱序例外（`\expandafter` 让后位调用点先展开）：`src.start < cons[fid]` 的展开组做不到单增映射——放弃 vtex 内联，按 `[[EXPAND_n]]` 保护，记 `expand_reorder` warning。

## 2. 覆盖账本与 run 双轨

run 项升级为 `(surface, ident)` 双轨：

| 来源                 | surface（进 chunk.content/译文面）       | ident（identity 面）                                                     |
| -------------------- | ---------------------------------------- | ------------------------------------------------------------------------ |
| gen=0 文本 token     | `t.text`（space 已折叠，译文面要折叠形） | `vtex` 切片 `[cov_start, t.src.end)`——含前导间隙（注释随 identity 保留） |
| ph 项（MATH/CITE/…） | `[[X_n]]`                                | 同一 token（ph_map 体即原文）                                            |
| 展开组               | 展开表面文本                             | `[[EXPAND_n]]` token（体 = 调用点 vtex 切片）                            |

- 非 chunk 冲刷：piece.text = `join(ident)`——注释、展开调用点原文全部逐字回，identity 零新机制。
- chunk 冲刷：content = `join(surface)`；identity 经 `ph_map["[[CHUNK_k]]"] = vtex[gspan]`——利用 `expand()` 现成的 `trans → ph_map → content` 优先级，零 schema 变更。仅当 run 含展开组才登记（`run_has_expand` 旗标），常态无额外开销。
- 溢出二次切分（`_split_core`）：part 边界落在展开组**整组**归属侧；各 part 的 `ph_map[CHUNK]` = vtex 连续切片，区间覆盖无缝。
- `lead/trail` 空白剥离：含展开组的 run 跳过（整 run 进 content）；纯 gen=0 run 维持原行为。

## 3. 展开组的流内形态

- **判定**：`t.gen > 0` 即展开产物。同 `origin`（最外层调用点 `(fid,a,b)`）的连续 token 为一组；组内 gen=0 arg token（pos 落在调用点区间内的真源 token）同属该组——组界 = 首个「gen>0 且 origin≠组」或「gen=0 且 pos 不在调用区间内」的 token。
- **调用点区间 = 整调用**（`\sw{a}{b}` 全段），不是 trig.pos 的 cs 名区间——gullet 侧补打为 `(trig.fid, trig.start, trace末位.end)`。
- **surface** = 组内 token 文本拼接（`eol_par`→`\n\n`、space→` `、cs→`\name`、param→`#`…按 Tok.text 渲染规则）。
- 组内再生保护段（展开文本里的 `$…$`、`\cite{…}`）照常走分段规则产 ph——ph 体是展开表面切片（vtex 里无对应字节，identity 由 chunk 级 `ph_map[CHUNK]`/run 级 `[[EXPAND]]` 兜底）。
- 展开组内 `eol_par` = **虚拟分段符**：flush run、不产字节；组的后半挂进下一 run，其覆盖字节已在上一 run 计过 → 记 `expand_span_reuse`（罕见病理）。

## 4. gullet 侧配套缺口（已全部实施）

落地时补齐的 gullet 侧机制：`_consumed` marker 族（`def:`/`newcmd:`/`newenv:`/`newtheorem:`/`mathop:`/`xparse:`/`let:`/`newif:`/`catcode:`/`if:`/`input:`/`endinput` 系）、`Mouth.resync` + `gullet.skip_past(fid,pos)`（tokbuf 残骸剔除、栈深找 fid、i 只前进）、`_stamp_call_origin` 补打整调用区间。segmenter 侧实测补丁五条（均为 v1→v2 移植暴露的留档级陷阱）：

- **零宽 span 是 falsy**：`Span.__len__` = `end-start`，`x or Span(0,0)` 式兜底会把 `Span(v,v)` 落成 `Span(0,0)`——判空一律 `is None`。
- **组内 consumed marker 不破组界**：gen>0 marker 的 pos 是定义体区段（早已覆盖、零宽即可）；`\document` 级大宏展开体内含 def/if/input marker 属常态；仅 input 型组内也记 `inputs[]`。
- **零宽 surface 项归段**：`_close_group` 的 eol_par 分段可产出 `surface==""` 但 vspan 盖真实 callsite 的 run 项（如 `\def\abs{\par…}` 展开面以 `\par` 开头）。`_slice_items` 对零宽项按 `acc >= lo and (acc < hi or acc == hi == end)` 归段；其 ident 一旦进 chunk identity，callsite 字节必须折入段 gspan（gspan 取分段项界并集），否则尾部 `_emit` 把同段字节 raw 再发 → 双发 diverged。
- **零宽 callsite 不签 EXPAND**：嵌套展开里内层组 callsite 已被外层盖过（vspan 零宽），签发 `[[EXPAND_n]]` 只会被零宽 run literal 冲刷时 `_emit_text` 的 `vend > vstart` 守卫连 piece 带 token 丢掉 → dead_ph。`_close_group` 对 `vspan.end == vspan.start` 直接置 `ident=""`。
- **filecontents 行首锚定**：kernel 语义是逐行读体、`\end{filecontents}` 行首独占才闭合——体内 PostScript/注释里的行中 `\end{…}` 全是字面负载。verbatim 路闭合查找对 filecontents 族改用 `(?m)^[ \t]*\end{…}` 锚定；`filecontents+`/`filecontentsheader` 变体补登 `_VERBATIM_BASE`。

## 5. 分段器主循环（dispatch 19 行 → token 版）

```
while t := gullet.next_expanded():
    t.kind == "cs"        → dispatch_cmd(t)            # 19 行分派逐行移植
    t.kind == "mathshift" → _on_math(t)
    t.kind == "eol_par"   → flush_run                  # gen>0 见 §3 虚拟分段符
    t.kind == "space"     → run.append((" ", vtex 切片))
    t.kind == "consumed"  → flush + LITERAL + 副作用登记
    其余（letter/other/active/lbrace…）→ run.append((t.text, vtex 切片))
    副作用：lbrace→push_scope，rbrace→pop_scope，mathshift 开→math_depth+=1
```

- **注释分支消失**——Mouth 已吞；间隙字节经 §2 覆盖账进 ident/vtex。顶层 `%` 的「flush+literal」边界语义由「间隙含 `%` 时 flush 先行」近似。
- **单遍不变式**（gullet-corpus 实测锚）：66/995 文件二次驱动发散——界标 `\if*` 的条件段被 gullet 消费后交出本体，重喂会把选中支头部当条件再吃（最深 −26k token）。推论：**展开流不可重放**——分段器前瞻一律 `read()` 原始流（不覆盖 vtex、无展开副作用），`unread` 只许回吐从未展开的 raw token，`next_expanded` 产物绝不回炉。
- `param` token（孤立 `#`）→ 字面进 run；未知 cs、LITERAL 宏、INLINE_LITERAL 按名分派全部沿用，只是 name 取自 `t.text`。

## 6. 逐处理器移植要点

- **`_args` → token 版**：跳过 space token；`lbrace` 平衡组收集（tokens 同时进 `sub` 列表供 in_arg 子扫）；`[`→`]` 同；单 token 参数 = 下一非空白 token；`eol_par` 前停（par 语义）；`e` spec 的 `^`/`_` 检查 kind 而非字符。
- **`_find_env_end` → token 拉取版**：`gullet.read()`（原始流——前瞻不许触发展开副作用）拉 token 计深度：`\begin{t}`/`\end{t}` cs + ENV_BEGIN/END 宏表查名 + verbatim env 体内跳读；命中 → `[[ENV]]` 盖 `[begin.src.start, end.src.end)`；未中 → `unread(collected)` 回吐。F12 墓标移植：事件位改「拉取序号」（跨 fid 全序）。
- **verbatim env / `\verb` / `\lstinline`**：`\begin{V}` → 文件字节 `find("\end{V}")` → VERB ph + `skip_past` resync；expanded 形（`\bv` 宏）同走文件字节路；字节找不到 → unclosed。`\verb` 拉定界 token，体按 token 位连续即取 file 切片，定界符被注释吃掉时退化文件字节 find + resync。
- **数学**：mathshift token 配对 + `$$` 双 token 识别；math-debt repair 移植（ph 体奇 `$` → debt 栈，体内容用 vtex/展开表面切片判）。
- **`\if` 界标档**（S4 落地形，取代设计稿的「逐 piece 回放」）：**marker 夹心**——gullet `process_if`/`_do_ifundefined` 消费完选支外字节后，lead marker（`if:<name>`）的 `end` 取选支首 token 起点（盖 `\if`+条件段 + 前置死支 + 分案符），尾 marker（`fi:<tag>`）随选支一起 `unread([*sel, tail])`（盖后置死支+`\fi`）；死支字节全成 LITERAL piece，与 v1 等价且不需要分段器做 case 收集。分段器侧 `_handle_cond` 走 **lazy 流式界标**：不可求值 `\ifX` 到 dispatch 时条件段已被消费成 gap——`read()` 窥下一 raw token 取 `end=nxt.pos[1]`（限 `gen==0` 且同 fid），flush + cover + `_emit` 一条 LITERAL 盖 `\ifX`+条件区；`\else`/`\or`/`\fi`/`IfSetter` 散件到主流后同样 flush+LITERAL；嵌套免计深，verb 体假 `\fi` 被 `skip_past` 天然挡住；in_arg 一律 `[[COND_n]]` 占位进 run。
- **`\end{document}`/`\endinput`**：顶层截停语义不变；`\endinput` 行不进 vtex（与 flatten「保留该行」微差，接受留档）。
- **in_arg 子扫**：同一 Segmenter 跑在 arg 的 token 子列表上（TokenSource 抽象 = gullet | list[Tok]），共享 ScanState；arg 内 gen>0 token 的 origin 已指向调用点，展开组规则同顶层。
- **preamble**：不再正则预扫 + 整段 LITERAL——preamble 区 token 照常过 gullet（`\def` 登记、`\if` 求值、`\makeatletter` 翻 catcode），分段器对 preamble 区间一律 LITERAL piece，`\begin{document}` 检出即切模式。
- **宏表职责迁移**：设计稿原定 `macro_table.py` 的 MacroTable（cmds/envs 平表）整体退役换 gullet scope 链。落地形有偏离——scope 登记职责确由 gullet 接管，但 `macro_table.py` 留存为**登记侧分类 + argspec 编译 helper**（宏体分类 ENV_BEGIN/ENV_END/OPAQUE/TRANSPARENT 与 argspec 编译），由 `gullet/classify.py` 与 `segmenter/_common.py` 消费；职责收窄而非删除。

## 7. 兼容面与验收门

`ScanResult` 字段不变 + 新增 `vtex`（= protected_tex 拼接前的源文本；`parse_tex` 单文件恒等于入参）。`parse_file(path)`：`flatten_inputs` 退役进 bench 参考；`Gullet root_dir=parent`；`res.inputs` 记 `(vpos, path)`。parsebench 门：corpus_v3 1955 文件 identity=100%（对 `res.vtex`）、leak 不劣于 v1 基线、unresolved_inputs 不涨、chunk 召回不降（展开组应带来增量——transparent_expand 49% 藏文本回收，见 `expansion-design.md`）。性能门 max≤500ms/文件。

## 8. 落地记录（S1–S4）

- **S1 骨架**：segmenter 新模块——TokenSource 抽象 + vtex 账本 + run 双轨 + 直排（verbatim/math/env/chunk-arg 先全按整块保护）。
- **S2 分派移植**：dispatch 19 行全部 token 化（verb/begin/end/cite/ref/PROTECT/href/input/chunk-arg/PROTECT_BLOCK/TRANSPARENT/BOUNDARY/endinput/数学定界/inline-literal/opaque-macro/unknown-cs），`_args_tok` 全 argspec 字母（m/v/o/O/s/t/d/D/r/R/e/b + 单 token/零宽缺省），in_arg 子扫走 `_ListSource`。corpus_v2_smoke 40/40 identity。实测补丁三条：**peek 吞 ws 丢 token**（`_peek_nonspace` 拉出即消费的 space 在参数不匹配时永不回主流，v1 `ws_skip_arg` 原位语义被破坏——修法：跳过 token 记 `pulled`，放弃路径 `unread([*pulled, x])` 全量回放，命中路径并入 `all_toks`）；**子扫 rendered 残余字节**（`_env_with_mined`/`_handle_chunk_arg` 的 `join(sub.pieces)` 丢「已盖 vtex 未挂 piece」的尾部——补 `vt.slice(sub_end, v_end.start)` 残段）；**gap-surface 前缀**（Mouth 吞 `\cs` 后空格/折叠空白/`%` 注释不成 token——进 ident 不进 surface → `[[MACRO_1]]as` 粘连；`_gap_surface` 去注释纯空白→`" "` 补 run 项 surface 前缀，修的是译文面词界）。dispatch 普查：UNKNOWN 兜底 49.5% cs token，`\\`（行界）、`\[`/`\(`、控制符号族为主——CMD ph 兜底符合设计。
- **S3 展开语义**：transparent_expand 表面入 run、`ph_map[CHUNK]` fallback、eol_par 虚拟分段符、`_split_core` 整组归属。嵌套展开组（diverged 孤例根因）两处修法：组界判定补「gen>0 且 origin⊆组调用区间→同组」的包含关系 + pending 分区登记。corpus_v3 全量 1955 双跑对照 v1：identity strict 1955/0/0（diverged 清零）、vtex_vs_src strict 全覆盖、leak 57→90（dollar 61 良性 FP + conditional 27 待 S4 + begin_env 2）、dead ph 0、Σ chunks 135116→115240 且 placeholders 789773→932999（展开面进 chunk）、wall p50 7→35ms / p95 202→285ms（约 5× 可接受）。
- **S4 `\if` 界标 + F12 墓标**：marker 夹心 + lazy 流式界标（§6）落地；`\@ifundefined` 同形修复（此前 marker 整调用覆盖 + 选支零宽回放 → literal 原文与 chunk 译文双发）。F12 墓标 = seq + (fid,pos) 锚：放弃源侧 pull_ord 游标方案（槽位在展开消费/丢支/unread 下复用错位），改为失败扫描 `collected` 内的拉取序号做 begins/ends 序 + `\begin` cs 的 `(fid,pos)` 做查询锚；失效/未录路径全部回吐已拉 token 落正常扫描，for-else 无匹配直接 return——事件流完备即真未闭合，不重扫。corpus_v3 双跑对照 S3：identity 1955/0/0 不回潮、leak 90→63（conditional 27→0 收口）、dead ph 0、chunks +4（选支入流）。**遗留 leak 63 全为片外族：dollar 61（`\$` 转义 FP）、begin_env 2。**
