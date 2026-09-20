# fixloop 立项候选：译文进 .aux 的 8192B 边界截断

> **结论**：译文 CJK 经 `\label`/`\newlabel` 写入 `.aux`，在 8192B 边界劈断多字节 UTF-8 序列 → 二次编译命中 invalid UTF-8、`\@newl@bel` 扫描越过 EOF；单引擎首轮失败、位点非确定（取决于 .aux 累计字节数 mod 8192）。
> **状态**：已修复（2026-09-16；现行实现位于 `compile/transcode.py::_transcode_intermediate` + `_trim_intermediate_tail`——`.aux` 系可再生中间产物与 `.bib/.bbl/.bst` 同档非 UTF-8 转码写回，中间产物另按行界截尾整形删不完整末行，引擎下遍重长；回归 `tests/test_normalize_aux_trunc.py`）
> **日期**：2026-09-16

2026-09-16 xlat 评审移交条目；证据为开发机 e2e-real s40 批次中的 2211.13013 失败格，结论已摘要进正文。

## 现象

pipe-xel 条件：verdict `partial`，reasons `warn:invalid_utf8`，first_error：

```
main.tex:104: File ended while scanning use of \@newl@bel.
```

## 机理

译文含 CJK 经 `\label`/`\newlabel` 写入 `.aux`；`.aux` 在 8192B 边界处多字节 UTF-8 序列被劈开 → 二次编译读 `.aux` 命中 invalid UTF-8 字节 → `\@newl@bel` 扫描越过 EOF。位点随 `.aux` 累计字节数漂移，表现为非确定性单引擎首轮失败。

## fixloop 切入点（立项建议）

- 检测：`first_error` 匹配 `File ended while scanning use of \\?@?newl@?bel` 或 log 里 `.aux` + invalid UTF-8 共现 → 新 fixup 类。
- 修复臂（按代价升序）：① 删除/截断损坏 `.aux` 后重编（重生产物，删了重长——首试）；② normalize 期对 `\label{...}` 含 CJK 的工程预写 `.aux` 清场；③ 译文侧兜底——`\label`/`\ref` 族内容本就不该被翻译，label 内出现 CJK 说明上游保护/切分漏了。
- 判据：修复后 invalid_utf8 warning 消失 + `\@newl@bel` 不再 EOF。

## 落地注记

实际修复落在 normalize/transcode 一侧而非 fixloop 规则：`compile/transcode.py` 把 `.aux` 纳入可再生中间产物转码面（`_transcode_intermediate`），并对中间产物按行界截尾整形（`_trim_intermediate_tail`）——不完整末行直接删，引擎下一遍自然重长，与机理分析一致且先于 fixloop 触发面解决问题。label 内 CJK 的上游保护缺口另由 splice/label 保护侧跟进（e2e-n100 的 splice 残留调查）。
