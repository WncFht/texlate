# arXiv CS+math 日更全量抓取 + 15 天 soak 设计（2026-09-19）

> **结论**：以 `rss.arxiv.org/rss/{archive}` 公告日全量枚举为主通道（一次拉取即得 id+ 版本 + 类目+announce_type+license 全部字段），cs+math 并集去重后 **new+cross = 1192 篇/日**、replace 系 592 篇/日（默认不抓）；公告即抓零时滞。枚举→钉版 fetch→stagerun 五 stage 的重喂架构已跑通，绕路成本 ≈ 一行 env 重定向。
> **状态**：**已退役（2026-09-21）**——`daily-soak.timer`、`scripts/daily-soak.sh`、`bench/py/corpus/daily_arxiv.py` 全删、`corpus_daily` 语料区废弃（见 `../../dev/automation.md` §1）；语料扩展转向钉版重建。本文留作 RSS 枚举通道的实测取证：枚举层结论（公告日批、字段完备、公告历行为）仍有效，RSS 条数等为 2026-09-18 公告日口径时点数据。
> **日期**：2026-09-19 设计定稿，2026-09-20 重订入库

前置文档：[2026-09-19-scale-roadmap.md](2026-09-19-scale-roadmap.md)（缺口 2「无增量通道」即本文所解）、[oai-pmh.md](oai-pmh.md)、[layer.md](layer.md)。

## 1. 枚举层实测结论（RSS 为主通道）

`rss.arxiv.org/rss/{archive}` 按**公告日**给出全量条目，一次拉取即得枚举所需全部字段，无需补充元数据调用。2026-09-18（周五公告日）实测：

| 频道      | 总条目 | new | cross | replace | replace-cross |
| --------- | ------ | --- | ----- | ------- | ------------- |
| /rss/cs   | 1205   | 748 | 78    | 333     | 46            |
| /rss/math | 723    | 396 | 57    | 231     | 39            |

- **item 字段全齐**：`guid = oai:arXiv.org:{id}v{N}`（带版本）、`<category>` 列出全部类目（主 + 副）、`announce_type` 四值、`dc:rights` 许可、`dc:creator` 作者、标题 + 摘要。v1 ⇔ new/cross，v2+ ⇔ replace/replace-cross（实测 825v1 = 826 new+cross，误差 1 为计数粒度）。
- **cs+math 并集去重后：new+cross = 1192 篇/日**，replace 系 592 篇/日（版本更新，默认不抓，可开关）。并集横跨 116 个类目——primary 在别库、cross 进 cs/math 的论文也计入（正是「相关」语义）。
- **公告节奏**：feed 的 `pubDate` 是公告日（美东）；周六日无公告，feed 冻结在周五批次——**批次身份用 pubDate 而非本机日期**，重跑幂等。周一公告覆盖五六日三日投稿 → ~3 倍量（估 ~3500）。
- **对照面**：`/list/cs/new` 显示 new 748 / cross 73 / replace 379（replace-cross 并入）——与 RSS 差 5 篇，因 listing 是**实时页**（版主事后改类会漂移）而 RSS 是公告时刻冻结快照；`/list/cs/pastweek?skip=N` 按公告日分页（实测 Friday 826 = RSS new+cross 口径），覆盖最近 ~5 个公告日，是 ≤1 周漏跑的**回填通道**。
- **对账面**：OAI-PMH `ListIdentifiers&set=cs&from=D&until=D` 同日返回 1271 条（含元数据变更 churn，是公告集超集），适合做周度对账与 >1 周回填；deletedRecord 墓碑同步给出撤稿感知。
- **src 可抓时点**：公告即抓——`/e-print/{id}` 301 → `/src/{id}`，周五新论文实测 GET 379KB/0.9s，零时滞。

## 2. 部署环境网络约束（实测约束）

部署机直连 arxiv.org TLS 握手即被重置（SNI 特征阻断），**必须走本机 HTTP 代理出口**；代理订阅刷新期间会出现分钟级全线失败（实测多站同时 TLS reset、境内站直连正常）。含义：日更任务必须**前置代理健康检查**（探测 rss.arxiv.org 200 才启动），失败即中止报警，避免空跑消耗配额。

## 2.5 官方许可语义与生态深挖（现场调研结论摘要）

- **export.arxiv.org 是官方指定抓取站**：bulk-data 文档明示 "users intent on harvesting use the dedicated site export.arxiv.org… specifically set aside for programmatic access"，且白纸黑字允许 "play catch-up programmatically between updates of the buckets"——日增量直采落在官方许可语义内[^arxiv-bulk]。抓取主机因此定为 **export 主站、www 转移备份**（robots.txt 的 /src disallow 针对通用爬虫，export 本身是豁免通道）。
- **官方速率口径 = 4 req/s 突发 + 1s sleep**（≈2 req/s 有效），比惯例 1req/3s 宽 6 倍；仍用 3.05s 串行——~1200 篇 ≈ 2h 足够，保守速率避免触发封禁。
- **封禁机制实测面**：403 → `arxiv.org/denied.html`（机器人检测，同出口 IP 连坐），arxiv-sanity 运维实证 ~1200 篇后全站 403、**~20min 自动解封**[^sanity-issue80]；2026-02 起新增系统级 "rate exceeded" 429（合规速率同样触发，官方已扩容）；**GET 走 Fastly 缓存、POST 绕缓存直触限流器**——保持纯 GET/HEAD。对策：ratelimit 断路器已扩 403→挂起（30min 起步恰覆盖自解窗）。
- **公告历**：Sun–Thu 20:00 ET 公告（Fri/Sat 永不）；提交窗 Thu14:00→Fri14:00 归 Sun 20:00 公告、Fri14:00→Mon14:00 归 Mon 20:00——周一批次含三天积压 ≈ 2-3×。RSS 每天 midnight ET 刷新、非公告日返空骨架。
- **生态普查**：源码级爬虫少而精——公开项目里有被封后免费代理轮换 + `--diff` 续传的抓取器、OAI sync+fetch 入 SQLite 的工具、Kaggle+GCS+S3 多源采集器、日更 LaTeX 源管线，以及 **15 万篇原始 e-print tar.gz（285GB）公开发布在 HF 的先例——单端点爬取可行性的外部证据**；日更 bot 群全部只抓元数据。镜像面：存在可用的 Caddy 反代实例（/list 全通、e-print 301 回源），cn.arxiv.org 已失效，Common Crawl 与 Wayback 对 /src、/e-print 零覆盖（礼貌爬虫守 robots）——**无可用公开旁路，直采是唯一解**。
- **数据集面**：S2ORC 增量 release（LaTeX 子集是处理后文本非原始源）、unarXive-2024 2.28M JSONL、提取文本型数据集——全是处理后产物；要原始源包只有 S3 月块 + 直采两条路（对照 [bulk-channels.md](bulk-channels.md)）。

## 3. 架构（新代码最小化，重喂 stagerun）

```
RSS cs+math ──> daily_arxiv.py enum ──> work_daily/enum-{date}.jsonl
                                       corpus_daily/manifest_{date}.jsonl
                daily_arxiv.py fetch ──> acquire_source(钉版) ──> corpus_daily/{id}/{meta.json,raw.*,extracted/}
                                       work_daily/fetch-{date}.jsonl（逐篇 status）
TEXLATE_CORPUS=bench/corpus_daily stagerun ingest --layers {date}
   → parse → xlat(mock 全量 + real 抽样子集) → compile zh/base → fixloop → 日报
```

- **枚举 `enum`**：拉两频道 RSS → 解析 → 按 base id 并集去重 → 写 `corpus_daily/manifest_{announce_date}.jsonl`（行含 id/layer=日期/cat_group=主类 archive 前缀/cats/announce_type/license/ver/yymm/channel=arxiv_eprint）。已有该日期 manifest 则跳过（幂等）。
- **取源 `fetch`**：对 manifest 行（默认 type ∈ new,cross）调 `acquire_source(version=ver)`——RSS guid 自带钉版，跳过版本解析；`RatePolicy(daily_budget=8000)` 覆盖默认 180（实测日需 ~2400 发、周一 ~8000）；限速沿用 GAP 3.05s 单连接——1200 篇 ≈ 2h、周一峰 ≈ 6h，隔夜窗口足够，**不引入并发**（WAF 生存优先）。pdf_only/withdrawn/error 记 status 不物化（pdf_only 本期不做，只统计）。OK 条目从钉版缓存拷 `extracted/` 入 corpus_daily。
- **回填**：漏跑 ≤1 周走 `/list/cs/pastweek?skip=`、`/list/math/pastweek`；>1 周走 OAI set 日窗（v1 过滤靠 ListRecords arXivRaw 版本史）。enum 对「上次成功批次 → 今日」缺口告警。
- **stagerun 接入**：corpus 根改 `TEXLATE_CORPUS` env 一行——日更语料与钉版语料物理隔离，stagerun 五 stage/records 账/resume/判分全原样复用。`--layers 2026-09-18` 即逐日单元；多日并集逗号并列。
- **管线量**：fetch 全量 ~1200/日过 parse+mock-xlat+compile+fixloop（xlat mock 臂零成本定翻译形；主要暴露面在 parse/compile/fixloop）；**real 臂抽 ~40 篇/日**过真网关（配额约束，全量不现实）。
- **调度**：`daily-soak.sh` 幂等编排（enum→fetch→stagerun 五 stage→日报），systemd 定时器每日 02:30 UTC 起跑（公告 20:00 ET 后 ~1.5h 余量）；长任务纪律照旧 setsid nohup + run.log + 文件面监控。周末定时器照跑——enum 命中已有批次即即时退出。

## 4. 容量与成本

- 15 天 ≈ 18-20k 篇新论文；raw+extracted ~3.5MB/篇 → ~60-70GB（bench 数据惯例 gitignored，大物可移远端容量节点）。
- 编译臂：~1200 篇 × ~60s xelatex ÷ 8 workers ≈ 2.5h/日（base 臂另计）——隔夜可消化；周一峰拉长，records 账天然跨日续跑。
- 网关：real 臂 40 篇/日 × ~200 chunks ≈ 8k 调用/日，配额内；全量 real 翻译 ~24 万调用/日，明确不做。

## 5. 风险与未决

- RSS 频道无历史日期参数——**漏跑即丢枚举**，靠 pastweek/OAI 补；故 enum 必须每日必达，定时器 + 缺口告警是硬要求。
- 代理出口是单点：健康检查只保证「启动时活着」，运行中死亡由 ratelimit 断路器 + 挂起承接（下次调度续跑），长期稳定性观察中；必要时整体迁往直连通畅的远端节点。
- replace 系默认不抓——v2+ 源码更新对「新论文 soak」价值低且放量 50%；若想测版本漂移再开 `--include-replace`。

### 参考文献

[^arxiv-bulk]: arXiv. Bulk Data Access——export.arxiv.org 为指定抓取站、"play catch-up between bucket updates" 明示许可。info.arxiv.org. [help/bulk_data](https://info.arxiv.org/help/bulk_data.html)

[^sanity-issue80]: arxiv-sanity 运维报告——~1200 篇连续抓取后全站 403 denied.html，~20min 自动解封。GitHub. [karpathy/arxiv-sanity-preserver#80](https://github.com/karpathy/arxiv-sanity-preserver/issues/80)
