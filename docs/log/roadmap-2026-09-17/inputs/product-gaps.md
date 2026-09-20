# 产品面侦察输入（roadmap-2026-09-17）

> **结论**：产品侦察：hjfy 对标大体实装且含超额项；共享缓存分发层与匿名已译浏览结构性缺席是两大缺口。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）

> 只读侦察，2026-09-17。口径：「所有 arXiv 论文干净翻译」终极目标下的产品/功能/运维差距。规格基准：`docs/research/product/hjfy-site.md`（hjfy 对照）、`docs/research/product/web-layer.md`（下称 WL §x.y）、`docs/research/product/shared-cache.md`、`docs/03-roadmap.md` M3/M4 行、`docs/05`、`docs/06-08` 终稿。前端轴已有同批 `frontend.md`，本文只引其结论不重复。同日另有 `bench/results/m3gap-scout-2026-09-17/report.md` 做 M3 验收行对账（部分结论已被当日提交推前——`arxiv_html` 链 `ebf462a`/`6914391` 落地后其 G1「HTML 降级链」名义缺口已换形态闭合，见 §1.2）。

## 1. 功能清单对账：hjfy 复刻面 vs 实装

### 1.1 已实装（含 hjfy 没有的超额项）

- **任务模型**：11 态机 + ACTIVE/TERMINAL 分集（`server/store.py:150-163`），`recover_startup` 启动分流 interrupted/needs_auth（`store.py:502-537`）——覆盖并细化了 hjfy 五态 + fault 语义（`hjfy-site.md:115`）。
- **任务 API 面**：translate（`app.py:854`，cache_key dedup/reuse + 409 `duplicate_active`）、task GET/SSE（`app.py:913`，Last-Event-ID 重放 `app.py:930`）、files（`app.py:942/957`）、upload（`app.py:1057`，80MB/300MB 双闸 `settings.py:54-55`）、tasks 列表（`app.py:1339`）、cancel/retry/DELETE（`app.py:1376/1403/1470`）、reader + position（`app.py:1497/1555`）、settings + test + providers（`app.py:1581-1658`）。`texlate run --server` 瘦客户端全链（`cli.py:488`+）。
- **BYOK 四级入口**：header > settings(0600/connections.json 分槽) > env > CLI configure（`settings.py:612-656`），tenant = `k_+sha256(key+salt)[:12]`（`settings.py:602-609`），四层不落日志防线全在（RedactFilter `settings.py:527` 区）。
- **术语表**：三级 + ph 恒等注入 + 文档级过滤烤进 system prompt（`xlat/glossary.py:1-30`）；`options.glossary`/`glossary_dir` 贯通 API→worker（`app.py:799-804`）；Home 选项格暴露（`web/src/pages/Home.tsx:42,89`）。
- **上传四类**：tex-zip/pdf/docx/epub 魔数路由（`app.py:1059` + `upload.py`）；pdf 走 babeldoc sidecar（`server/babeldoc.py`，scanned_pdf 检测 `babeldoc.py:560-563`），docx/epub 走 `export/` 双语插译 + `_run_doc`——**hjfy 只宣传未交付的 Word/Epub 这里已有**。
- **取源降级链**：e-print 主链 + **`arxiv_html` 链已落地**（`app.py:885` `source=html` → `worker/html.py` fetch→DOM chunk→translate→zh.html/dual.json；前端 `optSource` 选择器 `Home.tsx:48,100`）+ BabelDOC pdf 臂，三级齐全。
- **分享**：`.share.zip` pack/import（`share.py`，`POST /api/share/import` `app.py:1115`、`POST /api/task/{id}/share/pack` `app.py:1210`、CLI `share pack/unpack` `cli.py:1127/1233`）；arxiv 任务 parse 后先查本地共享 index 隐式命中（`worker/core.py:186-202`），零 token 对账回灌（`worker/share.py:162-205`）。
- **缓存三层**：src-cache 源级（`arxiv/cache.py`）+ cache_key 产物级 reuse（`store.py:367-384`，跨租户内容寻址，`per_key` 可切 `settings.py:112-115`）+ translation_cache 段级（`store.py:802-816`）。
- **用量账**：`task_usage` upsert 聚合（`store.py:673-714`）→ done 帧 stats + Reader 统计行（`web/src/taskStats.ts:1-30`）。
- **目标语言**：`TARGET_LANGS={zh-CN,zh-TW,en}`（`settings.py:59`）三档，API/设置/表单全通——hjfy 只 zh_CN。
- **分发/部署**：`Dockerfile` multi-stage（web 构建 → tectonic musl sha256 钉 → py3.12-slim + noto-cjk），`release.yml` wheel+ghcr 推送 + 容器冒烟；`texlate web` service.lock 单实例 + 已运行则开浏览器（`cli.py:712-816`）；`tools install-tectonic` 五平台矩阵；`doctor` 全链自检（`cli.py:1612`）。

### 1.2 规格承诺但未实装 / 设计分叉

- **社区共享缓存的分发层缺席**：`shared-cache.md` §0「服务端 v1 = 任意静态托管 + index.jsonl」仍是纸面——`share_dir` 纯本地目录（`settings.py:122-129`），`index_lookup` 只读本机 `index.jsonl`（`app.py:1275`），**无远端 index 拉取、无 HTTP 端点 serve 共享包、无上传通道**；隐式命中（`worker/core.py:195`）只能撞自己 pack 过的包。「别人的付费产出可复用」目前只有人肉传文件一条路。
- **匿名已译浏览（hjfy 核心体验）结构性缺席**：server 形态 mutation 无 `X-Texlate-Key` 一律 401（`app.py:589-594`），读面全部 tenant 过滤（`_get_task` `app.py:676`）；匿名者 tenant = 空 key 指纹，看不到任何人的任务。hjfy「已译论文匿名随便看」（`hjfy-site.md:7`）在 texlate 无对应物——reuse 命中虽跨租户（`store.py:377` 无 tenant 谓词），但匿名者连创建任务的资格都没有，命中无从谈起。
- **Redis 队列后端**：`REDIS_URL` 规格留位（`web-layer.md:275,589`、Dockerfile:84-85 注释自认「尚未实现」），代码零命中——单进程 asyncio.Queue（`worker/runner.py:51`）。
- **`POST /retry{model}` 升级重翻**：规格写的 retry 换模型被实装显式否决（`app.py` retry 注释口径：model/target_lang 是 cache_key 成员、换值须新建——m3gap-scout G3 同判）。功能等价（新任务+dedup）但无「换更强模型重翻」产品化入口（hjfy 的「翻译可读性差→换 DeepSeek 重翻」`hjfy-site.md:35,118`）。
- **用户系统/登录**：hjfy 微信 + 手机号双登录（`hjfy-site.md:25`）——texlate 有意不走账号体系（BYOK 本地优先 + key 指纹租户），这不是缺陷而是形态差异，但意味着「托管公开实例 + 配额收费」的 hjfy 商业形态不在当前产品面内（配额只有总量闸 `quota_max_tasks/bytes`，`app.py:719-747`——无 hjfy 式「每日 100 篇」时间窗限速）。
- **反馈通道**：hjfy `errorFeedback` + 错误类型下拉（`hjfy-site.md:35`）——texlate 无任何 feedback 端点/UI；失败样例回流 fixloop 规则库靠本机沉淀（docs/08 §5.5），用户侧「翻译有问题？」入口缺失。
- **上传→arXiv 去重**：hjfy 上传命中已译论文 302 直跳（`hjfy-site.md:95`）——texlate upload 路恒 `prefer=fresh`（`Home.tsx:149` 注释），无 PDF→arxiv 匹配。
- **失败任务定期重修**：hjfy 承诺「定期检查失败任务并修复」（`hjfy-site.md:79`）——texlate 只有手动 retry（`RETRYABLE_FROM` `store.py:161`），无调度器。
- **前端对照债**（详见 `frontend.md` §2/§3，仅列名）：任务列表无「继续」钮、`?status=` 有 API 无 UI、swapped/标题/默认视图三处 hjfy 行为差、无拖拽上传/示例论文、无暗色、SSE 扇出无界、Reader.tsx 1005 行单文件、首屏 1069KB。
- **术语表种子覆盖偏科**：`xlat/terms/index.yaml` 只映射 cs.LG/RO/ML/AI/CV + stat.ML/eess.AS 两个别名——math/physics/cond-mat/hep 等全落 `default.csv`；「所有 arXiv」口径下领域覆盖是显性缺口。
- **desktop/pay**：hjfy `/desktop` 是占位 stub、pay 未启用（`hjfy-site.md:48-49`）——texlate Electron 桌面版同属 M4+ 未启动（`03-roadmap.md:48`），对齐面互相都不欠。

## 2. 可靠性 / 运维面差距

- **管线全局串行**：`TaskRunner._dispatch_loop` 单 `_current` 槽逐任务消费（`runner.py:131-175`）——同时只有 1 个任务在跑（任务内 chunk 并发 `concurrency` 1–16 `app.py:425`）。本地单机合理，但「所有 arXiv」批量预译口径下是吞吐天花板；`GET /api/tasks` 全表返回无分页（`store.py:350-365` 无 LIMIT，`app.py:1339`），队列/列表规模上去后前后端双殁。
- **默认网关是私有 内网 地址**：`DEFAULT_BASE_URL = "http://127.0.0.1:<内部网关端口>"`（`xlat/client.py:51`）硬编码进包——对作者 内网 外任何人等于开箱即死；对作者自身也是单点（无 failover 链、无多网关轮询，故障只有 `gw-health.sh` 外部脚本）。providers 预设（`settings.py:856-893`）有 gateway/deepseek/openai/anthropic/qwen/custom 六档，但**首启没有任何引导**——新用户第一反应是任务全挂。
- **存储无治理**：`tasks/{id}/`（src 树 + build-en/build-zh + 产物）、`src-cache/`、`share/`、`translation_cache`、`task_events`（每任务 cap 2000 但任务数无界）全部只增不减；唯一回收是手动 `DELETE /api/task/{id}`（`app.py:1470`，行级联 + rmtree）；CLI 无 gc/prune/clean 子命令，settings 无 retention/TTL 字段。「跑过即永存」对单机 hoarder 尚可，对批量预译是磁盘炸弹。
- **部署件薄**：有 Dockerfile + release.yml 推 ghcr（单架 amd64，`release.yml:74-75` 注释自认 multi-arch 未做）；**无 docker-compose、无 systemd unit、无反代样例**——`TEXLATE_MODE=server` 的正式部署全靠用户自己拼（`web-layer.md:589` 只写了环境变量面）。`texlate:full` xelatex 变体只是 Dockerfile:11-16 的注释段落，不是发布 tag——容器默认只有 tectonic，xelatex 高成功率档要用户自己改镜像。
- **babeldoc 不进镜像**：AGPL 进程边界 + 2GB（Dockerfile:75-76 注释）——容器形态 PDF 上传通路直接缺席，`health` 的 compilers.babeldoc 恒不可用，需手动挂宿主二进制。
- **配额模型不匹配 hjfy**：只有租户总量闸（任务数/字节），无时间窗；BYOK 下用户自付 token 所以单日限速意义不大，但公共部署（若做）需要它。
- **本地 CLI 主命令是 mock**：`texlate run` 本地模恒 `MockTranslator`（`cli.py:359-362`、`e2e.py:3`）——真翻译只有 `web`/`--server`/`export` 三条路；`run` 本地模式实为「编译链验证器」。对 CLI 优先用户这是名不副实的坑位（`export` 反而默认真翻 `_export_translator` `cli.py:878`——行为不对称）。
- **多实例/水平扩展零路径**：单写者 SQLite + 进程内队列 + flock 单实例——`REDIS_URL` 未实现前 server 形态就是单副本。

## 3. 排序建议（按用户可见价值 × 对终目标的杠杆）

1. **共享缓存分发层（M，~3–5 天）**：`index.jsonl` 远端拉取 + 共享包 HTTP fetch（复用 `unpack_share`/`share_pack_publish` 现成机械面）+ 可选公共 registry 端点（静态托管即可，shared-cache.md §0 已定形）。这是「1 万篇预译秒回」的 hjfy 对等武器——BYOK 下唯一能摊薄社区 token 成本的结构，也是「所有 arXiv」最省钱的实现路径：预译者跑一次，后来者零成本。
2. **批量承载底板（M，~2–4 天）**：a) `tasks` 列表分页 + `?status=` 已有半拉子；b) `GET /api/tasks` SSE 聚合流或前端收敛（frontend.md 建议 1 同向）；c) 任务 TTL/GC：`settings.retention_days` + `texlate gc` + 启动期懒清理（tasks/{id}/ 与 files 行两层）；d) translation_cache 上限/LRU。没有这层，预译灌进几百篇后列表、磁盘、SSE 三面同时塌方。
3. **首启可用性 + 公网分发收口（S–M，~1–3 天）**：a) 默认 base_url 指向私有 内网 地址必须改——首个 `translate` 409/未配置 → UI 引导 Settings（或 `texlate web` 首启检测无 key 弹配置页）；b) providers 预设加「自带 OpenAI 兼容端点」外的免费档说明；c) 补 systemd unit + compose 样例 + `texlate:full` 真发 tag（Dockerfile 注释段转正）。不修这条，开源发布 = 只发布给作者自己。
4. **质量反馈/升级闭环（S–M，~1–2 天）**：`POST /api/task/{id}/feedback`（错误类型枚举 + 文本，落 `task_events`/新表）+ Reader「换模型重翻」按钮（= 新建任务预填 model，dedup 语义天然兼容）——hjfy isDeepSeek 双轨的产品化等效件，且反馈数据是 fixloop 规则与 prompt 迭代的取数口。
5. **领域术语表扩面（S，~1 天 + 内容活）**：`terms/index.yaml` 从 cs-only 扩到 math._/physics/hep-_/cond-mat/q-bio 高频 category——LaTeXTrans 种子之外的表需要新源（可社区贡献），对「所有 arXiv」的译文质量是广谱收益。

次优先（已被 frontend.md/其他轴覆盖，不重复立项）：SSE 扇出收敛、列表「继续」钮、暗色主题、Reader 拆分（frontend.md §6 三条）；Redis 队列（m3gap G2，裁决先行）；`run` 本地真翻入口（CLI 补 `--live` 走 settings 决议，~0.5 天，可与建议 3 捆绑）。

## 4. 风险注记

- 所有「实装」判定为代码静态核实（文件/接线/测试在案），未逐项起服复测；m3gap-scout 同口径提醒其「已闭合」亦建议一轮全链冒烟坐实。
- 「所有 arXiv」预译成本粗估缺失：产品面没有任务级成本预算器（usage 有记录但无预估入口），批量灌库前建议先出成本模型（bench 侧 `cost-model` 有 ~68% prompt 摊销锚点可引）。
