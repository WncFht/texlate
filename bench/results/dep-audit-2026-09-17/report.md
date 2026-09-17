# dep-audit — 依赖卫生审计交付（只读）

> 2026-09-17 收口。探针 `tmp/dep-audit/audit.py`（gitignored）。**verdict: clean** —— OSV querybatch 覆盖全部 37 个锁定 PyPI 包 0 漏洞；root/web/bench-ts 三处 `npm audit`（含 dev）各 0 漏洞；无 yanked；许可证全宽松（MIT/BSD/Apache/PSF/ISC/MPL-2.0 certifi）。"act now" 栏为空。

## Python（uv.lock vs PyPI latest）

实质全部 current。仅三处滞后：

- pypdf 6.18.1 → 6.19.0（minor，随下次例行刷新）
- pydantic-core 2.46.5 → 2.49.0（transitive，随 pydantic 下一 bump 到位）
- defusedxml 0.7.1：上游最新稳定版停在 2021-03，0.8.0rc 系（2023-09）从未 finalize，仓库 ~2024-09 起静默——仍是 stdlib 文档推荐的 XXE/billion-laughs 防线，**保留但标记为实质无人维护上游**（low）。

fastapi 0.141.1 / starlette 1.6.0 / httpx 0.28.1 / lxml 6.1.3 / typer 0.27.2 / sse-starlette 3.4.11 / pytest 9.1.1 / pytest-asyncio 1.4.0 等其余全部 current。

### 卫生项（leader 已落地）

uv.lock 312 条 registry 全记 `mirrors.aliyun.com`，而 pyproject `[[tool.uv.index]]` 声明 tuna——根因是本机 `UV_DEFAULT_INDEX=aliyun` 在 lock 时覆盖 pyproject。后果：CI `uv sync --frozen` 跨太平洋拉 aliyun；无该 env 的协作者跑 `uv lock` 会产出全文件 URL churn。**已修**：pyproject index 对齐 aliyun（声明=锁定=本机 env，三者一致后 churn 面消失）。

## JS

- root：prettier 3.9.6→3.9.7（patch）；eslint 10.10.0 / @eslint/js 10.0.1 / globals 17.12.0 / markdownlint-cli2 0.23.2 / git-format-staged 4.0.2 全 latest。
- web/：仅 typescript ~5.9.3 vs latest 7.0.2（TS7 是 native-compiler 线，留 5.9 等 typescript-eslint 8.x 跟进属合理——watch 项非 action）+ @types/node patch；solid-js 1.9.15 / vite 8.3 / vitest 5 / pdfjs-dist 6.3 / marked 18 / katex 0.18.7 / dompurify 3.4.15 / eslint 10 全 current。
- bench/ts：所有 resolved 依赖 current（unified-latex 1.8.4 / latex-utensils 7.0.0 / tree-sitter 0.25.1）。
- **bench/ts 死依赖**（7 个脚本零 require()）：`node-tree-sitter` 0.0.1——弃坑单发布 stub，repo 指向 gitee.com/arashrun 非官方 fork（真包已改名 `tree-sitter` 且在用）；另有 `web-tree-sitter` 与 @unified-latex 的 ctan/util-arguments/util-environments/util-packages。**建议移除全部 6 个**——node-tree-sitter 尤其（非官方来源 native binding 闲置在 node_modules）。*待 shell 恢复后 `npm uninstall` 重生 lockfile 再入库。*
- 重复 pins：eslint/@eslint/js/globals 在 root 与 web package.json 同 range 手工同步——今日一致，仅留意。

## CI（.github/workflows/ci.yml，leader 已落地）

- actions/checkout v4 → v7（v7.0.1 latest，v5+ 迁 node24 runtime）
- actions/setup-node v4 → v7（v7.0.0 latest）
- astral-sh/setup-uv v5 → v10（v10.1.0 latest；NO_PROXY 支持 + sensitive-event cache 加固）
- gitleaks pre-commit rev v8.30.1 = latest；brew 装工具（ruff/shfmt 等）有意浮动。

## 遗留观察（非行动项）

- defusedxml 上游维护停滞（前述）。
- typescript 7.0 native line 待 typescript-eslint 跟进后再评估。
- root/web 三套 eslint 系 pins 手工同步，未来可考虑单源化。
