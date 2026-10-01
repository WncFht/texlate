# research/latex/ —— LaTeX 管线域

围绕「arXiv LaTeX 源码 → 半解析 → LLM 翻译 → 重编译中文 PDF」主链路的调研档案：解析管线设计取证、校验三层、引擎路由与修复规则库、宏包资产构建、翻译 prompt 与出件格式、外部参考实现解剖。实现现状的唯一事实源在 `spec/`（`spec/latex-pipeline.md`、`spec/compile.md`），本域保留的是决策当时的证据、参数规格与外部世界快照——与代码漂移处以代码为准。

## 索引

### 解析管线（`latex/`）

| 文件                                                               | 内容                                                                                                                      |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| [expansion-design.md](expansion-design.md)                         | mouth→gullet→segmenter 三段式展开设计：pos 不变式（分类不物化）、transparent 两档、\def argspec 编译、oracle 实测——已落地 |
| [expansion-timing.md](expansion-timing.md)                         | 展开时机语料取证：use-before-def=0、`\if` 两档分布、深度 ≤4——单遍管线裁决依据（时点证据）                                 |
| [segmenter-integration.md](segmenter-integration.md)               | v2 接线契约 + S1–S4 落地记录：vtex 叙事序账本、EXPAND 组、`\if` marker 夹心、零宽/乱序陷阱集——已落地                      |
| [miniscanner-rewrite-spec.md](miniscanner-rewrite-spec.md)         | **SUPERSEDED**：v1 字节 scanner 规格（已删）；仅留四类 leak 机制解剖与验收账作历史参考                                    |
| [2026-09-15-adversarial-audit.md](2026-09-15-adversarial-audit.md) | 对抗性二审：16 处修复 + 31 探针；corpus 门照不到的死角与 warning 分布归因方法                                             |

### 校验层（`validate/`）

| 文件                                     | 内容                                                                                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| [validator-rules.md](validator-rules.md) | L0 规则校验器设计：7 规则、10 类破坏 100% 检出、0/313 误报、lev≤2 修复建议——已落地 `validate/l0.py`                              |
| [validator-ts.md](validator-ts.md)       | L1 tree-sitter 校验：@pfoerster/tree-sitter-latex 选型、relative 模式生产形、40/40 检出、陷阱集——已落地 `validate/ts/` + `l1.py` |

### 编译路由与修复（`compile/`）

| 文件                                                                 | 内容                                                                                                                                 |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| [engine-matrix.md](engine-matrix.md)                                 | tectonic/xelatex × 12 类失败形态实测矩阵：7/12 vs 4/12、E1–E12 分类法、路由结论——已落地 `compile/engine/_route.py`（时点证据）       |
| [pstricks-route.md](pstricks-route.md)                               | pstricks 失败根因（vendored sty 与新 tex 错配）与四路由规则——已落地                                                                  |
| [ctanfetch-probe.md](ctanfetch-probe.md)                             | tlpdb.xz 离线索引 + tlnet 直拉「mini-tlmgr」实测：cwd shadow 生效/TEXINPUTS 不生效、bbl stub、版本兼容陷阱——已落地 `compile/ctan.py` |
| [fixloop-rules.md](fixloop-rules.md)                                 | fixloop 规则库 YAML 化：16 规则全表、87% install 系主力、tectonic 降级矩阵汇于 `ctan_fetch`、沉淀机制——已落地 `compile/fixloop/`     |
| [2026-09-16-aux-cjk-truncation.md](2026-09-16-aux-cjk-truncation.md) | .aux 8192B 边界劈断 UTF-8 事故：机理与修复臂——已修复于 `compile/transcode.py`                                                        |

### 宏包与数据资产

| 文件                               | 内容                                                                                   |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| [ctan-argspec.md](ctan-argspec.md) | `latex/data/argspec.json` 构建：六源合并法、78.6%/98.9% 覆盖、未知命令保护取舍——已落地 |

### 翻译 prompt 与出件

| 文件                                               | 内容                                                                                                                                                                                |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [prompt-glossary-spec.md](prompt-glossary-spec.md) | prompt 套件 + 术语表设计：LaTeXTrans/MathTranslate/ieeA 三源证据、ph→ph 恒等注入（v5 已由 manifest 名单行替代）、批量/断点协议——已落地 `xlat/prompts.py` + `glossary.py` + `terms/` |
| [doc-formats.md](doc-formats.md)                   | bbm 的 EPUB/DOCX 机制解剖（DRM 允许表、clone-insert、对齐阶梯）+ 抄/不抄清单——已落地 `export/`（含落地差分注记）                                                                    |
| [pdf-path.md](pdf-path.md)                         | babeldoc sidecar 规格：分层静默回退、进度事件、AGPL 边界、MinerU 对比——已落地 `server/babeldoc.py`（spawn-CLI 形）                                                                  |

### 外部实现解剖与对齐实证

| 文件                                       | 内容                                                                                                                               |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| [texglot-patterns.md](texglot-patterns.md) | TeXGlot v1.1.0 全栈模式目录：visible_tex 归一化、named-dest 同步、双层缓存键、tectonic 分发、结构化重翻回路 + 反面清单——多项已落地 |
| [alignment-probe.md](alignment-probe.md)   | named-dest 锚点保留率实测 28 对：10/11 ≥0.94、退化路径 31%——滚动同步可行性裁决依据（时点证据）                                     |

## 阅读建议

理解 v2 解析管线的形态由来按 `expansion-design.md` → `expansion-timing.md` → `segmenter-integration.md` 顺序读，`miniscanner-rewrite-spec.md` 只作 v1 历史参考；理解编译失败的修复路径读 `engine-matrix.md` + `fixloop-rules.md` + `ctanfetch-probe.md`；找外部实现可借鉴的设计读 `texglot-patterns.md`（全栈）与 `prompt-glossary-spec.md`（翻译层）；`alignment-probe.md` 是滚动同步立项的实证底稿。
