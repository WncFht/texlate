# e2e mock bench — corpus39

- **base-xel**: clean 9/25
- **pipe-xel**: clean 13/25
- **pipeB-xel**: clean 8/25
- **pipeC-xel**: clean 4/25

- pipe-xel 失败且 base-xel clean（管线引入）: ['1412.6980', '1612.09375', '1706.03762', '2106.09685']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 2137（事件 6567）→ caught 1932 / recovered 205 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 3242 处 / 涉块 1797 → 进 splice 1724 / 回退 73；编译 verdict 分布 {'clean': 4, 'fail': 2, 'partial': 19}
- 存活率 vs pipe-xel 基线: 23/23 篇出 pdf

