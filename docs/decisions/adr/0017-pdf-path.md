# ADR-0017 PDF 直译路径：BabelDOC spawn-CLI sidecar（无源码降级末级）

> **状态**：现行
> **日期**：2026-09-15（05 裁决 8）| 更新 2026-09-17（in-process 改判 spawn-CLI）

## 上下文

~13% arXiv 论文只有 PDF 没有 TeX 源码（pdf_only 是真实负载固有类，hot 层实测 13–28%）。要覆盖它们必须有 PDF 直译路径。候选：BabelDOC（PDFMathTranslate 后继，布局保留型 PDF 翻译，AGPL）、MinerU（OCR→md 重构）、自研。约束：BabelDOC 是 AGPL——我们 Apache-2.0 主仓不能链接它；PDF 路径是降级末级不是主路径，投入要克制。

## 裁决

- **BabelDOC 以 spawn-CLI sidecar 接入**：独立 venv + 子进程调 CLI——AGPL 留在进程边界外（主仓进程零链接、零 import 其代码），与 ADR-0001 的许可隔离裁决同构。
- **侧车纪律**：`--no-send-temperature`（其默认 temperature=0 被内部网关 400 拒——litellm 透传坑实证）；`-c` TOML 配置文件传 BYOK 三要素（不写命令行防 ps 泄漏）；`translate_tracking.json` 做静默失败侦测（CLI 退出 0 但没产出 = 静默 fallback，按失败记账）。
- **产出接入**：PDF 侧车产物进统一任务产物面（files 表 + 阅读器），但无 zh-src/dual 语义产物——PDF 直译无源码工程可言，天然不满足 share pack 要件（dual.json+zh-src.zip 缺失即 422）。
- **MinerU 否决**：OCR→md 重构译文路线在本里程碑不做（见 ADR-0019）——重排质量对论文版面是倒退，留作未来 OCR 兜底槽。

## 理由

- 进程边界是许可隔离最便宜的形式：BabelDOC 功能完整（布局/字体子集/双语模式都现成），自研 PDF 直译是另一个项目量级。
- spawn-CLI 而非 in-process 的实操理由更硬：依赖钉版隔离（其 torch/onnx 系依赖与主仓冲突面大）、崩溃域隔离、BYOK 传递可控。
- 证据：原 `docs/05` 裁决 8（已随 2026-09-20 文档库重建归 `docs/decisions/`）；调研档案 `docs/research/latex/pdf-path.md`、`docs/research/latex/doc-formats.md`；babeldoc 对照实验留痕于 `bench/archive-2026-09-20/results/babeldoc-smoke-report.md`（产物见同级 `babeldoc/`、`babeldoc-e2e-2026-09-16/` 目录；实验 venv 属用户侧件本未入库）。

## 演变

- 2026-09-15：初裁 in-process 调库（import babeldoc）——同日发现其依赖面与 AGPL 传染风险双重超标。
- 2026-09-17：**改判 spawn-CLI sidecar**——独立 venv 子进程；同波落地 `--no-send-temperature` 与 tracking 文件侦测两条实测教训。
- 降级链定位确认：e-print → arXiv HTML → BabelDOC 末级（ADR-0008）；pdf-path 只在无源码时触发，不作等价替代。

## 现状

实现落在 `server/babeldoc.py`（sidecar 编排：venv 定位、TOML 渲染、tracking 侦测）+ `server/worker/pdf.py`（任务臂）。babeldoc venv 是用户侧准备件（doctor 检查项），不进主仓依赖。
