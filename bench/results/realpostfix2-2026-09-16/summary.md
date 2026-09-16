# e2e real bench — swe-2-medium

- 样本: 100 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 100/100 篇
- chunk 终态: ok 10706/10717 · partial 5 · fault 5 · skipped 1
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 76 fail 14 partial 10 /100
- **pipe-fix**: clean 9 fail 5 partial 10 /24
- **base-xel**: clean 2 fail 14 partial 8 /24
- **pipe-fix 救回**: clean 9 · partial 10 /24（fixloop 内部 verdict: acceptable_pdf 8 best_effort_pdf 3 clean 8 unfixable:missing_file 4 unfixable:other 1）

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 14
- warn: 7
- missing_character×1: 5
- errors>3 : 2
- missing_character×3: 1
- first_error=missing_graphic: 1
- first_error=missing_file: 1
- first_error=undefined_cs: 1
- first_error 类别: missing_file×12, clean×6, syntax×1, missing_graphic×1, already_def×1, pkg_order×1, undefined_cs×1, other×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0905.4907', 'hep-ph/9910403']
