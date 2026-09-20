# ADR-0006 编译管线：引擎路由 + 依赖探测 + clean 判据 + 沙箱

> **状态**：现行
> **日期**：2026-09-14（初裁 xelatex 主）| 更新 2026-09-15（05 裁决 6/13/14/15/20/21）、2026-09-16（latex209_suspect 试编、reject_at 归一）

## 上下文

编译引擎二选一不够：tectonic 便携（单二进制、自动拉宏包）但有三面硬墙——xdvipdfmx 不渲染 EPS/PS、bundle 缺物理字体、bundle 宏包版本旧；xelatex+TeXLive 全量但分发重。判定语义被三次实证推翻：tectonic 静默降级（「出 PDF」≠成功）、非 UTF-8 源码在 xelatex 下 0 `!` 出 PDF 但正文 U+FFFD 损坏、`\documentstyle` 工程三引擎全死。翻译范围、预编译探雷、执行沙箱也需要定案。

## 裁决

- **引擎策略：分发默认 tectonic 优先 + xelatex 兜底 + 静态预检路由；开发默认 xelatex**（fixloop 地面真值、可修性最高）。`Engine` 协议抽象（caps/compile/probe_file/install_file/rebuild_fontmaps/filemap）双实现。
- **静态路由表**：EPS/PS 图与 pstricks → xelatex 优先；minted+frozencache 共现 → tectonic 优先（bundle v2.6 兼容，xelatex v3.8 报 50 错）或 `{minted}`→`{minted2}` 改写；bbm 类位图字体包 → tectonic 高风险标记；`\special{psfile}` dvips 原语插图 → 双引擎均不渲染、走降级。dvips 通道语义 = EPS/PS 兜底而非 LaTeX 2.09 出路（E17 改判），且需 `.pro` 文件 preflight。
- **LaTeX 2.09**：route 层打 `latex209_suspect` **先试编**——inject 兜底拒注入；真 2.09 签名（tail 侧 `\documentstyle`/`COMPATIBILITY MODE`）由 fixloop gate `latex209_reject` 拒 → 降级链。ptptex.cls 已不可得，不做 2.09 原生编译。
- **翻译文件集：`compiled_dependencies()` 为权威**——编译产物 `.fls` INPUT 行 / tectonic `--makefile-rules` 决定翻哪些 .tex；静态 `\input` 图只作编译失败时的降级。
- **target_probe**：翻译前先以「译文桩」替换英文词编译一遍（零 token），暴露字体/模板问题再花钱；探针失败直接进 fixloop。
- **clean 判据三件套**：①有 pdf；②`!`≤3 且首错非 missing_*/undefined_cs；③log warning 扫描——`Invalid UTF-8 byte`/`Missing character.*U+FFFD`/tectonic `File.*not found` 降级行/missing_graphic 红线任一命中即 dirty；外加「中文实际进 PDF」（Missing character 计数与字体表 CJK 佐证）。tectonic 有时不写 .log，监控不假设 log 存在。
- **沙箱**：tectonic `--untrusted` + env 白名单（非黑名单）+ `openin_any=p openout_any=p shell_escape=f` + macOS sandbox-exec + 进程树超时杀。
- **终态语义**：策略拒绝（route/inject/fixloop 三处）统一归 `partial` + `reject_at` 审计字段——拒绝是降级交付不是 fault。

## 理由

- E9 引擎矩阵：12 项目初始 tectonic 7/12 clean、xelatex 4/12，联合 clean 9/12——两引擎失败集几乎互补，路由 + 兜底覆盖最大面。
- E10：「出 PDF≠成功」实锤（56 处丢占位符 0 编译错误）；latin-5 静默污染证明 `!`≤3 有盲区 → warning 扫描补洞。
- E17：pstricks 工程可救（vendored sty 摘除 + xelatex 0 错 32p），dvips 降为兜底通道。
- E19：tectonic 自动 bibtex 生成的 stub bbl 在虚拟 FS 遮蔽真 bbl——`.bbl` 直消费须 `\bibliography{x}`→`\input{x.bbl}` 改写（归 fixloop 规则，ADR-0007）。
- 证据：主仓 `docs/05` E9/E10/E17/E19；调研档案 `research/latex/engine-matrix.md`、`research/latex/pstricks-route.md`、`research/latex/ctanfetch-probe.md`。

## 演变

- 2026-09-14 → 09-15：引擎默认从「xelatex 主 + tectonic 降级」改判为「tectonic 优先 + xelatex 兜底」（分发面；开发面仍 xelatex）。
- 2026-09-16：裁决 13「`\documentstyle` 无条件 reject」部分推翻——route 改 `latex209_suspect` 先试编，真 2.09 签名由 fixloop gate 拒（`38cc0a7`）。
- 2026-09-16：策略拒绝不再单列 `reject` 终态，三处统一 `partial` + `reject_at`（`87e6a40`）。
- 2026-09-17：inject 遇 2.09 先走 `upgrade_209` 转换器（ADR-0005）。

## 现状

实现落在 `compile/engine/` 包（`_base` Engine 协议 + `_xelatex`/`_tectonic` 双实现 + `_route` 静态路由表 `route_project`/`engine_for` + `_cache`）、`compile/deps.py`（compiled_dependencies）、`probe.py`（target_probe）、`judge.py`（clean 三件套判定）、`sandbox.py`、`latex209.py`、`toolchain.py`、`proc.py`；fixloop 引擎循环见 ADR-0007。
