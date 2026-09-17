# e2e real bench — swe-2-medium

- 样本: 200 篇（seed=42 layers=core,booster,hot,expand）
- 网关: http://100.105.212.52:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 198/198 篇
- chunk 终态: ok 24089/24163 · partial 25 · fault 0 · skipped 49
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 150 fail 24 partial 24 /198
- **pipe-fix**: clean 23 fail 1 partial 24 /48
- **base-xel**: clean 6 fail 25 partial 17 /48
- **pipe-fix 救回**: clean 23 · partial 24 /48（fixloop 内部 verdict: acceptable_pdf 13 best_effort_pdf 14 clean 20 unfixable:undefined_cs 1）

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 24
- warn: 14
- errors>3 : 11
- first_error=undefined_cs: 5
- missing_character×2: 5
- missing_character×1: 5
- missing_character×271: 1
- missing_character×3: 1
- killed_by_signal: 1
- first_error=missing_graphic: 1
- missing_character×5: 1
- first_error 类别: missing_file×23, clean×10, undefined_cs×5, syntax×3, other×3, babel_opt×2, missing_graphic×1, soul_err×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['0806.2915', '0905.1119', '1306.0099', '1706.00183', '1803.00181', '2308.04246']
