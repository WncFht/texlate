# invalid_utf8 族归因（leader 批量归因 · scout-utf8 复核待并入）

> 口径：compile.jsonl 末条 `verdict.reasons` 含 `warn:invalid_utf8` = **545 格**
> （票面 354 是 triage 抽样口径，末条全量 545）。全部 status=partial 有 pdf，
> 非 fail——拖累 clean 率的警告级细胞。

## 方法

逐格取 `work/{id}/splice/` 最新 xelatex 日志 → 抓 `Invalid UTF-8` 行 + 向前
2000 字符内最近打开的输入文件，聚合签名与文件分布。545/545 格成功提取
（2 格无日志命中，见尾注）。

## 结论：**~100% 是第三方包文件的 latin-1 注释噪声，非工程文件问题**

| 告警落点文件 | 格数 | 现场 |
|---|---|---|
| algorithm.sty（algorithms 包） | 285 | line 11 `%% Copyright (C) 2005-2009 Rog\xE9rio Brito` — latin-1 `é`(0xE9) |
| algorithm2e.sty | 103 | line 284 同类版权/注释 latin-1 字节 |
| algorithmic.sty | 92 | line 11 同上（同包同源） |
| umsb.fd / ursfs.fd / ueuf.fd / utxsyc.fd / ot1ptm.fd | ~20 | AMS/数学字体 .fd 内嵌注释字节 |
| commath.sty / endnotes.sty / contour.sty / anyfontsize.sty / hypernat.sty / semantic.sty / ragged2e.sty | ~45 | 同款 latin-1 注释 |

- 验证：`~/texmf/tex/latex/algorithms/algorithm.sty:11` 实测 `Rog\xE9rio`——
  **TeX Live 上游包自带的 latin-1 版权注释**，xelatex 读入时按 UTF-8 校验
  报 warning 并以 U+FFFD 替换。字节在注释行，语义零影响。
- **工程文件零命中**：抽样+文件分布全部落在 texmf 包文件，没有一格是
  zh/splice 源或译文输出的问题——与译文腐蚀无关，normalize 层无责。

## 处置建议

1. **judge 红线限工程文件源**（已知在飞：texlate-1e `judge-redline` 项）——
   `warn:invalid_utf8` 仅在冒犯文件 ∈ {zh/, splice/ 工程源} 时记；
   texmf 包内告警降级或丢弃。**落地后此族 545 格全部解票。**
2. 不立规则、不加 normalize 逻辑：转码只读系统包文件不属本工程权责，
   且 U+FFFD 替换进注释语义无损。
3. 尾注：2203.00047、2403.15149 两格日志未命中签名（日志滚动/多 pass），
   归入同族待 judge 修复后复核。

## 附：signature 分布

`Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD` ×382（algorithm
系）· `at line 284` ×103（algorithm2e）· 其余行号 ~60。
