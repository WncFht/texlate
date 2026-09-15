# fixloop 立项候选：译文进 .aux 的 8192B 边界截断

> 2026-09-16 xlat 评审移交（handoff §2.5 条目落地）。证据：
> `bench/results/e2e-real-s40-2026-09-15/results.json` → 2211.13013。

## 现象

pipe-xel 条件：verdict `partial`，reasons `warn:invalid_utf8`，first_error：

```
main.tex:104: File ended while scanning use of \@newl@bel.
```

## 机理（推断，待复现确认）

译文含 CJK 经 `\label`/`\newlabel` 写入 `.aux`；`.aux` 在 8192B
边界处多字节 UTF-8 序列被劈开 → 二次编译读 `.aux` 命中 invalid UTF-8
字节 → `\@newl@bel` 扫描越过 EOF。单引擎首轮失败、非确定性位点
（取决于 .aux 累计字节数 mod 8192）。

## fixloop 切入点建议

- 检测：`first_error` 匹配 `File ended while scanning use of \\?@?newl@?bel`
  或 log 里 `.aux` + invalid UTF-8 共现 → 新 fixup 类。
- 修复臂（按代价升序）：
    1. 删除/截断损坏 `.aux` 后重编（`.aux` 是重生产物，删了重长——首试）；
    2. normalize 期对 `\label{...}` 含 CJK 的工程预写 `.aux` 清场；
    3. 译文侧兜底：`\label`/`\ref` 族内容本就不该被翻译（scanner 保护缺口
       的下游症状——若 label 内出现 CJK 说明保护/切分上游漏了）。
- 判据：修复后 invalid_utf8 warning 消失 + `\@newl@bel` 不再 EOF。

## 关联

- splice/label 保护侧另见 e2e-n100 的 splice 残留调查（task #12）。
- 评审全文：`docs/research/product/2026-09-16-xlat-resume-review.md`。
