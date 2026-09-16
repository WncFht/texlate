# e2e mock bench — corpus_v3

- **base-xel**: clean 23/48
- **pipe-xel**: clean 30/48
- **pipeB-xel**: clean 30/48
- **pipeC-xel**: clean 29/48

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.3472', '1306.1931']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 1564（事件 4932）→ caught 1345 / recovered 219 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 2516 处 / 涉块 1572 → 进 splice 1557 / 回退 15；编译 verdict 分布 {'clean': 29, 'fail': 3, 'partial': 16}
- 存活率 vs pipe-xel 基线: 45/45 篇出 pdf

