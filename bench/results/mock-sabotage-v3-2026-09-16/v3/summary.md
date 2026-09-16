# e2e mock bench — corpus39

- **base-xel**: clean 25/42
- **pipe-xel**: clean 34/42
- **pipeB-xel**: clean 30/42
- **pipeC-xel**: clean 26/42

- pipe-xel 失败且 base-xel clean（管线引入）: ['1003.1383', '1109.5963']
- pipe-tec 失败且 base-tec clean（管线引入）: []
## Mode B 台账 (pipeB-xel)
- 注入破坏块 1338（事件 4375）→ caught 1153 / recovered 185 / **escaped 0** — 门槛 escaped==0: **PASS**

## Mode C 台账 (pipeC-xel)
- 挪位 2062 处 / 涉块 1152 → 进 splice 1114 / 回退 38；编译 verdict 分布 {'clean': 26, 'fail': 3, 'partial': 12, 'reject': 1}
- 存活率 vs pipe-xel 基线: 38/40 篇出 pdf（退化: ['0806.1415', '1012.1584']）

