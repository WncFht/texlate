# e2e mock bench — corpus_v3

- **base-xel**: clean 1/8
- **pipe-xel**: clean 2/8
- **pipeB-xel**: clean 2/8
- **pipeC-xel**: clean 1/8

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.3472']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 323（事件 1064）→ caught 271 / recovered 52 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 525 处 / 涉块 331 → 进 splice 329 / 回退 2；编译 verdict 分布 {'clean': 1, 'partial': 7}
- 存活率 vs pipe-xel 基线: 8/8 篇出 pdf

