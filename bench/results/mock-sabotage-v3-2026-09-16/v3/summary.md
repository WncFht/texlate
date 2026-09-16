# e2e mock bench — corpus39

- **base-xel**: clean 14/18
- **pipe-xel**: clean 18/18
- **pipeB-xel**: clean 15/18
- **pipeC-xel**: clean 14/18

- pipe-xel 失败且 base-xel clean（管线引入）: []
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 381（事件 1217）→ caught 335 / recovered 46 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 572 处 / 涉块 344 → 进 splice 331 / 回退 13；编译 verdict 分布 {'clean': 14, 'fail': 1, 'partial': 3}
- 存活率 vs pipe-xel 基线: 17/18 篇出 pdf（退化: ['0806.1415']）

