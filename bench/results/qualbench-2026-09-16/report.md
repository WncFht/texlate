# qualbench — 翻译质量评测臂（LLM-judge）

日期：2026-09-16。脚本 `bench/py/qualbench.py`（新建，本目录 `mock/`、`mock-corpus/`、`smoke/` 为其产出）。动机：现有 bench 全是结构指标（identity/leak/编译成功率/锚点保持），没有译文质量度量——模型选型此前只有 xlatbench 的硬契约通过率，分不清「契约全过但译文平庸」的模型。本臂给每个 (src_en, zh) chunk 对出 1–5 分 + 六类质量 flag，是 hjfy 都没有的能力。

## 设计

### 输入：chunk 对来源

两臂二选一（`--source`）：

- `state`（默认，主路）：递归扫 `--state-root` 下全部 `state.json`（StateStore 五表落盘），`results[]` 按 chunk_id 末行胜取 `(source, translation, kind, status)`，翻译模型取 `meta.model`。兼容两种布局：e2e_real 的 `bench/work_e2ereal/_xlat_state/{safe_id}/` 与 stagerun 的 `work/{id}/xlat-state/{arm}/`（臂名记入 record 的 `arm` 字段）。只送 ok/partial 且译文≠原文的块；skipped/fault 不评（那是管线故障不是翻译质量），计数进 run_meta。当前现场：111 篇 / 13345 可评对（swe-2-medium 产出）。
- `corpus`（干净机自检）：corpus_v3 `{id}/extracted/*.tex` 空行切段 + 内置确定性 mock 翻译（占位符/控制序列原位保留、散文 run→固定中文），不 import texlate.* 也能跑通全链。

抽样：`--papers` seed 抽篇，`--per-paper` 内按 kind 桶轮转取块保类型多样（para/caption/section_title 都会走到），`--n` 全局封顶按跨篇轮转序截取——`--n 3` 天然分散到 3 篇。

### judge 协议

system prompt 声明六类 flag（hjfy 反馈通道同款类目）：`untranslated_spans` 漏翻 / `placeholder_broken` `[[TYPE_n]]` 丢造改 / `term_inconsistency` 术语不一致或误译 / `over_translation` 不该翻的翻了（math/命令/引文/人名）/ `hallucinated_content` 增译 / `grammar` 中文不通。输出严格 JSON `{"score":1-5, "flags":[...], "note":"<=60ch"}`；``` 围栏剥皮 + 首个 `{...}` 兜底抽取，解析失败带严格提醒补问一次，再败记 `judge_error` 不送分。user 消息三段式 `[Kind]/[Source]/[Translation]`，kind 期望写进 prompt（section_title 要简洁题头、caption 要紧凑图注）。

每条 record 同时落确定性信号（`ph_missing`/`ph_invented`/`en_residue`/`src_chars`/`zh_chars`）——LLM flag 与免费规则信号可对拍（如 judge 漏报漏翻而 en_residue 爆表时可互相纠偏）。

### 工程要点

- judge 调用直接 httpx 打 `POST {base}/v1/chat/completions`，不 import texlate.xlat（bench 脚本独立轻依赖惯例，全文件仅 httpx + stdlib + benchlib）。
- 网关协议发现：3003 网关 swe-2-medium 对 `temperature=0` 直接 502（`stage=response_event`，`invalid_argument`），0.01 起正常——`--judge-temperature` 默认 0.1。注意 `texlate.xlat.prompts.ENV_JUDGE_TEMPERATURE=0.0` 走同一网关会撞同一面墙（不在本臂范围，留痕）。
- reasoning 模型思考链吃 max_tokens——`--judge-max-tokens` 默认 4096。
- 续跑：records.jsonl 逐块 append，`key={model}|{paper}|{chunk}|{judge}`——同一 chunk 换 judge 模型重评互不覆盖（对拍天然支持）；有 score 的行跳过，error 行自动重跑。
- 聚合：model×judge 总分表 + flag 频率 + per-kind + per-paper + 最差 chunk 清单（score 升序前 30 带 note）。

## 验证

### mock 臂（离线，全链）

`run --mock-judge --papers 8 --per-paper 6`（state 源）：48/48 judged，0 error → `mock/`。确定性 mock judge 按 en_residue/ph_diff 出分，真实走到 flag 聚合：9 个 `untranslated_spans`（均为译文残留的缩写/专名串，如 `BSSCO`/`DeTemple--Wang`——确定性信号本身已能圈人审目标）。`run --source corpus --mock-judge`：12/12 → `mock-corpus/`。

### 真网关冒烟（n=3）

`run --judge-model swe-2-medium --papers 8 --per-paper 6 --n 3` → `smoke/`。3/3 成功（跨 3 篇、跨 kind），单 call 2.5–3.3s、tok_in 650–843 / tok_out 43–59。分数 5/4/5；4 分那条 note 给出真实可读的批评（"「最佳可能的」略生硬，宜作「最优的」"）——judge 协议产出质量合格。

## 下一步（大样本跑法）

- n100 全量复评：`--papers 0 --per-paper 12` ≈ 111 篇 × ≤12 ≈ 1300 对，按冒烟时延、并发自限 ≤2（swe-2-medium 全局闸 4 多会话共享）估 ~30–40min，judge 与产出模型同为免费档零成本。跑完即得 swe-2-medium 的 per-kind/per-paper 质量分布基线。
- 模型对拍：换被评模型只要先让 stagerun/e2e_real 用该模型产 state（`--state-root` 可多次给，混源自动按 `meta.model` 分列）；换 judge 用 `--judge-model`——同一批 chunk 双 judge 对拍可直接算 judge 一致性。
- judge 可靠性：固定 ~30 对人工标注做 judge 校准集（记录 human-vs-judge 分差分布）；`flags_extra` 字段已留 judge 自造 flag 名的观测口。
- 门控集成：report 的 mean score / flag 率可接 bench 门（如 mean<4.0 或 hallucinated_content>0 即拦模型切换）。

## 已知边界

- `state` 源里 `[[SL]]/[[PL]]` 已 decode 成换行（state 存的是 decode 后译文），judge 看到的就是上屏形态——对。
- en_residue 对 BSSCO 类缩写/专名会误报（mock 臂已观测）；judge prompt 里 over_translation 与 untranslated_spans 的边界靠模型自己拿捏，校准集后再收紧。
- judge 目前只看 src+zh 两段，不给前后 chunk 上下文——段内自洽足够，跨段一致性（同一术语全文不统一）靠 term_inconsistency 的 per-paper 聚合兜，未来可加同篇对照对。
