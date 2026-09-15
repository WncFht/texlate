# Segmenter 接线契约：scanner → token 流重写（M1 设计稿）

> 状态：设计定稿待实施（2026-09-15）。上游：`docs/07` §8 三段式 +
> `expansion-design.md`（gullet 侧规格已落地为 `mouth.py`/`gullet.py`，
> commit d22b56b，未接线）。本文档是分段器侧的缺失半边——回答「scanner
> 的 1614 行字节状态机怎么变成 `next_expanded()` 的消费者」。

## 0. 总形状

```
file bytes ──► Mouth（逐文件 tokenize，catcode 共享表）
           ──► Gullet（不动点展开 + \if 选支 + \input 压栈 + def 登记）
           ──► Segmenter（消费 token 流 → pieces/chunks/ph_map/warnings）
```

分段器**永不直接前读字节**：一切源消耗经 token 流；字节只在「切 raw 片」
时按 token 的 `(fid, start, end)` 从 `file_texts[fid]` 取。这保住三条铁律：
字节级 identity、注释不可见即边界、展开只做分类不做物化（`gen>0` token
的 pos 不做 splice，`origin`/`src` 才做）。

## 1. vtex——叙事序虚拟文本（position mapping）

**决定**：不按 `(file_id, offset)` 改造 Piece/Chunk/Span 下游，而在分段器
里增量物化一条 **vtex**（virtual text）= `flatten_inputs` 产出的同构文本。
一切 piece/chunk/span 用 vtex 坐标——`pieces` 平铺 `[0, len(vtex))` 不变式、
`validate_result`、`reconstruct`、parsebench identity 全部零改动。

- 每文件维护消费前沿 `cons[fid]`；一条源区间 `(fid, a, b)` 被「覆盖」时：
  `vtex_parts.append(file_texts[fid][a:b])`，其 vtex 区间 =
  `[vlen, vlen+b-a)`，`cons[fid] = b`。
- 覆盖驱动 = token 到达：gen=0 token `(fid,a,b)` 到达时先覆盖
  `[cons[fid], b]`——**间隙字节（注释/折叠空白）随覆盖自动进 vtex**，
  这正是 Mouth 吞注释后 identity 不破的机制。
- `\input` 成功：调用点字节**不进 vtex**（marker piece 记 `inputs[]`，
  输出物不含 `\input` 行——与 flatten 现行替换语义一致，不会双重 include）。
  子文件字节随其 token 到达序接进 vtex → 叙事序天然正确。
- 单文件情形 `vtex == tex`；多文件 `vtex == flatten_inputs(main)`（模
  `\endinput` 行保留之差，见 §6）。
- 乱序例外（`\expandafter` 让后位调用点先展开）：`src.start < cons[fid]`
  的展开组做不到单增映射——直接放弃 vtex 内联，按 `[[EXPAND_n]]` 保护
  （§3.2 病理档），记 `expand_reorder` warning。

## 2. 覆盖账本与 run 双轨

run 项从 `str` 升级为 `(surface, ident)` 双轨：

| 来源                 | surface（进 chunk.content / 译文面）     | ident（identity 面）                                                         |
| -------------------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| gen=0 文本 token     | `t.text`（space 已折叠，译文面要折叠形） | `vtex` 切片 `[cov_start, t.src.end)`——**含前导间隙**（注释随 identity 保留） |
| ph 项（MATH/CITE/…） | `[[X_n]]`                                | 同一 token（ph_map 体即原文）                                                |
| 展开组（§3）         | 展开表面文本                             | `[[EXPAND_n]]` token（体 = 调用点 vtex 切片）                                |

- 非 chunk 冲刷（短 run / MINED_ONLY）：piece.text = `join(ident)`——
  注释、展开调用点原文全部逐字回，identity 零新机制。
- chunk 冲刷：content = `join(surface)`；**identity 经
  `ph_map["[[CHUNK_k]]"] = vtex[gspan]`**——利用 `expand()` 现成的
  `trans → ph_map → content` 优先级（docs/07 §9 伪码同序），零 schema
  变更。仅当 run 含展开组才登记（`run_has_expand` 旗标），常态路径无
  额外开销。
- 溢出二次切分（`_split_core`）：part 边界落在展开组**整组**归属侧
  （取含切点项的 vend），各 part 的 `ph_map[CHUNK]` = vtex 连续切片——
  区间覆盖仍无缝。
- `lead/trail` 空白剥离：含展开组的 run 跳过剥离（整 run 进 content，
  ws 对翻译无害）；纯 gen=0 run 维持现行 §3.8 行为。

## 3. 展开组的流内形态

- **判定**：`t.gen > 0` 即展开产物。同 `origin`（=最外层调用点
  `(fid,a,b)`）的连续 token 为一组；**组内 gen=0 arg token**（代入位
  的真源 token，`pos` 落在调用点区间内）同属该组——组界 = 首个
  「gen>0 且 origin≠组」或「gen=0 且 pos 不在调用区间内」的 token。
- **调用点区间 = 整调用**（`\sw{a}{b}` 全段），**不是** `trig.pos`
  的 cs 名区间——当前 `expand_def` 打的是后者，gullet 侧需改为
  `(trig.fid, trig.start, trace末位.end)`（见 §4）。实测锚：
  `\def\sw#1#2{#2 and #1}` + `\sw{a}{b}` 现行 origin=(25,28) 仅盖
  `\sw`，目标 origin=(25,34)。
- **surface** = 组内 token 文本拼接（`eol_par`→`\n\n`、space→` `、
  cs→`\name`、param→`#`…按 Tok.text 渲染规则）。
- 组内再生保护段（展开文本里的 `$…$`、`\cite{…}`）照常走分段规则产
  ph——ph 体是展开表面切片（vtex 里无对应字节，identity 由
  chunk 级 `ph_map[CHUNK]`/run 级 `[[EXPAND]]` 兜底，永远查不到它）。
- 展开组内 `eol_par` = **虚拟分段符**：flush run、不产字节（源里本就
  没有 `\n\n`）；组的后半挂进下一 run，其覆盖字节 = 调用点已在
  上一 run 计过的位 → 记 `expand_span_reuse`（罕见病理）。

## 4. gullet 侧缺口（需 impl-expansion 补，或 leader 代笔）

> **落地状态（2026-09-15 晚）**：全部已实施——`_consumed` marker
> （`def:`/`newcmd:`/`newenv:`/`newtheorem:`/`mathop:`/`xparse:`/`let:`/
> `newif:`/`catcode:`/`if:`/`input:`/`endinput` 系）、`Mouth.resync` +
> `gullet.skip_past(fid,pos)`（tokbuf 残骸剔除、栈深找 fid、i 只前进）、
> `_stamp_call_origin` 补打整调用区间。segmenter 侧实测补丁两条：
>
> - `Span.__len__` = `end-start` → **零宽 span 是 falsy**——`x or Span(0,0)`
>   式兜底会把 `Span(v,v)` 落成 `Span(0,0)`，判空一律 `is None`。
> - **组内 consumed marker 不破组界**：gen>0 marker 的 pos 是定义体区段
>   （早已覆盖、零宽即可），`\document` 级大宏展开体内含 def/if/input
>   marker 属常态；仅 input 型组内也记 `inputs[]`。
>
> S3 全量落地后追加三条（corpus_v3 1955 文件实测）：
>
> - **零宽 surface 项归段**：`_close_group` 的 eol_par 分段可产出
>   `surface==""` 但 vspan 盖真实 callsite 的 run 项（如
>   `\def\abs{\par…}` 展开面以 `\par` 开头）。`_slice_items` 对零宽项
>   按 `acc >= lo and (acc < hi or acc == hi == end)` 归段；且其 ident
>   一旦进 chunk identity，callsite 字节必须折入段 gspan——gspan 取
>   分段项界并集（`slices[0].vstart … slices[-1].vend`），否则尾部
>   `_emit` 把同段字节 raw 再发 → 双发 diverged。
> - **零宽 callsite 不签 EXPAND**：嵌套展开里内层组的 callsite 已被外层
>   盖过（vspan 零宽），签发 `[[EXPAND_n]]` 只会被零宽 run literal 冲刷
>   时 `_emit_text` 的 `vend > vstart` 守卫连 piece 带 token 丢掉 →
>   dead_ph。`_close_group` 对 `vspan.end == vspan.start` 直接置
>   `ident=""`。
> - **filecontents 行首锚定**：kernel 语义是逐行读体、`\end{filecontents}`
>   行首独占才闭合——体内 PostScript/注释里的行中 `\end{…}` 全是字面
>   负载。verbatim 路的闭合查找对 filecontents 族改用
>   `(?m)^[ \t]*\end{…}` 锚定；`filecontents+`/`filecontentsheader`
>   变体补登 `_VERBATIM_BASE`。

| 缺口                      | 现状                                                                                                                                                             | 需要                                                                                                                                                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`origin` 只盖 cs 名**   | `expand_def` 打 `trig.origin or trig.pos`——`\sw{a}{b}` 的 origin=(25,28) 不含 args                                                                               | origin = 整调用区间 `(trig.fid, trig.start, self._trace[-1].pos.end)`（`_invoke` 返回后在 `next_expanded` 补打）。否则 EXPAND/ph_map[CHUNK] 的 identity 切片只含 `\sw`，args 字节漏出                                        |
| 静默消费事件              | `_do_def`/`_do_newcmd`/`_do_newenv`/`_do_newtheorem`/`_do_mathop`/`_do_xparse`/`_do_let`/`_do_newif`/`_do_catcode`/`process_if`/`_do_input` 成功均 `return None` | 发 marker：`Tok(kind="consumed", pos=(fid,cs,ce), text="def:name"/"input:path"/…)`。分段器：flush + LITERAL piece 盖 `pos` + `inputs[]` 登记（input 型）。保住 dispatch 2/3/10 的边界语义——def 串不落 chunk 否则译文会删 def |
| verbatim/`\verb` raw 消费 | Mouth 会把 verb 体内的 `%` 当注释吞 → 定界符永不到 → 流脱同步                                                                                                    | `gullet.skip_past(fid, pos)`：置 `inputs[-1].i`、复位 `state=S_M`、清 `tokbuf`。分段器对 `\begin{verbatim}`/`\verb` 在**文件字节**上找闭合（现行 `tex.find` 移植），命中即 resync                                            |
| `math_depth` 回报         | gullet 字段已存在                                                                                                                                                | 分段器在 `$`/`$$`/`\(`/`\[`/math-env 进出时写                                                                                                                                                                                |
| scope 回报                | `push_scope/pop_scope` 已有，注释写明由分段器驱动                                                                                                                | 分段器在 `lbrace`/`\bgroup`/`\begingroup`/`\begin{env}`/`$…$` 开、`rbrace`/`\egroup`/`\endgroup`/`\end{env}`/数学闭 推/弹。**组内对称推弹即安全**；arg 括号不产事件（gullet 内部消费，TeX 语义同）                           |
| warnings 合流             | `gullet.warnings`                                                                                                                                                | `ScanResult.warnings` 尾部并入（pos 已是 `(fid,off)`——warning.pos 需 fid 化或存 vtex 位）                                                                                                                                    |

## 5. 分段器主循环改写（dispatch 19 行 → token 版）

```
while t := gullet.next_expanded():
    t.kind == "cs"      → dispatch_cmd(t)            # 19 行分派逐行移植
    t.kind == "mathshift" → _on_math(t)              # _on_dollar 的 token 版
    t.kind == "eol_par" → flush_run                  # gen>0 见 §3 虚拟分段符
    t.kind == "space"   → run.append((" ", vtex 切片))
    t.kind == "consumed"→ flush + LITERAL + 副作用登记
    其余（letter/other/active/lbrace…）→ run.append((t.text, vtex 切片))
    副作用：lbrace→push_scope，rbrace→pop_scope，mathshift 开→math_depth+=1
```

- **注释分支消失**——Mouth 已吞；间隙字节经 §2 覆盖账进 ident/vtex。
  顶层 `%` 的「flush+literal」边界语义由「间隙含 `%` 时 flush 先行」近似：
  覆盖切片若含 `%`（逐 gap 扫一次即可，等价今日注释边界）。
- **单遍不变式（c2 gullet-corpus 实测锚）**：66/995 文件二次驱动发散——
  界标 `\if*` 的条件段被 gullet 消费后交出本体，重喂会把选中支头部
  当条件再吃（最深 −26k token）。推论：**展开流不可重放**——分段器
  前瞻一律 `read()` 原始流（不覆盖 vtex、无展开副作用），`unread`
  只许回吐从未展开的 raw token；`next_expanded` 产物绝不回炉。
- `param` token（孤立 `#`）→ 字面进 run。
- 未知 cs、LITERAL 宏、INLINE_LITERAL 等按名分派全部沿用——只是
  name 取自 `t.text` 而非 `read_cmd_name`。

## 6. 逐处理器移植要点

- **`_args` → token 版**：跳过 space token；`lbrace` → 平衡组收集
  （lbrace/rbrace 计数，tokens 同时进 `sub` 列表供 in_arg 子扫）；
  `[`→`]` 同；单 token 参数 = 下一非空白 token。ArgSpan content/full
  = 组内 token pos 区间 / 含括号区间（file→vtex 映射）。`eol_par` 前停
  （同 `ws_skip_arg` par 语义）。注释透明 = Mouth 已吞天然等价。
  `e` spec：`^`/`_` token 检查 kind 而非字符。
- **`_find_env_end` → token 拉取版**：`gullet.read()`（**原始流**——
  前瞻不许触发展开副作用）拉 token 计深度：`\begin{t}`/`\end{t}` cs +
  ENV_BEGIN/END 宏表查名 + verbatim env 体内 token 跳读。命中 →
  body token 已消费，`[[ENV]]` 盖 `[begin.src.start, end.src.end)`；
  未中 → `unread(collected)` 回吐、从 j 续扫（同现行语义）。F12 墓标
  移植：事件位改「拉取序号」（跨 fid 全序），`end_ret` 存 `(fid,pos)`。
- **verbatim env**：`\begin{V}` → 文件字节 `find("\end{V}")` → VERB ph
    - `skip_past` resync（§4）。expanded 形（`\bv` 宏）同走文件字节路
      （体在调用点后的真源里）；字节找不到 → unclosed（与现行等价）。
- **`\verb`/`\lstinline`**：拉定界 token → 体按 token 位连续即取
  file 切片；定界符被注释吃掉时退化到文件字节 find + resync。
- **数学**：mathshift token 配对 + `$$` 双 token 识别（相邻两个
  mathshift 或 Mouth 产 `$$` 单 token——以 mouth 实际产出为准，测试
  先行）。math-debt repair 移植：ph 体奇 `$` → debt 栈照旧（体内容用
  vtex/展开表面切片判）。
- **`\if` 界标档**：gullet `_do_if` 不可求值 → `\ifX` token 交出 →
  分段器 token 版 `_process_if`：`read()` 收集 case（`if*` 计嵌套、
  `newif` 整对保留、`else/or` 分案例、`\fi` 止）→ 界标 literal piece
  盖条件区 + **两支 token 序列各自 unread 回放**（中间夹 `\else` 界标
  piece——界标 piece 需要字节区间，用 `else`/`fi` token 的 src span）。
  可求值支已被 gullet 消费——其字节成 gap 自动 literal，选支流正常。
- **`\end{document}`/`\endinput`**：顶层截停语义不变；`\endinput` 行
  不进 vtex（与 flatten 的「保留该行」微差，接受并留档）。
- **in_arg 子扫**：`_handle_chunk_arg`/in_arg 变体 = 同一 Segmenter
  跑在 arg 的 **token 子列表**上（TokenSource 抽象 = gullet |
  list[Tok]），共享 ScanState。arg 内 gen>0 token 的 origin 已指向
  调用点——子扫内展开组处理规则同顶层。
- **preamble**：不再 `register_macros_in` 正则预扫 + 整段 LITERAL——
  preamble 区 token 照常过 gullet（`\def` 登记、`\if` 求值、
  `\makeatletter` 翻 catcode），分段器对 preamble 区间一律 LITERAL
  piece（`\begin{document}` 检出即切模式）。`macro_table.py` 的
  `MacroTable`（cmds/envs 平表）整体退役，统一换 gullet 的 scope 链
  `MacroTable`——`state.macros` 类型随之切换，下游 `res.macros`
  消费点（`_env_sig`、`dispatch` env 查表）适配。

## 7. 兼容面与验收门

- `ScanResult` 字段不变 + 新增 `vtex`（= `protected_tex` 拼接前的源文
  本；`parse_tex` 单文件时恒等于入参）。
- `parse_file(path)`：`flatten_inputs` 退役进 bench 参考；`Gullet`
  `root_dir=parent`；`res.inputs` 记 `(vpos, path)`。
- parsebench 门：corpus_v3 1955 文件 **identity=100%**（对 `res.vtex`）、
  leak 不劣于现基线（57 dollar 例）、unresolved_inputs ≤ 111、chunk 召回
  不降（展开组应带来**增量**——`transparent_expand` 49% 藏文本回收）。
- 性能门：§11 max≤500ms/文件 保持；Mouth tokenize + 展开每文件新增
  耗时需实测（c2 的 gullet-corpus bench 先给数据）。
- 回退开关：`TEXLATE_NO_EXPAND=1` 走旧字节 scanner（并存期基准对照）。

## 8. 实施切片（建议顺序）

1. **S1 骨架**（已落 `866ca27`）：`segmenter.py` 新模块——TokenSource
   抽象 + vtex 账本 + run 双轨 + 直排（verbatim/math/env/chunk-arg
   先全按「整块保护」），corpus 抽样冒烟。
2. **S2 分派移植**（已落，见 §9）：dispatch 19 行逐行过 + `_args_tok`
   token 版 + in_arg 子扫；对照旧 scanner 双跑 diff（同 corpus 输出对齐）。
3. **S3 展开语义**：transparent_expand 表面入 run + `ph_map[CHUNK]`
   fallback + EXPAND ph + eol_par 虚拟分段。
4. **S4 `\if`/`\input` 接线**：界标档 + marker 事件 + resync + F12 墓标。
5. **S5 门**：parsebench corpus_v3 双跑 + e2e-real s40 + 性能曲线。

每片独立可验；S2 起即可双跑 diff 当回归。

## 9. S2 落地记录（2026-09-15）

dispatch 19 行全部 token 化（verb/begin/end/cite/ref/PROTECT/href/input/
chunk-arg/PROTECT_BLOCK/TRANSPARENT/BOUNDARY/endinput/数学定界/inline-literal/
opaque-macro/unknown-cs），`_args_tok` 全 argspec 字母（m/v/o/O/s/t/d/D/
r/R/e/b + 单 token/零宽缺省），`_env_with_mined`/`_handle_chunk_arg`
in_arg 子扫走 `_ListSource`。corpus_v2_smoke 40/40 identity。

实测补丁两条（字节版→token 版移植的真实坑）：

- **peek 吞 ws 丢 token（F-尾丢）**：`_peek_nonspace` 拉出即消费的
  space token 在参数不匹配时永不回主流——v1 `ws_skip_arg` 的 `pos`
  停在原位、空白由主流重扫的语义被破坏，子扫尾巴上丢字节 →
  ENV/chunk-arg ph 体缺 `\n` → identity 破（corpus 40→11）。
  修法：`_peek_nonspace(src, pulled)` 把跳过 token 记进 `pulled`，
  一切放弃路径 `src.unread([*pulled, x])` 全量回放；命中路径
  `pulled` 并入 `all_toks`（`_unread_args` 全恢复）。
- **子扫 rendered 残余字节**：`_env_with_mined`/`_handle_chunk_arg`
  的 `rendered = join(sub.pieces)` 丢掉「已盖 vtex 未挂 piece」的
  尾部字节（上条的下游）——补 `vt.slice(sub_end, v_end.start)` 残段。
- **gap-surface 前缀**：Mouth 吞三类字节不成 token（`\cs` 后空格、
  折叠空白、`%` 注释）——进 ident 不进 surface → `[[MACRO_1]]as`
  粘连。`_gap_surface(fid, cons0, tok_start)` 去注释纯空白 → `" "`，
  run 项 surface 补前缀（`_rappend_tok`/`_rappend_ph(tok=)`/eol_par/
  展开组调用点）。identity 本就兜住，此修的是译文面词界。
- **杂项**：`_env_name` ws_skip + 嵌套花括号深度配对（`\begin {env}`）；
  `_env_name` 失败 unread 回吐重分派（grp 里可能藏真 `\end{target}`）；
  `_ListSource.skip_past` 丢 raw 消费段残骸 token（子扫内 verb 体
  `\_end` 假命中防御）；`\section*` 预吃星号（v1 同序）；`\import`
  第二参/`\lstinline` 用 `_read_skipws`（ws_skip 全空白语义，跨 `\n\n`）；
  `_protect_cs` 的 `*`/定界判定用裸读不 ws_skip（v1 `tex[pos]` 同位）。

遗留：`\if` 两档界标回放、F12 墓标（拉取序号版）在 S4；
v1↔v2 双跑 diff（`bench/results/v2-diff-2026-09-15.md`，S2 中途态快照：
v2 identity 75/200 strict——尾丢修复后应显著回绿，archbox 复跑）；
dispatch 普查（`bench/results/v2-census-2026-09-15.md`）：UNKNOWN 兜底
49.5% cs token——`\\`(16.7k=行界应走 boundary)、`\[`/`\(`（已接 row16）、
控制符号族（row17 已收）为主，余为 bibinfo/bbl 内部与真未知宏——
CMD ph 兜底符合设计。

## 10. S3 落地记录（2026-09-16）

展开语义全接：transparent_expand 表面入 run（`_RunItem.surface` 渲染、
ident = `[[EXPAND_n]]` 体=调用点 vtex 切片）、`ph_map[CHUNK]` fallback
（chunk identity 走 `expand()` 的 trans→ph_map→content 优先级，零 schema
变更）、eol_par 虚拟分段符（展开组内 flush、不产字节）、`_split_core`
溢出切分整组归属。嵌套展开组（diverged 孤例根因）两处修法：组界判定
补「gen>0 且 origin⊆组调用区间 → 同组」的包含关系（内层 origin 被外层
callsite 包住时不再早闭外组）+ pending 分区登记。零宽三补丁与
filecontents 行首锚定见 §4 落地状态追加段。

验收（`bench/results/parsebench-v2full-s3c-2026-09-15/`，corpus_v3 全量
1955 双跑，对照列 = v1 scanner 同跑）：

| 指标                                | v1              | v2 (S3)         | 判定              |
| ----------------------------------- | --------------- | --------------- | ----------------- |
| parse ok                            | 1955/1955       | 1955/1955       | —                 |
| identity strict/normalized/diverged | 1955/0/0        | 1955/0/0        | diverged 孤例清零 |
| vtex_vs_src 展开足迹                | —               | strict 1955/0/0 | 全覆盖            |
| leaked chunks                       | 57              | 90              | 见下              |
| dead ph（chunk+protect）/ orphan    | 0               | 0               | 18345→65→0 收口   |
| Σ chunks / placeholders             | 135116 / 789773 | 115240 / 932999 | 展开面进 chunk    |
| wall ms p50 / p95                   | 7 / 202         | 35 / 285        | 约 5×，可接受     |

leak 90 构成：dollar 61（`\$` 转义美元被 `_on_math` 当定界——良性 FP 大头，
v1 同族 57 个）、conditional 27（`\iffull`/`\ifx` 族真漏——`\if` 求值未接，
属 S4 域）、begin_env 2。无新 hit 族。

遗留 → S4：`\if` 两档界标回放 + ifflags 真值表接线 + consumed `if:` marker
已在 gullet 侧备好；F12 墓标（拉取序号版）。filecontents 族（含 `+`/
`header` 变体）opaque 块 + end 行首锚定已落（W26 闭环）。
