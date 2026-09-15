# e2e real bench — swe-2-medium

- 样本: 2 篇（seed=42 layers=core）
- 网关: http://127.0.0.1:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 1/1 篇
- chunk 终态: ok 62/62 · partial 0 · fault 0 · skipped 0
- splice 残留占位符: 0（应为 0）
- **pipe-xel**: clean 1 /1
- **base-xel**: fail 1 /1

## 失败模式（pipe-xel verdict.reasons 计数）

- pipe-xel 非 clean 且 base-xel clean（管线引入）: []
