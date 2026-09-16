# e2e mock bench — corpus39

- **base-xel**: clean 11/39
- **pipe-xel**: clean 15/39
- **pipeB-xel**: clean 10/39
- **pipeC-xel**: clean 4/39

- pipe-xel 失败且 base-xel clean（管线引入）: ['1412.6980', '1612.09375', '1706.03762', '2106.09685', 'math/0404188']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 4546（事件 14056）→ caught 4133 / recovered 413 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 8426 处 / 涉块 4580 → 进 splice 4405 / 回退 175；编译 verdict 分布 {'clean': 4, 'fail': 4, 'partial': 30, 'reject': 1}
- 存活率 vs pipe-xel 基线: 34/35 篇出 pdf（退化: ['hep-th/9901001']）

