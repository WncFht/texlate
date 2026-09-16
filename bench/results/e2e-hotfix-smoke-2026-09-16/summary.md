# e2e real bench — swe-2-medium

- 样本: 9 篇（seed=7 layers=hot）
- 网关: http://127.0.0.1:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 9/9 篇
- chunk 终态: ok 3037/3039 · partial 2 · fault 0 · skipped 0
- splice 残留占位符: 0（应为 0）— gate PASS
- **pipe-xel**: clean 2 fail 4 partial 3 /9
- **pipe-fix**: clean 1 fail 3 partial 3 /7
- **base-xel**: fail 3 partial 4 /7
- **pipe-fix 救回**: clean 1 · partial 3 /7（fixloop 内部 verdict: acceptable_pdf 2 best_effort_pdf 1 clean 1 unfixable:already_def 1 unfixable:missing_file 2）
- **pipe-fix 回退**（比 pipe-xel 差）: ['1502.03167', '2403.17888']

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 4
- warn: 2
- errors>3 : 1
- first_error=undefined_cs: 1
- first_error 类别: missing_file×4, already_def×1, undefined_cs×1, other×1

- pipe-xel 非 clean 且 base-xel clean（管线引入）: []
