# zotero/dev — 验证工具链

一条命令回答「插件在真 Zotero 里端到端工作吗」。六件可组合的工具 + 一份共享 env（`env.sh`，端口/路径单源），全部 scratch 落在 `tmp/zotero-dev/`（gitignored），绝不碰用户真实 Zotero 库与真实 texlate 实例。

## 反馈通道三性质

每件工具的头注释都带这三性质 + 四字段骨架（适用条件/变换方法/资源约束/验证证据）——它们既是工具的设计约束，也是验收标准：

1. **局部可归因** — 断言失败绑到具体步骤/字段/输入，不许只报「e2e 挂了」。dev-server 六步断言各自带名、首个 `[FAIL]` 即停并截断呈现违例响应；selftest 每步落 `detail` 证据；dev-zotero 把插件状态分三层回报（`rdp-dead` / `not-registered` / `registered-not-init` / `loaded`），「没装上」还是「装上没起来」一眼分清。
2. **廉价及时** — 单步探针能答的不跑全链：`dev-server check` 对已在跑的服务 30s 内出六步结论；`rdp` 秒级 eval；`dev-zotero verify` 一次性断言插件 loaded；全链 e2e 只作终验。
3. **客观可验证** — 判据只落机读事实：HTTP 码、JSON 字段、11 态枚举、sha256/字节数、`%PDF` 魔数、`Zotero.texlate.data.initialized===true`。日志只做诊断证据，不当判据；相关不等于因果，结论要有受控对照（破坏测试）。

## 架构

```text
dev-profile                 dev-server                     dev-zotero
隔离 profile + fixture ──→ 真 texlate + mock 翻译 :18765 ──→ xvfb 隔离实例 + 插件
        │                          │                            │
        └──────────────── rdp（JS-eval 咽喉，:6100）─────────────┘
                                     │
                          dev-verify（编排 PASS/FAIL 矩阵 + 破坏测试）
```

- `env.sh` — 端口/路径/二进制单源（source 用，不直接执行）；每个工具自己 source 它，也允许 env 覆盖。
- `dev-profile` — 建隔离 Zotero profile（seed `user.js` 开 RDP/关首跑弹窗）→ xvfb 起实例 → rdp 写 7 条确定性 fixture：DOI/url/archiveID/extra 四个提取级各一条（含 old-format `hep-th/`）+ 一条非 arXiv 负例。
- `dev-server` — `TEXLATE_TRANSLATOR=mock` + 独立 `TEXLATE_DATA_DIR` 起真 `uv run texlate web`：fetch/parse/compile 全真、翻译确定性假译零 token；六步 curl e2e（health/create/poll/files/download/reader-url）。
- `dev-zotero` — `npm run build` → extensions 指针文件装插件（scaffold asProxy 同款机制）→ xvfb 起 `--start-debugger-server` 实例 → rdp 探活 + 三层插件探针 wait。
- `rdp` / `rdp.mjs` — Firefox RDP 裸 TCP 零依赖客户端，在 zoteroPane 主窗口 context eval 任意 JS 取回 JSON。**整条链的咽喉**：fixture 写入、selftest 驱动、菜单断言全过它。
- `dev-verify` — 编排全链：经 rdp 驱动 `Zotero.texlate.selftest` 出逐项 PASS/FAIL 矩阵，并支持破坏测试（见下）。

## 工具参考

### env.sh

- **适用条件** — 所有 dev 工具；`source` 使用。
- **变换方法** — 定义 `TEXLATE_DEV_ROOT`/`TEXLATE_DEV_DATA`/`TEXLATE_DEV_PROFILE`/`TEXLATE_DEV_ZDATA`/`TEXLATE_DEV_PORT`/`TEXLATE_DEV_RDP_PORT`/`ZOTERO_BIN`，全部 `:-` 可覆盖；`texlate_dev_port_free` 断言端口空闲并打印占主。
- **资源约束** — 8765 是本机真实 gateway 实例、8766 被 status_panel 长占——dev 端口固定在 18765/6100；每个工具 bind 前断言空闲 + 连上后验明正身（health `.data_dir` / RDP 握手），绝不 squat 真实服务。
- **验证证据** — 端口取值在写入时实测空闲；`dev-server check` 撞错实例（如 8765 真 gateway）直接 FAIL。

### dev-server

- **适用条件** — `uv sync --extra server` 已跑、本机可拉 arXiv、tectonic 在 PATH。
- **变换方法** — setsid 起 `uv run texlate web` 独立进程组 + 独立 `TEXLATE_DATA_DIR`；curl 逐步打 API。
- **资源约束** — scratch 全在 `tmp/zotero-dev/`（server.pid/server.log/zh.pdf）；poll 死线 900s；stop 只杀 pidfile 记的进程组（校验 /proc cmdline 防 pid 复用误杀）。
- **验证证据** — `[PASS]` 行带 task_id/sha256/字节数；`tmp/zotero-dev/zh.pdf` 实物落盘。
- **用法** — `dev-server [run|start|stop|check|logs]`（缺省 run：起服 + 六步 e2e，跑完留服）。

### dev-profile

- **适用条件** — zotero + xvfb-run；fixture 增删改查依赖 `rdp`。
- **变换方法** — `xvfb-run zotero --profile <P> -datadir <D> --start-debugger-server <PORT>`；rdp eval JS 写库（async 结果经 globalThis 槽轮询读回）。
- **资源约束** — 只写 `tmp/zotero-dev/`；`-datadir` 写死命令行——不带会开 `~/Zotero` 真库。
- **验证证据** — `verify` 逐 fixture 断言字段精确匹配（含负例字段不泄漏 arXiv），非零退出即失败；`list` dump 全库条目关键字段。
- **用法** — `dev-profile {create|verify|list|clean}`；create 幂等可重跑。

### dev-zotero

- **适用条件** — zotero + xvfb-run + node/npx；`zotero/node_modules` 已装。
- **变换方法** — `npm run build` 产出 `.scaffold/build/addon` → 写 `<profile>/extensions/<addonID>` 指针文件 → seed `user.js`（**`xpinstall.signatures.required=false` 是硬需求**，缺它无签名代理包被静默拒载）→ setsid 起 xvfb 实例。
- **资源约束** — profile 必须落在 `TEXLATE_DEV_ROOT` 下（guard 断言）；启动断言 RDP 端口空闲；绝不裸起 zotero（`--profile` 写死命令行，裸起会开用户真实库）；stop 只杀 pidfile 进程组。
- **验证证据** — wait 死线内 rdp eval `Zotero.version` + 三层插件探针（`getAllPluginIDs` 注册态 × `Zotero.texlate.data.initialized` 运行态）；探针 ~8s 不绿自动 `installTemporaryAddon` 热装兜底一次（冷扫描漏注册的实测恢复路径）；未加载自动附 extensions 目录清单 + extensions.json + 日志 addon 行归因。
- **用法** — `dev-zotero [run|build|install|start|stop|restart|status|wait|verify]`（缺省 run：build+install+start+wait 全链）。

### rdp / rdp.mjs

- **适用条件** — 实例带 `--start-debugger-server <port>` 启动；profile `user.js` 开 `devtools.debugger.remote-enabled` + `prompt-connection=false`（dev-zotero/dev-profile 已 seed）。
- **变换方法** — 裸 TCP 长度前缀帧：root greeting → `listProcesses` → parent `getTarget` → `consoleActor.evaluateJSAsync`；async 结果写 globalThis 槽、第二个 eval 轮询读回；表达式形态 SyntaxError 自动退化语句体。
- **资源约束** — 服务端事件噪音按 `type`/`resultID` 过滤；超长字符串走 `longString` grip + `substring` 取全文；deadline 兜底防用户代码阻塞。
- **验证证据** — 实跑输出与坑清单见 `research/rdp.md`；exit 0 成功 / 1 eval 异常或超时 / 2 连接失败。
- **用法** — `rdp [--port 6100] [--timeout 30] '<js>'` → stdout `{"ok":true,"value":…}`。

### dev-verify

- **适用条件** — dev-server/dev-zotero/rdp 三件套就位；fixture 由 dev-profile 注入（脚本按 `[texlate-fixture]` 标题重发现并分类，不信固定 id）；`uv sync --extra server` + tectonic 同 dev-server。
- **变换方法** — dev-server run 起 mock 服 → dev-zotero verify 断言插件 loaded → rdp 写 serverUrl/pollInterval/pollTimeout prefs（global 位——裸 set 只写 profile 支，默认值 8765 仍生效）→ reset 清 fixture 的 `texlate:` 标记与 TeXlate 附件（幂等前提）→ 逐 fixture `api.selftest(id)` 断言 extract 源与 ID 形态 → 负例 `selftestNonArxiv` → `computeMenuState` 三态 → xpi 解包校验 manifest strict_min/max → 幂等重跑。sabotage 档见下节。
- **资源约束** — scratch 全在 `TEXLATE_DEV_ROOT`（`selftest-*.json` 原始证据、`.sabotaged` 暂挪文件）；reset 只碰 `[texlate-fixture]` 条目；selftest 死线 `TEXLATE_DEV_SELFTEST_TIMEOUT`（默认 420s）；full 档 ~5–15min（真实 arXiv+tectonic，prefer=reuse 使已译 id 秒回）。
- **验证证据** — 每条 PASS 行带 taskId/sha256 前缀/bytes/itemID/source=；原始 SelftestResult JSON 落 `tmp/zotero-dev/selftest-*.json`；入库 transcript 在 `zotero/dev/dev-verify-report.txt`（tmp/ 下同名是最近工作副本）。
- **用法** — `dev-verify [full|quick|sabotage]`（缺省 full，无其他 flag）。full=全矩阵（协议 e2e + 插件加载 + 6 fixture + 负例 + 菜单态 + xpi + 幂等重跑）；quick=协议 e2e + 插件加载 + 1 fixture + 负例 + 菜单态 + xpi；sabotage=三例破坏测验。退出码只计真失败——sabotage 的期望 FAIL 不影响 exit。

## 一次完整验证会话

```bash
zotero/dev/dev-server start        # 真 texlate mock 实例 → :18765（check 可复验）
zotero/dev/dev-profile create      # 隔离 profile + xvfb 实例 + 7 条 fixture
zotero/dev/dev-zotero run          # build→install→start→wait 全链（插件 loaded 才过）
zotero/dev/dev-verify full         # selftest 矩阵终验
```

`dev-verify` 自身会拉起/复用 dev-server 与 dev-zotero——上面前三步是手动分解（排障时逐层环回用），只想拿结论时 `dev-verify full` 一条命令即可。

收尾：`dev-zotero stop` + `dev-server stop`（各只杀自己 pidfile 记的进程组）；`dev-profile clean` 连 profile/datadir 一起清。

单独环回：`dev-server check`（服务协议面）、`dev-profile verify`（fixture 面）、`dev-zotero verify`（插件装载面）——三层各自可归因，不必全链重跑。

## 破坏测试

`dev-verify sabotage` 验证的是验证链本身：三例人为破坏各要求失败落在预期步且 detail 可归因——(a) 停 dev-server → selftest 必须 FAIL 于 `health`（unreachable/connection）；(b) serverUrl 改指死端口 127.0.0.1:19999 → FAIL 于 `health`；(c) 挪走 `tasks/<id>/zh.pdf` → FAIL 于 `download+attach` 且点名 kind `zh.pdf`。每例后自动恢复并复验转绿；期望 FAIL 原样打印但不计入退出码——exit 非零只意味着「破坏没生效」或「恢复失败」。失败位置不对即视为 sabotage 无效——三性质里「局部可归因」由此得到受控对照证据。

## 端口 / 路径

| 项                 | 值                            | 说明                                                                                                                                                      |
| ------------------ | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| texlate dev server | `127.0.0.1:18765`             | `TEXLATE_DEV_PORT`；**8765 是禁区**——本机真实 gateway 实例，8766 被 status_panel 长占；bind 前 `texlate_dev_port_free` 断言 + health `.data_dir` 验明正身 |
| RDP 调试口         | `127.0.0.1:6100`              | `TEXLATE_DEV_RDP_PORT`；`--start-debugger-server` 端口，绑定前同样断言空闲                                                                                |
| scratch 根         | `tmp/zotero-dev/`             | `TEXLATE_DEV_ROOT`，gitignored；pidfile/log/fixture/下载物全在此                                                                                          |
| texlate 数据       | `tmp/zotero-dev/texlate-data` | `TEXLATE_DEV_DATA`，与 `~/.texlate` 正式库隔离（service.lock 不打架）                                                                                     |
| Zotero profile     | `tmp/zotero-dev/rdp-profile`  | `TEXLATE_DEV_PROFILE`；rdp-spike 初始化的 canonical profile                                                                                               |
| Zotero 数据库      | `tmp/zotero-dev/zotero-data`  | `TEXLATE_DEV_ZDATA`；`-datadir` 指定，不带会开 `~/Zotero` 真库                                                                                            |
| Zotero 二进制      | `/usr/bin/zotero`             | `ZOTERO_BIN` 可覆盖                                                                                                                                       |

## research/

- `research/rdp.md` — RDP 通道 spike 实记：actor 链逐包、async 结果 globalThis 槽轮询、踩过的死胡同。
- `research/scaffold-mechanics.md` — zotero-plugin-scaffold 0.8.x 源码实测：serve/test/build 全机制、指针文件安装、锐边清单（`pkill -9 zotero`、裸 `no-remote` 参数 bug 等）。
