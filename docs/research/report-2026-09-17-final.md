# TeXlate 现状终报 —— 2026-09-17 车队作战全天收线

> 面向用户的综合报告。配套文档：排期与八轴侦察明细在 `docs/research/roadmap-2026-09-17/ROADMAP.md`（含 `inputs/` 八份只读侦察）；逐条决策与落地台账在 `docs/research/overseer-2026-09-16.md`。本文数字以落笔时点（~21:00）records/scorecard 实测为准；仍标记「在飞」的项会在收线后由台账续记。

## 0. 一页结论

**管线已实质可用且今日大幅推进**。5,124 格语料面：pdf **97.89%**、clean **84.99%**；end-state 口径 M1-B 波 72/72 全出 PDF。全天 526 commits：P0 清零（xlat batch 非锚定错配修复）、一次 ReDoS 急性事故当日内「发现→py-spy 钉栈→原子组修复→补波闭环」全程走通、vendored_fetch 机制把 492 格全 fail 面打到 73.2% clean、strict-xfail 全仓清零、pytest 全量 3:46 全绿。

**今日验证的最重要的方法论闭环**：「机制归因 → 资产化 → 重跑」流水线真实有效——C-bucket 波证明 offline-vendored 资产能把整片 fail 区系统性翻转；illegal_unit 波证明 segmenter 修法 + 深链重跑能把一族残面清零；这两套动作已固化成可复用的波次 runbook。

**距终目标（所有 arXiv 干净翻译）的主要矛盾**（按杠杆排序）：

1. **real 臂证据窗口 ~29 天**（swe-2-medium promo 2026-10-16 到期，实测 40–72 格/h）——免费额度内能拿的真模型回归面有限，须探针化优先打 hot/expand 缺口（排期 S1）。
2. **共享缓存只有本地 pack**——「1 万篇预译秒回」的远端分发层缺席，是终目标最省钱路径的缺口（M1，3–5d）。
3. **网关翻译 = 单篇墙钟 96.8%**——server concurrency=3 vs 管线 10 是现成 ~3× 旋钮，但 BYOK 限流语义**需用户裁决**（决策点 1）。
4. **测量面残余失真**已修大半（dur_s 伪影/taxonomy 零消费/same-status 盲区/rules_fired 物化均今日落地），余 scorecard union 口径名实不符 + csb 校验是 status 等值（S2）。
5. **fixloop 规则面**是 scout 面 P1 最密归属（peer1 占 6/14），残余机制 11 件 orphan 待立规。

## 1. 今日战果

### 1.1 波次总账（全部收线）

| 波                     | 规模                                        | 结果                                                                                                                        |
| ---------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| C-bucket vendored-shim | 492 格（全 fail 起点）                      | **clean 360（73.2%）/ partial 127 / fail 5**；scorecard pdf +24 / clean +101                                                |
| illegal_unit 深链      | 108 id                                      | **108/108 闭环**：96c/6p/0f + held6 直出 6 clean，零回归，unfixable 清零                                                    |
| M1-B 判别波            | 72 格（T1 58 arg-eaten + T2 14 math-eaten） | **72/72 全出 PDF**，fixloop 终态 c53/p19/f0；残余 19 格分簇路由                                                             |
| n200 real 臂           | 200 id                                      | union pdf 98.5%，real≈mock 打平，fixloop 救回 23/24                                                                         |
| S6 base 臂             | 5,122 格                                    | **收线**（records `97d30b0`）：base clean 3,064/partial 1,045/fail 885/reject 65/skip 63——build-base 覆盖 0→全 + 源健康基线 |

### 1.2 重大修复（按影响排序）

- **P0：xlat batch 非锚定错配** `164a9e0` —— 非锚定 `[n]` 解析整体撤除 + `@@` 泄漏闸 + EOL 归一 + slot 字符拒，同批核销 4 个 P1。译文静默错配进成品的通道封死。
- **ReDoS 急性事故** `746237f` —— `_WS_NOPAR` 的 `%[^\n]*` 变长片在外层 `(?:…)*` 下对 `%%%%` 横幅注释串产生 2^N 回溯爆炸（老论文头部高发形）。py-spy 三采样零位移钉栈定位；修法=原子组化（三选一首字符互斥，语义不变）+ 512B 匹配窗帽 + cs 臂边界前瞻。held6 六格从 30min+ 卡死到 <0.1s。**连带着翻了 pytest「OOM」旧案**：此前 48min 卡死实为套件自身吃同病灶，修后全量 3:46。
- **vendored_fetch 机制全链** `a90978a`/`7f1defd`/`1a74204` —— 23 件 off-CTAN 老期刊宏包入库 + round-0 scan_install vendored 兜底（穿透型缺件缝闭合：missing_file 非首错时轮级分类看不到的缺件现在静态预检期就落位）。
- **illegal_unit 段修** `d2c377b`+`1bbc4fb` —— 尾参扫四补面 + count 尾种 + ~50 寄存器名 + env argspec 20 条（varwidth/lrbox/numcases/textblock/listing 等）。
- **e2e↔worker 漂移 D 批** `f0a4041`/`abc2efd` —— probe_flags ctx 化、opt_bool 统一（**options 显式参数现在优先于 env**，语义翻转已在 ledger 登记）、baseline 快照接通 restore_support_from_src、_delivered 非空口径对齐。
- **测量面四件** `174790e`/`b2876d8`/`c4ff8fb` —— xlat dur_s t0 伪影修（99.6% 排队假象消除）、rules_fired+post.regressed 物化、rundiff `--deep` same-status churn 视图、dossier 改吃物化 taxonomy。
- **纵深硬化** `c50cf3a`/`9acced6`/`ac84ae6`/`b84f6fc`/`30866ea`/`1b6b023` —— run_process POSIX rlimits（AS 4GiB/NOFILE 1024/CPU 兜底）、share 扁平守卫并齐、_MODELS_CACHE FIFO64、ctan cache 归 data_root、redact 隔离、settings 存盘探针下事件循环。

### 1.3 产品面落地

- **G1 arxiv_html 三级取源全链** `9fab8bf`→`407f1db`→`ebf462a`→`792fd0d`→`6767726`：arxiv/html.py（40 真页 8956 块双射）+ worker emit 臂 + 前端 DomPane/source-select——LaTeXML 方案经 spike 否决（2.33GB 依赖全劣）。
- **EPUB/DOCX 双语插译**已实装（hjfy 未交付项，我们超额）。
- BYOK 三入口、offline 模式、health build 戳、models 探测告警等周边齐。

## 2. 关键数字

- **scorecard**（5,124 格）：pdf **97.89%** / clean **84.99%**（M1-B 归因迁移 fixloop+51/compile−47 非质量位移；illegal_unit 波净 +14，集内 +82 被并发波 csb stale-677 churn 对冲 68——波次调度碰撞面已立档）。
- **S6 源健康基线**（base 臂 5,122 格，`97d30b0`）：base clean 59.8%/fail 17.3%——其中 missing_file 占 92.1%（arXiv 老稿 tarball 自带缺件=**源级烂**非管线伤）；**管线引入致命伤仅 2/3,064 = 0.065%**（go/no-go「回归集→0」实质达成），降级 clean→partial 3.4%，下游 vendored+fixloop 救回 862/885=97.4%，真死格 ~23 成攻坚尾池。build-base 覆盖 97.5%。
- **墙钟分解**：xlat real 臂 ~24s/id inner；单篇 e2e 中位 77.7s 其中网关翻译 96.8%；compile 15.3s/id（xelatex 本体 94.7%）；fixloop 14s/行；parse 2.1s。
- **real 臂吞吐**：conc20 实测 90s/格 ≈ 40–72 格/h；server 侧 conc=3 ~260s/篇 vs 管线 conc=10 ~78s。
- **规模账**：corpus_v3 四层 5,133 篇；mechanisms.jsonl 144 条；frame.parquet 宇宙 3,164,528 行。
- **资源**：磁盘 corpus 20G + work 28G + results 45G，卷余 363G；e-print 通道 180/日硬限（bulk 通道无瓶颈）。
- **缺陷账**：P0 **清零** / P1 22→~14（今日核销 8+）/ P2 ~40；strict-xfail 全仓清零；pytest 全量 4946+ 全绿预期。
- **代码量**：src ~51.8k 行 py + web ~5.6k 行；rules.yaml 70+ 规则（39 已挂 mechanisms）。

## 3. 车队台账摘要（谁做了什么）

| lane                    | 今日主线                                                                                                    | 状态                                                                                |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1d（latex/segmenter）   | illegal_unit 修法 `d2c377b` + ReDoS `746237f` + NO_EXPAND env 化 + S9 env-arg 20 条 `1bbc4fb`               | M1-B 残余两簇在飞（illegal_unit 残漏 4 + syntax 重伤 3）                            |
| peer1（fixloop/rules）  | mechanisms 字段 `a9bcd5b`+`385493a`、TEXLATE_CACHE `b84f6fc`、scan_install vendored 兜底 `1a74204`          | M1-B stub 缺件 5 + 判据边界 3 在飞 → undefined_cs 48 格分解 + orphan 机制 11 件排队 |
| 1e（server/bench/xlat） | P0 batch 五钉 `164a9e0`、html-title `083cded`、docs/08 同步、env 规范化三件套、e2e drift D2/D3/D7 `abc2efd` | E2 下沉批（~500 行 → repair/）+ 5 fuzz agent 在飞                                   |
| e8（worker/e2e/repair） | C-bucket postmortem `6b75761`、dur_s t0 `174790e`、陈旧 pin×5 `99a4189`、D1/D5/D8 `f0a4041`                 | math--0408287 异常 + _build_dual zh 英文 P1 + COMPILE_TIMEOUT 接线在飞              |
| 2f（data/bench）        | C-bucket/illegal_unit/held6/M1-B 四波收官 + scorecard 链                                                    | S6 base 臂 5,122 格在飞（~1.5–2.5h）                                                |
| overseer fork×6         | i5a `b2876d8`、i5b `c4ff8fb`、i7 `7ac59c6`、export-pin `ea3402c`、sharepack `9acced6`、sandbox `c50cf3a`    | **全部交付核销**                                                                    |
| 4f（dense-feedback）    | dossier.py/mech_ids.py/mechanisms 字段/taxonomy 物化/verdict-proxy spec                                     | 已退出（自治 lane 结束）                                                            |

**纪律面**：车队铁律（teammate 零 git、overseer 统一 pathspec commit + --no-verify、交付=文件清单 + 建议 msg+ 测试证据、diff 逐 hunk 归因）运转中；两次自 commit 越矩（e8 `4ed297f`、1e 三件）均核净后收编并重申。

## 4. 在飞与残余清单（收线时点 ~21:30）

收线广播已发：各 lane 当前件到交付边界即停、不接新件；本节「已裁决未做」项全部转入 §5 排期。

**收线中**（最后一批交付）：

- 1d：**已落 `feb5046`**——M1-B 残余 7/7 格闭环（`_TAIL_OPERAND` 因子链文法 + arith/boxspec 两 kind + `\newX` 声明名 +12 + PiCTeX 域容忍；hep-ph-0104029 推回 stub/shim 道）
- peer1：**已落四件**（`8910a96` rules_declined 物化 / `69649ca` ell 条目 / `526932c` diagrams stub 富化实证 172→0 err / `be03326` routes 档）
- 1e：E2 迁移批**已落 `9539bcc`**（repair +430/e2e −397，19 符号下沉+D6 jail+`_ruleset_with_baseline` 单源化）+ glossary fuzz `59ddfb3`（17 xfail-strict 钉 9 CONFIRMED）；残余=client/engine/judge 三份 findings + client fuzz 文件
- 2f：S6 base 臂 **已收**（records `97d30b0` + 简报 `e0b3dff`——源健康基线数字见 §2）
- e8：**已全清**（`4ebfb12`/`ea4d0c4`/`b6d0ede`）

**已裁决未做（下梯次，进排期）**：

- peer1 序 3-5：font_cs_shim 新 builtin（fivmi 83-err，老 AMS 命名族普适）/ cs_rebind produced_by 子路径（§/ø TFM 产字）/ jinstpub stub（先盘点用量）；owrart.cls + `\bm`-CJK 守卫低值 backlog
- retry.py 七钉缺陷（1e fuzz 产出，**字节丢失类**）：`_split_lines_scoped` 丢尾随 `\t`/`\xa0` 空白尾片 / `_make_slots` 丢 >SLOT_MAX_CHARS 纯空白片 / `_best_split` cs↔`{arg}` 原子断缺 / `_slots_round` 结算读可变 group 误记 no-answer / `max_tries=0` "unreachable" 可达 + 象形括号 ⟦⟧《》/零宽-only 槽值（PLAUSIBLE）
- glossary 九钉缺陷（`59ddfb3`，xfail-strict）：**`_resolve_glossary_path` jail 逃逸族**——NUL→ValueError / ENAMETOOLONG→OSError / ELOOP 自环→RuntimeError 三类异常越狱（`options.glossary` 未校验用户输入经 app.py:876 可达，e-print tar 可植自环）；flatten_terms null 毒化（`en:~`→字面 "None" 进 prompt）；load_index terms_dir 逃逸（latent）；csv >128KiB 域炸；**sort_key 非全序→PYTHONHASHSEED 依赖注入序**（逐字节稳定=前缀缓存前提被破）
- judge/cjkmap/latex209/redlines 四钉（`6c1340d`，xfail-strict）：latex209 `_DS_AT_RE` 裸子串 `ds@` 过触发（注释/宏名误伤 reject）；cjkmap `_iter_pdf_fonts` 不走 /Pages 继承 → 共享资源文档 GB1 静默不注入 + 非 dict 资源 AttributeError 穿 per-font 壳拖死整页；redlines l2 `missing_glyph_nullfont` 同行 `.*` 与限界窗双向分歧（折行漏豁免/尾缀误豁免两形）
- client.py 七族裸逃（`5dae6fb`，xfail-strict）：`_retry_after` isdigit⊋float 可解（Unicode 上标 ²³¹ 穿透全部公开面）；`_sse_events` 非 dict data 行裸逃 chat_stream；`_parse_openai`/`_parse_anthropic` 形状错 200 体以非 ChatError 裸逃**绕过 fallback 降级臂**；discover_free_models/panel_models 成员形状洞；非 ASCII api_key UnicodeEncodeError。另 12 观测钉（LengthTruncated status=−1 倒挂致 retry 走 timeout 底等）
- engine/toolchain 九钉（`3f50e7b`；D5/D9 xfail-strict 钉期望，余绿 pin 钉现行缺陷行为）：`_split_flags` 只挡单横线——`--output-directory=` 双横线长选项可重键 pdf/log 落点（outdir 回收失守）；`compile` main 不规范化 `../` 逃逸 wdir（D9）+ stale unlink 先于路径校验致 NUL ValueError 裸逃（D3）；`probe_file` 无 cwd 内约束 `../` 命中仍返回（D5）；`load_search_cache` truthy 非标量毒化 filemap；`_texmfdist` 不查 kpsewhich rc 垃圾进 fontconfig；`route_project` eps 信号漏 is_file；`child_env` extra 压过 shell_escape 强制阀；`_MINTED_FROZEN_RE` 裸子串散文误翻 prefer
- stagerun 调度层：safe_id 双拼写撞名去重（14 对 wid 撞名实证，math--0408287 复判被罩的元凶）——`--rerun` 下同 wid 串行或 id 归一
- e2e.py:772 halt_on_error 两侧相反——权威侧裁决挂起
- C-bucket 残面：127 partial（undefined_cs 48 → cs_targeted_fix 扩表 / syntax 37 / other 30）
- orphan 机制 11 件（W31/W37/W49/W79/W102 等）待立规；worker `_build_md_zip`/dual 修后 fallback_orig 对账口径补记 drift-map

## 5. 后续排期（ROADMAP.md 摘要）

### 立即（本周已在跑/收尾）

I1–I7 项除 E2 下沉（I3，在飞）外基本核销；I5 测量四件全落。

### 短期（1–2 周）

- **S1 real 臂滚动探针**（**硬约束**：promo 10-16 到期）——每波分层抽 n≈200–300，hot/expand 加权
- S2 scorecard 口径修齐（end-state 正名 + csb 指纹校验 + `--json`）
- S3 P1 清账批（fixloop 规则面最重：graphic_repair 三缺口/CJK 缺字路由/救援物自炸/accent 缺字）
- S4 吞吐旋钮：server concurrency 3→10（**需用户裁决**）+ xelatex fail-path 单遍跳过（−40~50% 引擎秒）
- S5 质量代理指标回填（leak/term_hit/landmark_density 纯后算先进 metrics）
- S6 base 臂补跑（在飞）
- S7 R3 词法常量层 + warning 注册表 + rules 计数生成化
- S8 docs-health 三件
- S9 env-arg 波（已落 `1bbc4fb`，残余随 M1-B 路由）

### 中期（月度）

- **M1 共享缓存分发层**（3–5d）——index.jsonl 远端拉取 + HTTP fetch + 可选公共 registry；「1 万篇预译秒回」的 hjfy 对等武器
- **M2 批量承载底板**（2–4d）——tasks 分页/SSE 收敛（>6 在途撞浏览器上限）/retention+GC
- **M3 首启可用 + 公网分发**（1–3d）——默认 base_url 中性化 + systemd/compose 样例
- M4 compile/engine.py 拆分 + fixloop↔engine 环掐断；M5 e2e 共享件扶正余量；M6 mech_tags 全层回填；M7 术语表扩面；M8 反馈 + 换模型重翻闭环；M9 f 带进样+hot 补齐；M10 50k 前置磁盘纪律

### 远期/战略

匿名已译浏览/公共实例（产品形态分叉决策）、多任务 worker 池+Redis、前端打磨包（暗色/Reader 拆分/拆包）、rules.yaml 治理、桌面端 M4。

## 6. 需要你决策的点（按紧迫度）

1. **server concurrency 3→10 是否授权**：BYOK 下 ~3× 提速；代价是用户自付 token 网关的限流面变大。
2. **promo 死线前排产授权**：S1 滚动探针的配额与节奏（建议每波 n≈200–300，hot/expand 加权，10-16 前把 real 覆盖缺口跑完）。
3. **共享缓存公共 registry 是否立项**（M1）：静态托管即够，但意味着公开分发已译语料的姿态。
4. **匿名浏览/公共实例路线表态**：远期分叉，现在只需「暂不」或「调研」两字。
5. **默认 base_url 中性化**：影响对外发布形态，与 M3 绑定。
6. **e2e halt_on_error 权威侧裁决**（小）：e2e=True vs worker=False，定哪侧语义为准。

## 7. 硬约束与风险

| 约束                    | 数值/死线                    | 应对                                         |
| ----------------------- | ---------------------------- | -------------------------------------------- |
| swe-2-medium promo 到期 | **2026-10-16（剩 ~29 天）**  | S1 优先；备用 127.0.0.1:3033 + 注册源预案    |
| Devin 账号级 429        | 限流非本地可控               | retry 阶梯空转即正确姿势                     |
| 磁盘                    | 卷余 363G；50k 需 ~185G+     | M10 剪枝纪律先行                             |
| arxiv e-print           | 180/日硬限 + 429 park 翻倍   | hot/版本敏感增补的唯一受限通道               |
| 单点网关                | 私网 tailnet 单地址          | M3 中性默认 + failover 链                    |
| real↔mock 口径断点      | a08dda3 前后体积类指标不可比 | 跨波对比按 commit 切段                       |
| 并发波 csb 互踩         | 实测 +82→+14 净对冲          | 波次调度加「csb 指纹冻结窗口」或串行化记分面 |

## 8. 流程复盘：今天做对了什么、可改进什么

**做对的**：

- py-spy 钉栈调试法对 ReDoS 类卡死一次命中（三采样零位移即定性）；翻案 pytest「OOM」旧案证明「别信表象信栈」。
- 「机制归因→资产化→重跑」闭环两波实证，是成功率推进的最强杠杆。
- overseer 统一 commit + 逐 hunk 归因在多 lane 并发下零夹带事故（两次越矩均核净收编）。
- fork 代理（一次性任务）比常驻 peer 更适合 S 级独立修复——6 个 fork 全部干净交付。

**可改进的**：

- 并发波次的 csb 校验互踩导致 scorecard 读数被对冲（+82→+14）——记分面需要波次隔离或冻结窗。
- ReDoS 这类正则病灶应进静态审查清单：变长可选片在外层 `*` 下 + 首字符互斥性差 = 高危形，`(?>` 原子组是一行解。
- records schema 无版本标记 + code stamp 不盯 bench/py——波次间口径漂移零防护（S 级改进已列）。
