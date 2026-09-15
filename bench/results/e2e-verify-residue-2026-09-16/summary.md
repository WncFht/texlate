# e2e real bench — swe-2-medium

- 样本: 7 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 7/7 篇
- chunk 终态: ok 1225/1226 · partial 1 · fault 0 · skipped 0
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 3 fail 2 partial 2 /7
- **base-xel**: fail 2 partial 2 /4

## 失败模式（pipe-xel verdict.reasons 计数）
- warn: 2
- missing_character×1: 2
- no_pdf: 2
- first_error 类别: clean×2, missing_file×2

- pipe-xel 非 clean 且 base-xel clean（管线引入）: []
