# ADR-0016 阅读器前端：SolidJS + pdfslick 薄壳 + named-dest 锚点同步

> **状态**：现行
> **日期**：2026-09-15（05 裁决 5/18）| 更新 2026-09-17（DomPane 降级面随 G1 落地）

## 上下文

双语对照阅读器的核心是「滚一边另一边跟」——但 zh/en 两份 PDF 的页码、分页位置、段落位置全不同构。hjfy 的做法（服务端算好对齐数据）启示：锚点同步是数据问题不是渲染问题。框架选型要求可逆——阅读器只是管线产物的薄壳，框架锁死等于把薄壳做成承重墙。

## 裁决

- **栈**：SolidJS + Vite + `@pdfslick/solid`（pdfjs 的 Solid 薄封装）——选 Solid 不选 React：细粒度响应式契合「滚动位置高频更新」负载，包更小，且框架是可逆决策（壳薄，换掉不碰管线）。
- **锚点同步**：`align.py` 离线算 named-dest 锚点映射（`\label`/hyperref 目标在 zh/en 两树的页内位置）→ 加权单调链配对 → 消费侧折算 `{page, fraction, viewport}` 三要素定位；滚动侧 ignoreTop 哨兵 + rAF 节流 + epoch 戳防过期事件回写。
- **降级面**：主路径双 PDF 对照；`HtmlPane`/`DomPane` 承接非 PDF 产物形态（arXiv HTML 任务的 DOM 块级对照）——产物形态决定 pane，不是一pane通吃。
- **版本语义**：`key={doc.version}` 重挂载——版本变即全新文档，锚点表/页表随组件销毁重建，杜绝旧锚点污染新版本。

## 理由

- E18 锚点实测：named-dest 覆盖 + 单调链配对把可同步段落锚点保留率推到 ~100%（对齐探针口径）；纯页码按比例映射的精度在图表密集论文上不可接受。
- 前端壳薄原则：所有「聪明」都在 align.py 与产物 JSON 里，前端只做映射消费——框架替换成本被刻意压到最低。
- 证据：主仓 `docs/05` E18；调研档案 `research/latex/alignment-probe.md`、`research/product/web-layer.md`。

## 演变

- 2026-09-17：G1 落地新增 `DomPane`——arXiv HTML 链任务（kind=arxiv_html）在 en 侧直接渲染 arXiv 官方 HTML DOM 块，锚点同步面复用同一 {page,fraction,viewport} 折算的 DOM 对应物；share 导入产物走同一阅读器。
- 阅读器扩面：done 终态阅读器 + partial 终态 result-banner + doc 类任务产物面板三形态收口；「分享本译文」按钮挂三点（见 ADR-0012）。

## 现状

实现落在 `web/`（SolidJS+Vite+pdfslick，独立 package.json/tsconfig/vitest，CI web job 跑 tsc/eslint/vitest）+ `src/texlate/align.py`（named-dest 锚点同步算法件）。前端构建产物由 server `staticfiles.py` 同进程托管。
