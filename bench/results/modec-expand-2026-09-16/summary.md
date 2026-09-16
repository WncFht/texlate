# e2e mock bench — corpus_v3

- **base-xel**: clean 44/80
- **pipe-xel**: clean 54/80
- **pipeB-xel**: clean 56/80
- **pipeC-xel**: clean 47/80

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.1984', '0806.3144', '0905.0795', '1003.0112', '1404.0275', '1404.0527', '1706.00265', 'hep-th/0408064']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 3123（事件 10102）→ caught 2720 / recovered 403 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 5368 处 / 涉块 2904 → 进 splice 2822 / 回退 82；编译 verdict 分布 {'clean': 47, 'fail': 2, 'partial': 31}
- 存活率 vs pipe-xel 基线: 78/78 篇出 pdf

