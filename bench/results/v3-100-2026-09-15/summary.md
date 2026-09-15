# e2e real bench — swe-2-medium

- 样本: 100 篇（seed=42 layers=core）
- 网关: http://127.0.0.1:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 91/91 篇
- chunk 终态: ok 10684/10688 · partial 3 · fault 1 · skipped 0
- splice 残留占位符: 1066（应为 0）
- **pipe-xel**: clean 46 fail 28 partial 17 /91
- **base-xel**: clean 9 fail 34 partial 10 /53

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 28
- warn: 14
- missing_character×1: 7
- errors>3 : 6
- first_error=undefined_cs: 2
- missing_character×92: 1
- killed_by_signal: 1
- missing_character×1229: 1
- missing_character×11869: 1
- missing_character×4408: 1
- first_error 类别: missing_file×27, clean×9, syntax×5, undefined_cs×2, other×1, already_def×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0905.4907', '1511.02908', '1706.07924', '2203.13039', '2203.13109', 'cond-mat/0307508', 'physics/0111119']
