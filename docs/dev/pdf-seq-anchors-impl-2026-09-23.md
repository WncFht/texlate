# PDF seq 锚定实施计划（marked-content 注锚 + 模糊锚升级）

> **目标**：PDF 窗格拿到「PDF 位置 ↔ dual.json chunk seq」确定性映射，点亮
> copy-latex / sent-align / find-usages 的 pdf 臂。
> **路线**：B（编译期 `\special{pdf:code}` marked-content 注锚）为主锚——
> 新编译任务确定性 seq 级；C（textLayer 模糊匹配）升级为存量兜底——
> 7 个存量任务 2947 chunks 零重编受益。A（SyncTeX）不做。
> **依据**：`docs/research/product/2026-09-23-pdf-anchoring.md` §7 三实验实证
>
> - 6-lane 侦察工作流 `wf_a2e01a17-361`（reconstruct/fixloop/pdfpane/matcher/
>   tex-safety/test-surface 全量内勘）。

## 1. 标记形态（已端到端实证）

```latex
\special{pdf:code /TLXC <</MCID 50080>> BDC}<chunk 展开体>\special{pdf:code EMC}
```

- tag 恒定 `TLXC`；seq 编码进 MCID：`mcid = 50000 + seq`（50000 基座避开
  文档自带 tagpdf/NonStruct MCID，实测文档自有 MCID ≤ ~640）。
- xelatex/tectonic（xdvipdfmx 血统）原样落内容流；段边界注入零排版漂移，
  段内 ≤2.3bp 水平微移（whatsit 占位已知效应）。
- pdf.js `getTextContent({includeMarkedContent:true})` 吐
  `beginMarkedContentProps{tag:"TLXC", id:"p<obj>_mc<50000+seq>"}` +
  `endMarkedContent`；TextLayer 自动包 `span.markedContent` 且 **id 写进
  DOM**（`pdf.mjs:15193`）→ `span.markedContent[id$="_mc50080"]` 直接可查。
- 跨页安全：页尾未闭合 mark pdf.js 自动闭合（合成 endMarkedContent item），
  页首孤儿 EMC 解析层丢弃——**DOM 永不损坏，最差=部分锚**（实测故意失衡
  编译验证）。
- 内联形态（不插 `\n`、不带尾 `%`）：全语境单形态——块边界 BMC 落 vmode
  零漂移，段内 EMC 最差 ≤2.3bp。

## 2. 后端：reconstruct 注锚

### 2.1 签名与注入点

```python
reconstruct(res, translations=None, *, mark_seq0: int | None = None,
            mark_moving: bool = False) -> str
```

- `mark_seq0` = 本文件 seq 基址（`seq = mark_seq0 + c.id`；`c.id` 即
  `res.chunks` 下标）。`None` → 不注锚。identity（translations=None）永不注锚。
- `mark_moving` = 调用方证明「本文档无 `\tableofcontents`/`\listof*`/hyperref」
  → moving-arg chunk 也可内联注锚；缺省 False（保守）。
- 注入点：`_Expander.expand_body` 的 token 循环——`[[CHUNK_n]]` 命中
  `mark_map` 且过安全谓词时，展开体两侧包 BDC/EMC special。包在**引用点**
  （非 `expand()` 内/memo 外）→ 同 token 多引用各自按本站判定，memo 存裸
  展开体零污染。
- `chunk_spans`（repair_l2:307）零改动——它自建无 mark 的 `_Expander`，
  `find(body)` 仍命中标记内侧的连续译文体，L2 归因不破。

### 2.2 安全谓词（tex-safety lane 硬约束）

chunk 发射点由三类 piece 产生：顶层 run 冲刷（para/item/abstract）、
chunk-arg 花括号内（context=命令名）、mined env 体。逐语境判定：

| 条件                                                                                                                                                                                  | 判定                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| site 花括号栈含 soul 族 cs（`ul                                                                                                                                                       | hl                                                | sout | uline | uwave | st  | caps`） | SKIP——soul 逐 token 重扫遇 whatsit = 编译错 |
| `chunk.env` ∈ ALIGN_ENVS（tabular/longtable/Nice*/tabbing/deluxetable/tblr/supertabular/xtabular/ltablex/array/matrix 族）                                                            | SKIP——行间 whatsit → Misplaced \noalign           |
| 后继非空 token 以 `\\`/`\hline`/`\noalign`/`\midrule`/`\cline` 起头                                                                                                                   | SKIP（行间冗余闸；piece 尾尽时回看下一 piece 头） |
| site 栈含 moving-arg cs 或 `chunk.context` ∈ MOVING（section/subsection/subsubsection/paragraph/subparagraph/chapter/part/caption/captionof/subcaption/tablecaption/addcontentsline） | `mark_moving` False → SKIP；True → INLINE         |
| `chunk.context` ∈ {intertext, shortintertext, pdfbookmark}                                                                                                                            | SKIP                                              |
| 其余（para/item/abstract + 非 moving chunk-arg：footnote/thanks/title/author/date/keywords/abst 等）                                                                                  | INLINE                                            |

- site 花括号栈：`mask_tex(protected_tex)` 上**前向单遍**维护 cs-brace 栈，
  在每个 piece 边界快照 → piece 起点 enclosing cs 集合 O(1) 查；字面段内嵌
  token 用有限回溯（≤16KB）补站。**structural unreachable**（math/verbatim
  全 opaque ph）不做谓词但 assert 记档。
- moving-arg 泄漏链：`\section`/`\caption` 参数经 `\protected@write` 字面写
  .toc/.lof → 目录页重放同 MCID = 锚歧义；hyperref `\pdfstringdef` 剥除
  `\special` 并告警。`mark_moving` 由调用方一次扫全文件判定。

### 2.3 seq 透传（三调用点）

| 调用点                                 | seq0 计算                                                                                                                                               |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `worker/compile.py::_build_zh` (:332)  | `ctx.scans.items()` 序累计 `len(res.chunks)`（**无条件累计**——`if not by_int: continue` 跳文件时 seq 仍须占位，与 parse.py:162 `seq=len(rows)` 同口径） |
| `pipecore.translate_tree_run` (:407)   | `enumerate(scans)` 序累计同上                                                                                                                           |
| `repair_l2._resplice_and_diffs` (:593) | `sum(len(run.scans[j][1].chunks) for j < fidx)`                                                                                                         |

`moving` 判定由调用方对全部 vtex 扫一次
`\tableofcontents|\listoffigures|\listoftables|hyperref` 得 `moving_ok`。

### 2.4 开关

`options.seq_marks`（bool，默认 on）+ `TEXLATE_NO_SEQ_MARKS` env——
`_opt_switch`（pipecore.py:649）单源决议；worker `_build_zh` 喂
`ctx.options()`，pipecore/repair_l2 走 env 缺省开。`_SNAPSHOT_OPTS_DROP`
**不加**（偏好随克隆保留）。

### 2.5 fixloop 生命周期

- **L2 resplice 自愈**：`_resplice_and_diffs` 重跑 reconstruct → 同一
  `mark_seq0` 参数下传即自动补标（`_retr_resplice` 同径）。
- **失衡 lint**（`_sync_fixed_sources` compile.py:139 唯一漏斗）：每个镜像
  文件查 `/TLXC` BDC 数 == `pdf:code EMC` 数 且 MCID 无重；失衡→剥该文件
  全部 `\\special{pdf:code ...}` token（inline 可不在行首，剥 token 非剥行）
    - log，降级模糊锚。**不阻断编译**——pdf.js 对失衡本就容忍。
- `_build_zh` 注入后 assert 平衡（catch 注入器自身 bug）。
- 高危动作面登记：latex209_upgrade 全文重写、subfile_docclass_strip 截尾、
  fileset_relocate 复制（同 MCID 双份=seq 冲突→lint 抓）、escalate_llm
  任意 replace。
- `zh-src.zip` 保留标记（接受——重编者可复用锚）；`/latex` 端点读 base/
  不受影响。

## 3. 前端：标记消费

### 3.1 新件 `web/src/reader/pdfmarks.ts`

```ts
const MCID_BASE = 50000;
seqOfMarkedSpan(el): number | null      // id 尾 _mc<N> 且 N>=50000 → N-50000
```

### 3.2 sel→seq（hitctx 无侵入接入）

- `makeChunkResolver` 泛化锚集：`{selector, keyOf}` 参数化——`.textLayer`
  body 用 `span.markedContent[id]` + `keyOf = seqOfMarkedSpan→String`；
  其余 body 维持 `[data-chunk]`。hitctx 按 body 类名二选resolver。
- `hit.sel.chunks` 自此在 pdf 侧带数值 seq 串 → copylatex feature pdf 臂
  （features/copylatex.ts:273）：`hit.sel.chunks` 解析出 int 集非空 → **精确
  seqs 直接用**；空 → `pdfSeqsForText` 模糊兜底。
- `endpointInChunk` 补 `.markedContent` closest 判据（`inChunk` 谓词 pdf 侧
  随锚自然成立——`sel.chunks` 非空且端点在锚内）。

### 3.3 seq→rect/page（PdfPane handle）

- 懒建 seqmap：idle 逐页 `getTextContent({includeMarkedContent:true})`
  （`scanDests` 同款切片）→ `seq → {page, itemBegin, itemEnd}`。
- `PaneHandle` 增：
    - `seqEls?(seq): HTMLElement[]`——`container.querySelectorAll(
'span.markedContent')` 滤 id 尾（跨页续段多枚；未渲染页缺席——调用方先
      `gotoPage`）。rect 消费 = `el.getClientRects()`（span 天然包裹 chunk
      全部 textDivs）。
    - `seqPage?(seq): number | null`——seqmap 查页。
- sent-align gotoPeer 的 pdf 臂以此桥接（本计划交付桥，goto 接线单记）。

### 3.4 find-usages pdf 臂（修 ReaderView:213 死臂）

- `PdfPane` 实现 `openUsagesFor(target, anchor)`：
    - `scanDests` 扩记 link annot → `(dest, page, rect)` 站集（现只存名）。
    - usages of key = 全部 dest 指向 `cite.<key>`/`cite.bib<key>` 族锚名的
      link annot → UsagesCard 条目（page+rect 跳转）。
- dests 集合已扫（PdfPane.tsx:286-314），只补 annot 侧反查表。

## 4. C 路升级（copylatex.ts，存量任务唯一通路）

实证基线（expC-report，2947 chunks）：逐字定位 33.6%、+token 锚 64.9%、
命中即 ~99.8% 准、闭区间膨胀最坏 span=75。

1. **texStrip 进 chunk 预处理**（expPdfAnchor.test.ts:42 已验证形）：
   `[[X_n]]`/`$..$|\(...\)|\[..\]`/`\cmd*[opt]`/`{}`/`~`/`\%&#_`/余 `\` 全抹；
   per-(dual,side) memoize。
2. **NFKD 入 normSel**：`s.normalize("NFKD").toLowerCase()...`——连字
   U+FB00 系/全角折叠（chunk 侧 strip 后同规归一）。
3. **gap 容忍对齐**：anchorScore 产多命中块，同 chunk 内块间 doc-gap ≤30
   token 合并计覆盖（数学/引用占位切碎段——主攻剩余 35% 失配面）。
4. **连通聚簇代闭区间**：matched 升 `{seq,best,edgeHead,edgeTail}`，seq 序
   gap≤2 连分量聚簇，胜者 = Σbest+edge 证据最大簇，返簇内 seqs（标题页
   重复文本散落命中不再膨胀）。
5. 保留 `side==="zh"? c.zh : c.en) ?? c.en ?? c.zh` nullish 回退语义。

## 5. 测试验证矩阵

| 层                 | 件                               | 用例                                                                                                                                                                                |
| ------------------ | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pytest             | `tests/test_seqmarks.py`         | 块界注入字节钉 / identity 零标记 / chunk-arg in-brace / moving+lists→skip / soul 栈→skip / align env→skip / `\hline` 后继→skip / seq 跨文件偏移对表 / lint 失衡剥净 / resplice 自愈 |
| pytest integration | 同上 +`@pytest.mark.integration` | tmp_path 真 xelatex（skipif）→ pypdf 解内容流断 `/TLXC <</MCID \d+>> BDC` 在场 + log 无 Reconstruction failed/Misplaced                                                             |
| vitest             | `src/test/pdfmarks.test.ts`      | `_mc` 尾解码、resolver 对 span.markedContent、选区跨 span 序                                                                                                                        |
| vitest             | `copylatex.test.ts` 增例         | texStrip 残留段命中、gap 断口合并、散落命中不膨胀、NFKD 连字                                                                                                                        |
| vitest node        | `expPdfAnchor.test.ts` 重跑      | 升级后命中数回归报告（C 路实测量）                                                                                                                                                  |
| playwright         | `scripts/pdfanchor_verify.mjs`   | mock-api miniPdf 注 BMC→`span.markedContent` 计数→选区→copyTex seq 断言（TASK= 可换真任务厚臂）                                                                                     |
| 全量               | 四件套                           | `tsc --noEmit` + `vitest run` + `pytest tests/` + `pytest tests/kernel/` + `ruff check`                                                                                             |

## 6. 风险登记（侦察裁决后）

- soul 族深嵌套（>16KB lookback 外）漏检 → 编译错；靠 fixloop/失衡 lint
  兜底，登记残余风险。
- `fileset_relocate` 复制同 MCID 双份 → lint 抓重剥离。
- pdf.js 私有面（`_pages`/`_textHighlighter`）依赖收敛进 pdfmarks.ts 单
  adapter——升级 pdfjs 时单点排查。
- 文档自有 MCID 与 50000+seq 碰撞：item 层 tag=TLXC 恒定可滤，id 路径
  歧义仅影响 DOM 直查——seqmap（item 层）为主、id 路径为辅。
- moving-arg 判定的 hyperref 探测是启发扫——漏判时最差不注锚（降级）
  或目录页重复锚（lint 不可见，真实低危）。

## 7. 落地验证结果（2026-09-23）

| 层                                         | 结果                                                                                                                                                                                                                                                                |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_seqmarks.py`                   | **48/48 PASS**——字节钉/identity 零标记/五闸逐条（8 env、4 moving ctx、5 skip ctx、7 soul cs、ROW_TAIL/HEAD 各形态、site 兜底、非顶层空沿）/跨文件 seq0/env 旗标/moving-unsafe demote/失衡自愈 + 真 xelatex integration（pypdf 解流 50000/50001 在场、log 无错位错） |
| `web/src/test/pdfmarks.test.ts`            | 全绿——`_mc` 尾解码、TLXC tag 校验、跨 span/同 seq 双 span/自有锚（mc<50000）混排 resolver                                                                                                                                                                           |
| `web/scripts/pdfanchor_verify.mjs` mock 臂 | **7/7 PASS**——手工 marked pdf → `p3R_mc5000{0,1}` 两枚 span、锚内选区 seqs=[0]、跨锚 seqs=[0,1]                                                                                                                                                                     |
| 同上真任务臂（`t_d7c669e8b3c92149`）       | **6/6 PASS**——52 页真 zh.pdf 外科注锚 8 MCID（p3R/p19R 两组可见）→ 选区 seqs=[0]/[0,1] 精确命中、零 console 错；同任务老产物的 C 路模糊兜底亦验过（seqs 非空）                                                                                                      |
| 四件套                                     | `tsc --noEmit` 绿；`vitest run` 绿（usages.test.ts 真论文索引改 beforeAll 共享后 26/26）；`pytest tests/` 绿（仅 `test_shipped_specs_compile` 红=在飞 layoutqc spec 外账，`test_s07` 并发例 5/5 单跑过=负载抖动）；`ruff check` 本会话件全净                        |

外科注锚实证路径（活服旧码不重启的验证法）记 `tmp/zzmark_real_task.py`
——task zh/ 拷贝→`\n\n` 段块 CJK≥20 前 8 枚包 BDC/EMC→xelatex→pypdf
自检→unlink+换 zh.pdf（硬链接件不可原地写）。

**提交后回归修复**（同日复盘）：823107dc 落地后 e2e 两例红
（`test_l2_retranslate_then_recompile`/`test_l2_fallback_verified_fixloop_off`）
——行首 `\special{BDC}` 前缀把 chunk span 起点推出行首偏移 `off`，
`L2Attr.attribute` 的 `s<=off<e` 含行判失败 → forward-fallback 把行错贴给
**前一块**（实证 hits '0:1' 而非 '0:2'，重译误入长块触发 L0 长度比 revert）。

**消费粒度后续**（2026-09-26）：§3 交付的 seq 锚消费面已由「整 seq 锚染/闪」升级为**句叶级**——悬停 hot/peer、点击跳与镜像/usages 落定闪均按 marked 叶文本重切句、取句域叶集（源侧 `pdfSentUnder` 指叶定句、对侧 u 分位 `pdfSentAt` 选句）；⌘-Inspect 检视层复用同一份 marked 面做分面命中与落点行带揭示。机制明细见 `ux-impl-2026-09-22/` 下 sent-align 档 v1.7/v1.8 节与 `⌘-inspect 修饰键检视层 实现文档.md`。
修复 = `attribute` 增「行首到 span 起点仅 seq 锚/空白即视同含行首」判据
（repair_l2.py:413）；回归钉 `test_attribute_through_bdc_line_head`（49/49）。
教训：锚是**行内字节**——凡按行首偏移做含行判的消费面都要过这一闸。
