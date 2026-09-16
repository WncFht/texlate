# probe-audit — compile/probe.py + normalize.py 代码级审计（两波收口）

> 2026-09-17 收口。scope：`src/texlate/compile/probe.py` + `normalize.py` + 对应测试，对照 docs/08 §3.2/3.4 规格。实证探针 `tmp/probe-audit/`。scoped `pytest -k "probe or normalize"` **131 passed**；ruff format/check 净。
> 落地：主波 `d51e11b`（probe kpathsea cwd 语义 + normalize 安全波）+ 补充波 `6d4d18a`（2 回归测试）。

## 主波修复（d51e11b）

### probe.py — kpathsea cwd 语义对齐

- 依赖解析改「单跳 compile-cwd」语义：kpathsea 以编译工作目录为锚，原实现沿 \input 链以「当前文件目录」逐跳解析 → 深层 \input 引用的同目录件被误判 missing。修为单跳：所有相对引用统一从 main 所在目录（=compile cwd）解。
- **dead-tail 跳过**：`\end{document}` 之后的 \input/\includegraphics 等引用不再计入 deps/missing（TeX 语义上文档体终结后内容不执行）。
- `\InputIfFileExists` 归 optional 类：存在性自判宏不再进 missing 硬缺。
- `\openin`/`\openout` 参数审计：shell-escape 管道形态（`|cmd`）识别隔离，不误判为文件依赖。

### normalize.py — 安全波

- **microtype 多包形态**：`\usepackage{microtype,…}` 混排时旧只认单包注入点，现逐包扫。
- `strip_input_encodings` 行保留：改写维持行号（诊断/日志行号不漂移）。
- `use_bundled_bibliography` 加 cwd 参数 + first-missing-only：多次调用不再重复处理同一缺失。
- **PS DSC 二进节保留**：PostScript `%!PS` 文档的 binary section（DSC 约定）改写时不再被文本化处理破坏。
- **is_symlink 写穿防护 7 处**：所有就地改写前查 symlink——树内 symlink 指向树外时拒绝写穿（防越写工作区外文件）。

## 补充波（6d4d18a）— 按 #167 登记单补边界回归测试

- `test_circular_input_terminates`：A↔B 循环 \input —— visited 去重锁 BFS 终止 + inputs 无重复（锁既有正确行为）。
- `test_clean_name_filters_noise_tokens`：`\input{\cs}` / `\input @tempb` 噪声 token 滤除——不进 deps/missing（锁 `_NAME_RE` 行为）。

## 审计结论（其余登记点）

main 缺席路径、queue BFS 顺序、deps_diff basename 兜底、`_norm_dep` 归一化——审计均判正确或有意的启发式取舍，已在登记单逐条记档。

## 外部路由

- `invalid_utf8` normalize recode 扩面（`.sty/.cls/.def` bundled 件 + 二进 epsi→notes，144 格）——normalize.py 现已稳定，扩面可开（leader 车道已排）。
