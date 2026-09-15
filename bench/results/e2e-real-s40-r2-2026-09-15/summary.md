# e2e real bench — swe-2-medium

- 样本: 40 篇（seed=42 layers=core）
- 网关: http://127.0.0.1:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 38/38 篇
- chunk 终态: ok 4547/4553 · partial 0 · fault 6 · skipped 0
- splice 残留占位符: 258（应为 0）
- **pipe-xel**: clean 19 fail 15 partial 4 /38
- **base-xel**: fail 17 partial 4 /21

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 15
- warn: 4
- missing_character×1: 2
- first_error 类别: missing_file×15, clean×4

- pipe-xel 非 clean 且 base-xel clean（管线引入）: []
