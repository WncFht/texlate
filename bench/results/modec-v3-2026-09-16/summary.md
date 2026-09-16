# e2e mock bench — corpus_v3

- **base-xel**: clean 22/48
- **pipe-xel**: clean 27/48
- **pipeB-xel**: clean 24/48
- **pipeC-xel**: clean 17/48

- pipe-xel 失败且 base-xel clean（管线引入）: ['0806.3472']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 1564（事件 4932）→ caught 1345 / recovered 219 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 2537 处 / 涉块 1590 → 进 splice 1575 / 回退 15；编译 verdict 分布 {'clean': 17, 'fail': 8, 'partial': 18, 'reject': 5}
- 存活率 vs pipe-xel 基线: 35/42 篇出 pdf（退化: ['astro-ph/0104134', 'astro-ph/0501428', 'cond-mat/9910284', 'hep-th/0408076', 'math/9901064', 'nucl-th/0307063', 'quant-ph/0307209']）

