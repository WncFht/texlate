# seqpos 解码层契约（`src/texlate/server/seqpos/` 包）

> **定位**：`dev/projects/2026-09-23-pdf-seq-anchors-impl.md` 记的是生产侧（编译期 BDC/EMC 注锚）；
> 本文记消费侧——把 marked PDF + dual.json 解码成「seq ↔ 双侧 PDF 位置」映射的
> 整条算法链。reader 点击定位/滚动同步/copy-latex pdf 臂全部吃这份产出。

## 1. 产出与缓存

```python
seqpos_for_task(task_dir: Path, dual: dict) -> dict | None
# {"seq_str": {"o"?: Pos, "t"?: Pos}}   Pos = {page, fraction, x?, x1?}
```

- `o` = en.pdf 侧位置，`t` = zh.pdf 侧位置；单侧命中也入库（双要条件在
  无标记任务上丢 36~43% seq，实证）。
- `fraction` = 行顶页高分位；`x` = 行左缘页宽分位；`x1` = 行右缘
  （`_row_extent` 补，栏判定消费原料）。
- 缓存 `task_dir/seqpos.json` = `{v: _VERSION, seqpos: {...}}`，输入三件
  （dual.json/en.pdf/zh.pdf）mtime 或 `_VERSION` 任一漂移即重算。
  **语义每动必 bump `_VERSION`**——否则旧缓存按 mtime 命中、新逻辑不生效。
  预热：`tools/seqpos_warm.py`（幂等，命中秒回）。
- 不可算（缺 PDF/无 chunks/compute 抛错）→ None，调用方降级不炸 reader。

## 2. 装配阶梯（`compute_seqpos`）

```
_char_stream×2(en,zh) → 剥 0 字形空壳标 → _doc_order 排针序
→ zh 乱码降级判定(zh_dead) → _mark_trusted×2 → dead_seqs 候选集
→ zh 无标针配(_match_side) → en 无标针配（zh 锚按流长比映 en 先验带）
→ dead_seqs 碰撞滤 → 双侧合成 + _row_extent 补 x1
```

- **0 字形空壳标先剥**：`\iftoggle` 吞参/弃置盒会留下 BDC/EMC 执行了但
  裹零字形的标——无位置证据，留着会被孤儿 snap 拿针撞上近重复孪生段
  （t_f748 seq161 `\icra{}` 空壳 snap 到 `\arxiv` 段实证）。
- **zh_dead**：textLayer 无 ToUnicode 时 CJK 全错码点，文本匹配是死路——
  密度阈判定（`zh_cjk < max(100, len//20)` 且针面 CJK 占比 >1/4）。
  判死后 zh 侧靠 `_interp_t`（pairs 对齐插值）猜；zh==en 未译任务
  针面 CJK≈0 不误判（t_e300 实证）。

## 3. 双解码器 `_char_stream`

一条流三个产物：`(stream, bounds, marks)`。

- **stream**：全文阅读序字符串。`_reading_order` 把行界按栏分组排序
  （双栏左栏先行），bounds = `[(stream_offset, page, frac, x, x1)]` 行界表。
- **文本层**：pymupdf `page.get_text("dict")` 逐 span 收字形、`_est_w` 估宽
  定行幅面 x0/x1。
- **标记层**：pypdf `visitor_operand_before` 解内容流 `BDC/EMC`，
  `/TLXC <</MCID 50000+seq>>` → `marks[seq] += [{page, fraction, x, text, chars}]`。
  occurrence 按文档序收集（TOC/hyperref 重放的在前，正文真标在后）。

## 4. 标记可信链 `_mark_trusted`（双侧同件）

occurrence 级校验 → seq 级兜底，三级阶梯：

1. **cov 闸**：标内文本对 needle 的 SM 覆盖 ≥ `_MARK_COV`(0.35) 为 good；
   good 里取**末个** anchored（TOC 重放落前、真标在后）。
2. **孤儿 snap**：不可信或裹字 < `_ORPHAN_CHARS`(4) 的 suspect，针长
   ≥ `_ORPHAN_MIN_ND`(8) 时在标称页 ±`_ORPHAN_PAGES`(5) `_match_bounded`
   寻真位，命中行界换新锚。
3. **实标兜底**（snap 失败后）：裹足量字形的末锚定 occurrence 按位兜底——
   BDC/EMC 落点随字形走，cov 低是针被渲染汤稀释而非位置错：
    - 主车道：`chars ≥ _MARK_FALLBACK_CHARS`(48) 且针微命
      `_text_cov ≥ _MARK_FB_COV`(0.10)（微命防 splice 错位裹进全无关段）；
    - 副车道：`chars ≥ _MARK_FB_CHARS_LO`(8) 且 `fraction < _MARK_FB_MAXFRAC`
      (0.92)——十几字形段首残件针覆盖全是噪声；folio 区（≥0.92）小碎片
      多为页码残件不兜（t_5248 seq87 "19" 实证）。

返回 `(trusted, gidx)`——gidx 复用于 `_match_side` 补缺。

## 5. 针配 `_match_side` / `_match_bounded`

- **针构建** `_needles`：`_tex_strip`（命令/花括号/`[[MATH_n]]` 等占位符剥除）
  → `_norm_chars`（去空白）。zh 针 min_len=2、en=4（信息量差）。
- **有界匹配**：gram(_GRAM=6) 倒排定候选窗 → `_sm_cov` 打分
  （SequenceMatcher 最长块 `need_blk` 按针长分档 `_min_cov`：
  <30 全等、<80 0.6、长针递减）+ 锚序连续性约束。
- **缝桥接**：`_sm_cov` 内部把匹配块间缝「渲染件残件」视作可桥——
  判据 `not _GAP_WORD_RX.search(gap)`：数字/bib 标签 (b2/e1)/单字母符号
  (π θ ukl) 全可桥；≥3 字母连跑 = 真词插入不桥。
- **短针纯插入车道**（ln < `_COV_SHORT`=30）：verbatim 之外只收
  「针侧全序连续 + 流侧缝皆 ≤ `_CITE_GAP`(20)」的匹配——逐字模渲染件
  插入；替换型近似仍弃（projectwho≈projectlead 冤锚前科）。

## 6. 行幅面与栏判定 `_row_extent`

`bounds` 行界自带 `[x, x1]` 幅面。锚（行顶 frac + 标内首字形 x）→ 同行幅面：

1. frac 先筛：`|b.frac - frac| ≤ _ROW_EPS`(0.012，~半行高) 圈同视觉行；
2. x 后定栏：在圈内按「锚 x 到行幅面距离」argmin 选行，
   距离 > `_ROW_EPSX`(0.03) 判离群返 None。

**顺序不可换**：双栏同行左右两段 frac 全同，先比 x 会撞错栏（37 处锚
右缘贴左栏实证）；先圈行再比 x 才对。

## 7. 死区抑制

双侧都无标的 seq = 死区候选（`\iftoggle` 吞参/声明点不渲染）。针配命中后滤：

- 落**别家 trusted 标幅面内**（`a ≤ o < b` 半开）= 近重复孪生段误锚 → 剥；
- 落**无标自渲区**（`\maketitle` 收集 - 迟发文本）→ 留（t_32fc seq1 署名实证）。

半开边界是刻意的：命中恰贴别家标幅面右端属邻位文本不算侵占
（t_32fc seq1 offset==seq0 span end 实证）。

## 8. 度量链（tools/seqpos_*）

| 工具                    | 面                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------ |
| `seqpos_warm.py`        | 全任务 seqpos.json 预热（幂等）                                                      |
| `seqpos_audit.py`       | 精度 oracle：`search_for` 字面真值，按侧×臂报 cov/wrong_page/p50/p90                 |
| `seqpos_clicksim.py`    | 点击→seq 仿真：nearest/floor_y/floor_c 三 picker 对照                                |
| `seqpos_verify_mask.py` | occurrence 遮蔽：ambig 命中是否把错 occurrence 洗成 0 误差                           |
| `seqpos_e2e_sim.py`     | **端对端**：每裹字形标位造点击，报 pick/pg/e2e@.10/e2e@.25/null/nodst/wrong_rows/inv |

e2e 指标口径：pick=点击选中率、pg=页正确率、e2e@ε=选中段 frac 误差 ≤ε、null=点击落无锚段、wrong_rows=选错段数、nearest=最近标=选中标比率（软密度指标非缺陷闸）、inv=阅读序逆序（浮动体重排属正常，inv_big>阈才算）、tnd=dst 无真值探针（测量盲区，不入 e2e 分母）。
**正当缺席**不算缺陷：死区段、未译段（zh=''）、folio 区页码残件、图/公式
非锚区点击不入 eval。

## 9. 修复沿革与基线

| _VERSION | 轮                  | 内容                                                                                                                                                                  |
| -------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ≤17      | v9/v10              | 栏感知锚（行顶 frac+x+ 中缝 + 块阈 64）落地（fd789c23+d5ed5b15）                                                                                                      |
| 20       | 死区抑制            | 0 字形空壳剥标记层、dead_seqs 碰撞滤、gutter 半步外扩（545e55af）                                                                                                     |
| 23       | 数学汤三件套        | 实标兜底车道×2、缝桥接放宽（数字→非词）、短针纯插入（4462fda0）                                                                                                       |
| 24       | 栏错配              | `_row_extent` frac 先筛 x 后定栏（63474133）                                                                                                                          |
| 25       | 锚验收三闸 + 针首 x | 周期 replay 剔页眉模板标（同 frac 跨 ≥3 页判运行头重打）、针起点投影纯化 occurrence、verbatim 先评免 `_CAND_CAP` 截断；`_pos_at` 行内字位 x 内插（dedcfea9+a86b4df9） |

基线：v24（19 任务）双侧 pick/pg/e2e@.10/e2e@.25 = 100%、wrong_rows=0、唯一 null=t_f748 死区两段（正确抑制）。v25 三任务复测（bbb/a7c5/bedd，真值探针扩面后的真实口径）：pick 双 100%、e2e@.25 o 91.4% / t 97.3%；tnd（dst 无真值探针的测量盲区，不入 e2e 分母）o ~1%、t 0%——bedd t 侧 45% 为源文真缺字盲区非错锚。修复实证：a7c5 seq0 双侧 p21→p1（页眉宏标不再淹没真标）、bbb seq0 引文行→p1 标题位、a7c5 zh seq1 snap 错锚→真位。

## 10. 已知边界

- 标裹字形不足 8 又 snap 不回的小碎片段仍无锚（位置证据真没有，宁缺勿滥）；
- `_interp_t` 降级臂吃 pairs 对齐质量；
- est_w 估宽噪声下贴中缝的锚行幅面判栏有 `_ROW_EPSX` 内不确定带；
- 上游 splice 注锚覆盖率（为何有的段标只裹段首十几字形）未在本层追，
  兜底车道已消化，根修属 reconstruct 侧问题。
