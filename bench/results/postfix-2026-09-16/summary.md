# e2e real bench — swe-2-medium

- 样本: 100 篇（seed=42 layers=core）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 100/100 篇
- chunk 终态: ok 10723/10729 · partial 6 · fault 0 · skipped 0
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 56 fail 9 partial 35 /100
- **pipe-fix**: clean 6 fail 2 partial 10 /18
- **base-xel**: clean 13 fail 14 partial 17 /44
- **pipe-fix 救回**: clean 6 · partial 10 /18（fixloop 内部 verdict: acceptable_pdf 10 best_effort_pdf 1 clean 5 unfixable:expl3_backend 1 unfixable:pkg_order 1）

## 失败模式（pipe-xel verdict.reasons 计数）
- warn: 18
- no_pdf: 9
- first_error=undefined_cs: 9
- latex209: 8
- errors>3 : 7
- missing_character×1: 5
- missing_character×60: 1
- missing_character×3: 1
- missing_character×92: 1
- first_error=missing_graphic: 1
- first_error=missing_file: 1
- missing_character×4379: 1
- first_error 类别: clean×10, undefined_cs×9, missing_file×8, syntax×3, other×1, hyperref_driver×1, babel_opt×1, missing_graphic×1, pkg_order×1, expl3_backend×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0707.3950', '0905.4907', '1003.4522', '1012.1321', '1109.5963', '1206.1808', '2003.10959', '2105.03900', '2211.04495', 'cond-mat/0307508', 'hep-ph/9703228', 'hep-ph/9910403', 'math/0111203']
