# e2e mock bench — corpus39

- **pipe-xel**: clean 8/16
- **pipeB-xel**: clean 7/16
- **pipeC-xel**: clean 3/16

- pipe-xel 失败且 base-xel clean（管线引入）: []
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 2452（事件 7543）→ caught 2231 / recovered 221 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 4948 处 / 涉块 2541 → 进 splice 2404 / 回退 137；编译 verdict 分布 {'clean': 3, 'fail': 2, 'partial': 11}
- 存活率 vs pipe-xel 基线: 14/14 篇出 pdf

