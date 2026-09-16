# e2e mock bench — corpus_v3

- **base-xel**: clean 37/60
- **pipe-xel**: clean 44/60
- **pipeB-xel**: clean 46/60
- **pipeC-xel**: clean 39/60

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.1984', '0806.3144', '0905.0795', '1003.0112', '1404.0275', '1404.0527', '1706.00265']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 2343（事件 7535）→ caught 2047 / recovered 296 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 4286 处 / 涉块 2287 → 进 splice 2231 / 回退 56；编译 verdict 分布 {'clean': 39, 'fail': 2, 'partial': 19}
- 存活率 vs pipe-xel 基线: 58/58 篇出 pdf

