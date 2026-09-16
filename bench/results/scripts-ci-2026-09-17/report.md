# scripts-ci — scripts/ + workflows/ 审计交付

> 2026-09-17。scope：scripts/** + eslint.config.js + bench/results 内 tracked .sh。shfmt/shellcheck/actionlint 全净。

## 改动文件（8 个，全部小修）

| 文件 | 改动 | 原因 |
|---|---|---|
| `scripts/gwcap/ensure-bypass.sh` | `for i` → `for _` | SC2034 unused var——**CI shell job 实证会红**（该文件已入库） |
| `bench/results/repro-2501-2026-09-16/repro.sh` | `shfmt -w` | tracked .sh 且未过 shfmt——**CI shell job（`git ls-files '*.sh'` 全扫）下一个 push 必红**。已按链内同规格式化（bench/results 内 tracked 文件事实在链内：babeldoc.toml 过 taplo、md 过 markdownlint） |
| `scripts/fmt-shell.sh` | `read` EOF 边界：`read \|\| [ -n "$first" ] \|\| exit 0` | 空输入 / 单行无尾换行 → read 返回 1 → `set -e` 退出 1 → gfs 报 formatter 失败（实测复现 rc=1，修后 rc=0 且输出 identity） |
| `scripts/server-smoke.sh` | 补 `cd "$(dirname "$0")/.." \|\| exit 1`；`json.load` 双读改单读 | 缺仓根锚定——`uv run` 在仓外必炸成"health 15s 未就绪"谜语；TID 兜底分支第二次 `json.load(sys.stdin)` 对已耗尽 stdin 必然 raise（fallback 是死代码） |
| `scripts/loc.sh` | 桶内 grep 包 `{ \|\| true; }` + 三处 `xargs -r` | 某桶零非数据文件时 grep exit 1 经 pipefail → `set -e` 静默死在半篇报告中间；空输入还会让 `wc -l` 打一行假 `0` |
| `scripts/git-stash-export.sh` | `cd` 锚定 + `rev-parse --verify` 预检 + `for`→`while read` | 默认 outdir `tmp/` 相对 CWD——子目录调用会把导出物漏进 tracked 区；空格路径被 for 分词劈碎；坏 stash ref 原先是晚失败谜语 |
| `scripts/demo.sh` | MAIN_TEX / PDF 空值守卫 ×2 | fetch/run 未产出时下游 `parse ""`/`pdftotext ""` 报错不可读 |
| `eslint.config.js` | ignores +`tmp/`、`src/texlate/server/static/`、`bench/corpus*/`（原 `bench/corpus/` 未含 v2/v3） | **`npm run lint:js` 本地实测炸**：eslint 下钻 `tmp/refs/` 嵌套 flat config → ERR_MODULE_NOT_FOUND；修后又扫出 static/ 打包物与 corpus_v3 e-print 自带 .js 共 136 个假错。CI 因干净 clone 全绿——本地红/CI 绿的同源缺口 |

## 验证结果（全绿）

- `shfmt -i 2 -d scripts/` → 0 diff；`shellcheck -S warning scripts/*.sh scripts/gwcap/*.sh` → 净
- **CI shell job 镜像**（`git ls-files '*.sh'` 全量 shfmt -d + shellcheck）→ fails=0
- `actionlint` → 净；`npm run lint:js` → 0 problems；`prettier --check eslint.config.js` → 过；改动脚本 `sh -n`/`bash -n` 全过；`loc.sh` 实跑正常

## CI 漂移表（ci.yml/release.yml vs 本地真源）

| 项 | CI | 本地源 | 裁断 |
|---|---|---|---|
| eslint 严格度 | `eslint .`（lint:js） | hook 带 `--max-warnings 0 --no-warn-ignored` | **漂移（latent）**：当前树 0 warnings 但 hook 比 CI 严——本地被拦的 commit CI 反而放行。建议 lint:js 加 `--max-warnings 0`（留给 leader 定） |
| gitleaks | 无 job | hook v8.30.1 + .gitleaks.toml 自定义规则 | **缺口**：自有凭据格式 CI 从不扫（GitHub push protection 只盖标准 pattern）。疑似刻意取舍，请 leader 确认 |
| autocorrect | 无 | md 链 `autocorrect\|prettier` | 非门洞——autocorrect 是改写器，入库 md 已是其稳定态，prettier --check 够用 |
| bench/results 划出口径 | shell/md/py/toml gate 仍扫 | 仅 prettier-js/md hook + .prettierignore + eslint 划出 | **口径分裂**：CLAUDE.md 称"整目录划出 format/lint"，实际只对 churn 型 formatter 成立（repro.sh 事故即此出）。建议要么修文档措辞，要么补 exclusion——需 leader 定政策 |
| Node | 22 ×3 job | Dockerfile `NODE_VERSION=22`；无 engines/.nvmrc | 一致 |
| Python | 未显式钉（uv 自举） | requires-python>=3.12；Dockerfile `PYTHON_VERSION=3.12` | 一致，uv --frozen 走 uv.lock ✓ |
| tectonic | 0.17.0 + sha256 8533d0… | Dockerfile ARG 逐字相同 | 一致（与注释"与 Dockerfile 同源"相符） |
| ruff/shfmt/shellcheck/actionlint/taplo | brew 浮动 | brew 浮动 | 同源 ✓ |
| prettier/markdownlint/eslint/gfs | npm ci 锁 lockfile | package.json 唯一事实源 | 同源 ✓ |
| web job | tsc+eslint+vitest+build | web/package.json scripts | 一致；另注意 pre-commit eslint glob `jsx?\|mjs\|cjs` **不含 ts**——web 前端本地零 eslint 门，CI 比本地严（不违反"本地不过 CI 必挂"，但本地绿≠CI 绿，观察项） |
| release.yml | node22/uv/build-web.sh/wheel断言/docker ghcr | 与 ci.yml + Dockerfile 同源 | 干净；`uv tool install` 冒烟 + SPA 入包断言齐 |

## 审过未动（无问题）

agent-links / build-web / crossnote-links / dev-smoke / find-gateway-hog / gw-health / gw-tunnel / gwcap/install.sh + 两个 unit + tailscaled dropin / tcp-relay.py。crossnote-links 对 README.md/scripts/tests/vendor 不验存在就 ln -sfn——当前事实源 8 项全在，无悬挂链，记观察。

## 遗留观察（未修，理由各附）

- `git ls-files '*.sh'` / `for f in $(...)` 模式（ci.yml shell job、loc.sh）对空格文件名脆弱——当前零触发，修要动 CI 行，留作记录
- `demo.sh --real <id>` 参数序怪癖（`--real` 在首位会吞掉 id）；find-gateway-hog 双 pgrep 可出重复 PID——均为诊断/演示工具，容忍
- 测试残留 `tmp/stash-export-*/` 已自清
