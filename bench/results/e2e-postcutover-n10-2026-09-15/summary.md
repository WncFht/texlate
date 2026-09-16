# e2e real bench — swe-2-medium

- 样本: 10 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 10/10 篇
- chunk 终态: ok 1189/1192 · partial 1 · fault 1 · skipped 1
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 1 fail 4 partial 5 /10
- **base-xel**: clean 2 fail 4 partial 3 /9

## 失败模式（pipe-xel verdict.reasons 计数）
- warn: 4
- no_pdf: 4
- errors>3 : 2
- missing_character×1: 2
- missing_character×60: 1
- first_error=undefined_cs: 1
- first_error 类别: missing_file×4, clean×2, other×1, undefined_cs×1, syntax×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0707.3950', '1012.1321']
