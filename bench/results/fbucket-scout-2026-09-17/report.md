# F-bucket 残余定性（2026-09-17）

> 口径：`bench/results/stagerun-loop1-2026-09-16/records/` 末条胜 + gate_scorecard 终态合成（compile zh → fixloop post 覆盖，csb 校验）。F 格 = 终态 verdict `cjk_chars==0`。复算用 `texlate.compile.judge.pdf_cjk_chars` 原函数。

## 结论先行

**verdict 假阳亚型（0-chunk main 吃 cjk_chars=0）已归零**——`expect_cjk = translate.chunks != 0`（e2e.py:939 / stagerun.py:1091）生效，当前记录面零格 xlat chunks=0 却背 cjk=0。所谓「F 桶 keyarg 结构漏 50」与「451→528 级联下沉」的陈树携带部分随 parse recut 波抽干，**当前残余共 7 格（mock 臂；real 臂 0）**，全部是真零（译文确实没渲染进 PDF），judge 口径无误伤，另 2 格临界带 `0<cjk<20`。

7 格全部由 compile fail（missing_file）→ fixloop install 救援 → post 判 partial 路径进入。cjk=0 在 6/7 格里与 errors/missing_chars 冗余；**唯 1706.00217 是 cjk=0 单因拦截**——且拦截正确（中文产品 0 中文字就是失败）。

## 机理三型

### 型一 F-echo：mock 保真盲区（1 格）

**1706.00217**（fixloop clean → post partial；`clean:russian`）：俄文论文，xlat 9 chunks 全 ok 但 `xlat-state/mock/state.json` 里 translation 与 source 逐字节相同；zh/main.tex 全文零 `这是译文`。机理：`MockTranslator._PROSE_RUN_RX = [a-zA-Z][^\n]*[a-zA-Z]|[a-zA-Z]`（pipeline.py:223）只替换拉丁字母 run，西里尔散文原样回显 → zh 树零 CJK → 真 0。属 bench 侧 mock 失真，非管线缺陷。**附带口径缝**：fixloop 内部判 `fixloop_verdict=clean`（装了 babel-russian 能编译即收），post judge 带 expect_cjk 判 partial——fixloop「clean」命名不查 CJK，目前以 post 覆盖兜底无账目错乱，但值得知晓。

### 型二 F-font：xeCJK 绑定失效全文灭字（2 格）

**2410.00046**（nature_meth 类）、**2410.18001**（article 类）：zh 树 `这是译文`×155/142 命中正文（`\item{这是译文}` 等），splice 经 fixloop 已注入 ctex[fontset=fandol] + xeCJK warmup + texlatefb 声明，log 确认 xeCJK.sty/FandolSong 族创建成功——但 Missing character ×3188/2157 全部落在 `[lmroman*]:mapping=tex-text`，缺字符=这/是/译/文/图/表/中/字（纯 CJK）。pdftotext 抽出的是 U+FFFD（缺字形替代符，CJK_RX 不计）→ 真 0。即 **CJK 在正文但被绑回 Latin Modern，xeCJK interchartoks 未接管**——E(b) 字体绑定/结构洞家族同族，warmup 不兜。fixloop 救援动作是 install `kotex.sty`（韩语包治中文缺字，错配）。修复车道 = fixer-font-fallback-8bit / structpos，非判分。

### 型三 F-stub：错误风暴截断输出（4 格）

**astro-ph/0307062、astro-ph/0501187、astro-ph/0501259**（aa.cls shim）、**nucl-ex/0408018**（graphicx.tex）：fixloop install 救援后 TeX 仍 61–101 错误 → 输出 1–2 页 stub（仅未译卷首），译文段根本未 ship → cjk=0 是上游失败的症状读数。

- astro-ph 三格首错同一形态：`Missing \endcsname inserted` ×100 at `\section{这是译文}`——csname 扫描吞掉 `\section` 控制序列（R1 csname 端点家族样貌）；注意 aa.cls 是 **fixloop 写的 35 行 legacy shim**（`fixloop legacy shim -> article + A&A polyfills`），该错可能是 shim 引入而非源生，归 fixer shim/polyfill 复核。
- nucl-ex/0408018：fixloop 装的 `graphicx.tex`（Carlisle miniltx 包装）在 `\def\Gin@extensions{\zap@space#1 \@empty}` 无限递归 → `input stack size` 爆栈（10000i 打满）→ 1 页 stub。属 install 救援物自身缺陷。

## 修法建议

1. **judge 不用 tune**：7/7 真零，cjk=0 判据语义正确；唯一单因格（1706.00217）恰是它拦下的假 clean。
2. **F-echo（可选）**：`_PROSE_RUN_RX` 扩到 Unicode 字母 run（如 `[^\W\d_]` 起锚），让非拉丁源也产出 `这是译文`；或在 bench 文档登记「mock 对西里尔/希腊源恒等」为已知盲区。面=1 格。
3. **F-font**：归 fixer-font-fallback-8bit 车道；另建议 fixloop 签名侧收窄——`missing_character` 命中 U+4E00–U+9FFF 时应走 binding/font_fallback 动作而非 `install`（kotex 错配实证）。
4. **F-stub**：cjk=0 不独立出票，随各格上游错误票走；两个具体钩子——(a) aa.cls shim 在三格同炸 `\section`，复核 shim 的 maketitle/abstract 五段式是否把 csname 扫描引到结构 cs；(b) `graphicx.tex` 安装物在 xelatex 下 `\zap@space` 递归，装前应有 sanity 或换 driver 尾。
5. **临界带**（0<cjk<20，非本桶但同源）：1706.00222（cjk=2，errors×93+missing×15）、cond-mat/0307193（cjk=9，undefined_cs:\vert ×124）——与 F-stub 同机理（stub/截断输出），随上游票即可。

## 数据面附注

- 残余集合明细：`fcells-mock.json` / `fcells-real.json`（本目录）。
- 全部 7 格 `compile_status=fail`（missing_file: aa.cls×3 / kotex.sty×2 / graphicx.tex / babel_opt russian）→ fixloop acceptable/best_effort/clean 救援后 post 撞 cjk=0。
- 历史对照：wave2 时 F=11 verdict 假阳 + keyarg 结构漏 50；recode 波 451→528（陈树携带 387）；本扫 = 7，假阳与结构漏两亚型在记录面均已不可见。
