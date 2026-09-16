# e2e mock bench — corpus_v3

- **base-xel**: clean 44/80
- **pipe-xel**: clean 65/80
- **pipeB-xel**: clean 67/80
- **pipeC-xel**: clean 59/80

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.3144', '1404.0275', '1404.0527', '1706.00265', 'hep-th/0408064']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 3114（事件 10376）→ caught 548 / recovered 2566 / **escaped 0**
- dirty 0（交付 zh 命中协议回显签名——multiset 可对而载荷脏，escaped 的内容通道盲区）
- 门槛 escaped==0 AND dirty==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 5428 处 / 涉块 2901 → 进 splice 2889 / 回退 12；编译 verdict 分布 {'clean': 59, 'fail': 3, 'partial': 18}
- 存活率 vs pipe-xel 基线: 77/77 篇出 pdf

