# e2e mock bench — corpus_v3

- **base-xel**: clean 48/80
- **pipe-xel**: clean 68/80
- **pipeB-xel**: clean 69/80
- **pipeC-xel**: clean 60/80

- pipe-xel 失败且 base-xel clean（管线引入）: ['2003.10723', 'solv-int/9910006']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 2797（事件 9386）→ caught 549 / recovered 2248 / **escaped 0**
- dirty 0（交付 zh 命中协议回显签名且 src 不含——multiset 可对而载荷脏，escaped 的内容通道盲区）
- armed 0（交付块 src 自带协议签名——同形 echo 与忠实译文裸包含不可区分，结构性盲区只观测不进门槛；其中 zh 同命中 0 块不可判定）
- 门槛 escaped==0 AND dirty==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 5254 处 / 涉块 2808 → 进 splice 2791 / 回退 17；编译 verdict 分布 {'clean': 60, 'fail': 1, 'partial': 19}
- 存活率 vs pipe-xel 基线: 79/79 篇出 pdf

