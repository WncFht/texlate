# e2e mock bench — corpus

- **base-xel**: clean 1/2
- **pipe-xel**: clean 1/2
- **pipe-tec**: clean 1/2
- **pipeB-xel**: clean 1/2

- pipe-xel 失败且 base-xel clean（管线引入）: []
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 121（事件 377）→ caught 0 / recovered 121 / **escaped 0**
- dirty 0（交付 zh 命中协议回显签名且 src 不含——multiset 可对而载荷脏，escaped 的内容通道盲区）
- armed 0（交付块 src 自带协议签名——同形 echo 与忠实译文裸包含不可区分，结构性盲区只观测不进门槛；其中 zh 同命中 0 块不可判定）
- 门槛 escaped==0 AND dirty==0: **PASS**

