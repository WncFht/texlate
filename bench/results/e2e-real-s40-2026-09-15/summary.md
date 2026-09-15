# e2e real bench — swe-2-medium

- 样本: 40 篇（seed=42 layers=core）
- 网关: http://127.0.0.1:3003 model=swe-2-medium

## 环节通过率
- 翻译执行（chunks>0）: 36/36 篇
- chunk 终态: ok 4354/4365 · partial 0 · fault 11 · skipped 0
- splice 残留占位符: 0（应为 0）
- **pipe-xel**: clean 16 fail 14 partial 6 /36
- **base-xel**: clean 3 fail 17 partial 4 /24

## 失败模式（pipe-xel verdict.reasons 计数）
- no_pdf: 14
- warn: 5
- missing_character×1: 3
- cjk_unverified+missing_chars: 1
- errors>3 : 1
- first_error 类别: missing_file×14, clean×4, other×2

- pipe-xel 非 clean 且 base-xel clean（管线引入）: ['1907.10324', '2211.13013']
