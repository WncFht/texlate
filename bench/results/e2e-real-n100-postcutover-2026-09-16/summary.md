# e2e real bench — swe-2-medium

- 样本: 100 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 100/100 篇
- chunk 终态: ok 10445/10476 · partial 6 · fault 1 · skipped 24
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 31 fail 40 partial 21 reject 8 /100
- **pipe-fix**: clean 20 fail 13 partial 7 /40
- **base-xel**: clean 13 fail 45 partial 11 /69
- **pipe-fix 救回**: clean 20 · partial 7 /40（fixloop 内部 verdict: acceptable_pdf 4 best_effort_pdf 4 clean 19 unfixable:latex209 3 unfixable:missing_file 8 unfixable:other 2）

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 40
- warn: 13
- first_error=undefined_cs: 10
- latex209: 8
- errors>3 : 6
- missing_character×1: 4
- missing_character×60: 1
- missing_character×3: 1
- missing_character×92: 1
- missing_character×4379: 1
- first_error 类别: missing_file×39, undefined_cs×10, clean×6, other×3, syntax×3

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0707.3950', '0905.4907', '1012.1321', '1206.1808', '1511.02908', '2003.10959', '2105.03900', '2203.13109', 'cond-mat/0307508', 'hep-ph/9703228', 'hep-ph/9910403', 'math/0111203', 'math/0307301']
