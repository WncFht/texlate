# e2e real bench — swe-2-medium

- 样本: 100 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 91/91 篇
- chunk 终态: ok 10715/10718 · partial 3 · fault 0 · skipped 0
- splice 残留占位符: 1524（应为 0）
- **pipe-xel**: clean 28 fail 44 partial 19 /91
- **base-xel**: clean 10 fail 50 partial 11 /71

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 44
- warn: 17
- errors>3 : 9
- missing_character×1: 4
- missing_character×92: 1
- missing_character×1513: 1
- missing_character×851: 1
- first_error=undefined_cs: 1
- missing_character×1229: 1
- missing_character×11869: 1
- missing_character×4408: 1
- missing_character×1694: 1
- first_error 类别: missing_file×41, clean×9, syntax×8, latex209×3, other×1, undefined_cs×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0905.4907', '1206.5602', '1511.02908', '2203.13039', '2203.13109', 'cond-mat/0307508', 'physics/0111119', 'physics/9703012']
