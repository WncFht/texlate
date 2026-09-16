# scripts-ci-audit — scripts/ + CI/pre-commit/gitignore 全量审计（17 文件，两 commit 落地）

> 2026-09-17 收口。scope：scripts/（14 sh + 2 py + gwcap 全套）+ .github/workflows/{ci,release}.yml + .pre-commit-config.yaml + .gitignore。工具链全在场（shellcheck 0.11 / shfmt 3.14.1 / actionlint 1.7.12 / ruff 0.16.7 / prettier via node_modules），零 SKIP。
> 落地：`ea67f7b`（scripts/ 14 件）+ `c8a05c7`（ci.yml + pre-commit + gitignore）。

## 修复明细

**scripts/gw-tunnel.sh** — `is_up()` 真 bug：`curl -w '%{http_code}' | grep -q .` 连接失败时 curl 仍输出 `000` → 恒真，隧道死了也报 OK（实测复现）。改 `curl -sf -o /dev/null -m 5`。

**scripts/demo.sh** — ① 参数解析重写为 for-case：`--real 2105.11479` 旧代码把 ID 静默重置回默认；② `MAIN_TEX` 多版本目录 `head -1` glob 序任意 → `sort -V|tail -1` 取最新版；③ pdftotext 缺失误报"未检出中文" → `command -v` 守卫；④ 固定 `/tmp` 工作目录 → `mktemp -d`（并行/重跑互踩；已核实 `run -w` 容忍已存在空目录）。

**scripts/dev-smoke.sh** — 固定 LOG 名 → mktemp（多会话互截、PORT 解析抓到别家端口）；端口正则补 `127.0.0.1:` 形态。

**scripts/find-gateway-hog.sh** — `pgrep -x` + `pgrep -f` 双路且 -x⊂-f 致 PID 重复 → 单路 `pgrep -f | sort -u`；`ss` grep `:${PORT} ` 尾随空格锚定（:3003 误中 :30030）。

**scripts/fmt-shell.sh** — `*zsh*` → `'#!'*zsh*`：首行注释含 "zsh" 的 bash 脚本旧被静默透传。4 分路实测全对。同口径同步到 shellcheck hook 与 ci.yml。

**scripts/git-stash-export.sh** — ① stash 内 deleted 文件 `git show` 失败 → set -e 中断整批 → 记档跳过+清残；② `$S^3` 不存在时 `git archive|tar -x` 空输入噪音 → `rev-parse --verify` 预检。真 stash@{0} 实跑：62 文件导出干净。

**scripts/loc.sh** — ① 全管道 `git ls-files -z | grep -z | xargs -0r`；② 新增 `(root)` 桶——根级文件（AGENTS.md/pyproject.toml 等）原不进任何桶 TOTAL 漏计（实跑 root=1306 行）；③ --cloc 固定 /tmp 名 → mktemp。

**scripts/server-smoke.sh** — ① openapi.json `curl -s|python3` 无闸 → `curl -sf --max-time 10 || fail`；② 各 curl 补 --max-time。端到端实跑全绿（health→16 routes→upload→SSE done→4 artifact sha256→端口释放）。

**scripts/tcp-relay.py** — ① `LISTEN/TARGET` 顶层解析在 argc 检查前 → 无参崩 traceback 而非 usage，移入 `__main__` 卫语句；② `handle` 上游 connect 失败未捕获 → 客户端 socket 泄漏，补 `except OSError: cw.close()`。实测 usage + 真 relay 200。

**scripts/agent-links.sh** — ① `ln -sfn AGENTS.md CLAUDE.md` 对实体文件无守卫（真文档会被无声吞掉）→ `-e && ! -L` 拒绝；② dangling 清理：`.claude/skills/*` 指向已消失目标的软链删除。幂等实跑通过。

**scripts/crossnote-links.sh** — ① 软链循环补 `[[ -e $SRC/$item ]]`（源缺件旧产 dangling）；② 硬链 `rm + ln` → `ln -f tmp && mv -f` 原子替换。

**scripts/gwcap/ensure-bypass.sh** — ① `$mode` 加 `ensure|remove` usage 校验（旧任意值当 ensure 跑）；② 复查分支裸 `insert_top` → `{ del_all; insert_top; }`（竞态重钉留双规则）。

**scripts/gwcap/install.sh** — ① `enable --now` → `enable`+`restart`（重装覆盖已运行实例时 enable --now 是 no-op）；② uninstall 补 `[ -x ensure-bypass.sh ] && remove`（unit 半坏时 bypass 残留压不住 ts-input drop）；③ `groupdel gwcap`。

**scripts/gwcap/gw-cap-redirect.service** — `ExecStop=` 加 `-` 前缀：表不在时 restart/stop 不卡 failed。

**.github/workflows/ci.yml** — ① 顶层 `permissions: contents: read`（旧无声明吃默认权限；fork PR 面同步收窄）；② shell job `for f in $(git ls-files)` word-splitting → `ls-files -z | while read -d ''`；③ zsh 探测锚定 `^#!.*zsh`；④ taplo `xargs -0r`。

**.pre-commit-config.yaml** — ① shellcheck hook zsh 锚定；② 全部改写型 formatter（markdownlint-cli2/prettier-yaml/shfmt/ruff-format/taplo）统一 `exclude: "^bench/results/"`——gfs stdin 通道拿不到文件名，工具级 exclude 兜不住 stdin 格式化，显式划出落实"划出改写型"教义。

**.gitignore** — 补 `/dist/`（uv build 产物，根目录现有残留，release.yml 同目录）。

## 自验

shellcheck -S warning + shfmt -d -i 2 全 14 脚本净；actionlint 净；ruff 双净；bash -n/sh -n 全过；prettier --check 改动 yaml 净。功能实测：fmt-shell 4 分路、tcp-relay usage+relay、agent-links 幂等、loc.sh 输出、git-stash-export 真 stash、server-smoke 全链、ensure-bypass usage guard、ci shell-loop errexit 语义。

## 未修项（有意记档）

- release.yml `ls dist/...whl` 多 wheel 拿多行——单产物 vacuous。
- ci.yml 无 autocorrect check（`autocorrect --lint` 可加但是新门控，留 leader 取舍）。
- gw-tunnel respawn 循环端口被占时无限重试——文档化容错设计。
- `dev-smoke.sh` health-mock 校验 warn-only——playwright 才是真闸。
- mktemp `XXXXXX.log` 后缀是 GNU 扩展——本仓脚本全面 Linux 化无 macOS 诉求。
- `gw-cap-proxy.py` 审完无改动需求（`_local_json` wfile BrokenPipe traceback 仅 journald 噪音）。

## 外部路由（leader 处理）

1. **CLAUDE.md/AGENTS.md 文档漂移**（已修）：宣称 "bench/results tracked 文件仍在 check 类链内"——事实相反：markdownlint 经 cli2 ignores 划出、ruff 经 extend-exclude 划出、shfmt/shellcheck/taplo vacuous。文档已按实态改写。
2. `scripts/__pycache__/tcp-relay.cpython-314.pyc` 磁盘残留——已核实未入库（gitignore 覆盖），磁盘文件已清。
3. `ci.yml` `on.push.branches:[master]` vs PR 主分支 main——本仓工作分支即 master，故意性确认保留。
4. pre-commit gitleaks 钉 v8.30.1 vs ci.yml brew 浮装——跨版本扫描差异风险，记档不钉（brew 无便捷钉版）。
5. engine job xelatex apt 未钉版——文档已声明取舍。
6. 别家在飞：`texput.log`（gitignored）、`tests/test_group_surface_depth.py` 未跟踪——未动。
