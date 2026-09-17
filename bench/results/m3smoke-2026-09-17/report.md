# M3 产品全链冒烟（2026-09-17）

派工口径：`127.0.0.1:8765` 实测 `/` SPA → arxiv 翻译 → 进度 → reader → babeldoc → export docx/epub。每步记 200/耗时/产物/挂点。**src/git 未动，bug 只记录不修**。

## 关键前提：首跑实例是陈旧构建

`texlate web`（pid 2375544，`uv run` 自 repo `.venv`）已运行 ~27.6h——**早于今日 babeldoc 硬化（12:49）与 worker split/fixloop 接线（14:27）**。首跑在其上测得的两个失败均为旧构建行为而非现行代码缺陷。已将实例重启为当前代码复测（任务已终态，无损）。**建议：/api/health 加 build/commit 戳，陈旧实例一眼可辨**。

## 结果矩阵（重启后当前代码）

| 步骤 | 结果 | 证据 |
|---|---|---|
| `GET /` SPA | ✅ 200，745B，2.4ms | index.html 送达（static+mount_spa 端到端通） |
| `POST /api/arxiv/0707.0255/translate` | ✅ 202 → **partial** @100%，~3min | zh.pdf **578KB** + zh_src.zip 314KB + dual.json 102KB + compile.log 30KB |
| 进度/SSE 口径 | ✅ 实时 | status/stage/progress 平滑迁移（queued→translating 59→99→终态），`GET /api/task/{id}` 轮询可见 |
| reader | ✅ 200 | `/api/task/{id}/reader` 72B 描述符；dual_json 在产物表（HtmlPane 数据源成立） |
| babeldoc sidecar（PDF 上传） | ✅ **done** @100%，~75s | en.pdf 13KB + **zh.pdf 31.8KB + dual.pdf 48KB** + dual.json |
| export zh.docx | ✅ done，~75s | zh_docx 1665B——**解包实证含双语插译**（原文 + "你好世界，这是一段用于翻译的冒烟测试段落。"） |
| export zh.epub | ✅ done，~75s | zh_epub 1152B |

BYOK 实测：settings PUT base_url=https://api.llm7.io + 任意 key + model=GLM-5.3-Flash（免费 OpenAI 兼容端点）→ Gateway/babeldoc 两臂同吃，凭证透传链（`-c` TOML）工作。

## 首跑（陈旧实例）对照——证明修复生效

| 路径 | 旧构建表现 | 现行构建 | 结论 |
|---|---|---|---|
| arxiv 编译 | **fault**：`aastex.cls not found`，fixloop:null，无 rounds 现场 | **partial**：有 PDF——fixloop 已进管线且起效 | fixloop 接线实证 |
| babeldoc | fault："未产出译文 pdf"——babeldoc-out 空（旧 spawn 不传 `--openai`，0.6.4 硬要求服务标志） | done：三件套+dual.json | sidecar 硬化实证 |

## 挂点/缺陷记录（不修）

1. **B1 — babeldoc 错误面吞根因**：无 BYOK 时 fault 文案恒为 `babeldoc 未产出译文 pdf`；真根因（0.6.4 要求 `--openai` 服务标志/未配 key）被吞——建议把 babeldoc stderr/rc 摘要带进 fault.message。
2. **B2 — 模型可用性传播**（观察非缺陷）：llm7 拒 `gpt-4o-mini` → 95% 处 fault 且真错误透出（"Model unavailable"），行为正确；但 settings 存了不可用 model 会持续毒化后续任务——值得登记 UX 注记。
3. **B3 — 陈旧实例风险**（已述）：长驻 `texlate web` 服旧码无标识——加 build 戳或启动时校验。
4. **B4 — mock 臂 partial 属预期**：0707.0255 判 "有 pdf 但判据未全绿或块级失败"——mock translator 不过 post-judge 严判属已知口径，非新 bug；vendored-shim 落地后此类 missing_file 格可升档。
5. en_pdf 登记即源 PDF——口径正常。

## 结论

**当前代码 M3 交付链端到端可用**：SPA/翻译/fixloop/reader 数据/babeldoc/docx/epub 全绿出产物，BYOK 透传实证。昨日审计所列断点全部复验闭合；唯二需跟进=B1 错误面吞因 + 建议 health 加 build 戳。30min 内完成（含实例重启与 BYOK 模型排障）。
