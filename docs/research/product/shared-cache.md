# 社区共享译文缓存设计

> 2026-09-16。范围：share key 寻址、包格式、信任模型、opt-in 上传与服务端形态。实现落 `src/texlate/share.py`（纯库层，零新依赖，stdlib）；cli/worker/服务端接线不在本文。现状代码参照：`server/worker.py`（产物与 `cache_key_for`）、`server/store.py`（files/translation_cache 表）、`xlat/state.py`（段级键派生）。

## 0. TL;DR

- **寻址**：`share_key = sha256(arxiv_id | resolved_ver | model | prompt_ver | target_lang | glossary_hash | pipeline_ver)`——与本地 dedup 键同构，多 `glossary_hash` 一个组分，且永不拼凭证指纹。
- **包格式**：`{share_key}.share.zip` = `manifest.json` + `zh-src.zip` + `dual.json` + 可选 `zh.pdf`（partial 包合法——zh.pdf 只是贡献者侧编译证据，译文载荷在 dual.json；manifest artifacts 表即在场清单）。manifest 自校验：key_parts 重算 share_key、逐产物 sha256/bytes 对账。
- **信任模型**：下载的译文**不直接渲染**——进本地管线只跳 xlat 阶段，splice/validate(L0/L1)/compile/judge 全部本地重跑，validate 不过则丢弃回退自译。恶意包最坏结果是浪费一次编译，不会产出坏 PDF。
- **上传 opt-in**：默认关，任务完成后提示；glossary/自定义 prompt 进 key 天然隔离。
- **服务端 v1**：任意静态托管/对象存储 + `index.jsonl`，不锁定具体实现。

## 1. 动机：BYOK 下的成本池化

hjfy 是中心化模式：平台付 token，代价是每日 100 篇新建配额与登录墙，换来的产品特性是「已译论文匿名随便看」[^hjfy]。texlate 走 BYOK，每个用户自付 LLM token——零配额、零账单风险，但同一篇论文会被 N 个用户重复付费翻译。共享缓存把「已付过的 token」沉淀成社区资产：命中即秒回、零 token 成本。这是对 hjfy「已译随便看」的对等实现，但所有权反过来——缓存由用户各自的付费产出汇聚而成，不是平台资产。

## 2. 现状盘点：本地三级缓存

管线已有三层缓存，共享缓存是在产物级之上做**跨实例**延伸。

| 层     | 键                                          | 命中物                  | 位置                               |
| ------ | ------------------------------------------- | ----------------------- | ---------------------------------- |
| 源级   | `arxiv_id@resolved_ver`                     | arXiv e-print 解压树    | `data/src-cache/`（SourceCache）   |
| 产物级 | `sha256(id@ver\|model\|pipeline_ver\|lang)` | 整任务产物复用（reuse） | `tasks.cache_key`（store.py）      |
| 段级   | `{cfg16}:{seg_key}`                         | 单 chunk 译文           | `translation_cache` 表（store.py） |

产物级 `cache_key_for` 的 docstring 已注明「公开论文的确定性函数可跨租户 reuse——hjfy 对等共享缓存是既定产品特性」，并提供 `TEXLATE_CACHE_SCOPE=per_key` 凭证分桶开关（`k:{key指纹}` 拼进键材料）消除本地缓存存在性 oracle。共享缓存是同一方向的跨实例化：本地 dedup 只能命中自己跑过的任务，共享包让其他人的付费产出可被复用。

与 `cache_key_for` 的关系——同构但独立：dedup 键面是本地任务表去重，per_key scope 下可按凭证分桶；share key 是**公开寻址**，永不拼凭证/租户成分，且多 `glossary_hash` 组分。术语表改变译文内容，不进键会让不同术语表用户的译文串桶——段级 cfg 指纹 `sha256(model|prompt_ver|lang|glossary)[:16]`（worker `_make_cache`）已含此成分，share key 对齐其口径。

## 3. 寻址与版本漂移

share key 七组分按下序 `|` 拼接进 sha256：

| 组分            | 来源                          | 说明                                                  |
| --------------- | ----------------------------- | ----------------------------------------------------- |
| `arxiv_id`      | 任务行                        | 无版本号基底（`YYMM.NNNNN` 或旧式 `subject/YYMMnnn`） |
| `version`       | 取源时 resolve                | 归一形 `v5`；`""` 表 latest 别名                      |
| `model`         | 任务行                        | 模型全名，口径按 cfg 原文                             |
| `prompt_ver`    | `xlat.prompts.PROMPT_VERSION` | 模板措辞变更必 bump                                   |
| `target_lang`   | 任务行                        | 目标语言代码                                          |
| `glossary_hash` | 术语表内容指纹                | `""` 表默认/无术语表                                  |
| `pipeline_ver`  | `worker.PIPELINE_VERSION`     | `texlate-{ver}\|{prompt_ver}` 产品级版本              |

版本漂移语义：用户提交 `1706.03762`（无 v）→ 取源阶段 resolve 出具体版本（如 v5）→ **进键的是 resolved 版本**。arXiv 日后发 v6 时，同一请求 resolve 出 v6 → 新 key → 旧包自然失效不串味；而显式要 v5 的请求继续命中 v5 的包。`""`（latest）只是上传时刻的别名形态，不用于回读寻址——消费端总是先 resolve 再查。

两个刻意决策值得记：其一，`model` 组分的含义是「译文内容生产者」——BYOK 下 Alice 用 deepseek 译出的包不会命中 Bob 用其他模型的请求，这不是缺陷而是特性（用户只检索自己信任的模型池）；要做「跨模型共享」是另一层产品决策（比如白名单模型互通），v1 不做。其二，前六组分禁止含 `|`（否则分隔歧义可撞键），`pipeline_ver` 是末位组分允许自带 `|`——`worker.PIPELINE_VERSION` 本就长成 `texlate-{ver}|{prompt_ver}`，末位含分隔符无解析歧义。

## 4. 包格式

`{share_key}.share.zip`（PK zip）成员（`zh.pdf` 可选，缺席即 partial 包）：

| 成员            | 来源                 | 角色                                                                                |
| --------------- | -------------------- | ----------------------------------------------------------------------------------- |
| `manifest.json` | pack 时生成          | 寻址自校验 + 产物对账 + 元数据                                                      |
| `dual.json`     | worker `_build_dual` | **信任边界载荷**：`chunks[]` 的 `src_file`/`en`/`zh` 逐段对是回灌本地管线的原料     |
| `zh-src.zip`    | worker `_zip_zh`     | 译文 LaTeX 工程（splice 后 `zh/` 树）——冗余形态：人类可直接下载，消费端也可交叉核对 |
| `zh.pdf`        | worker `_compile_zh` | 贡献者侧编译产物——预览/证据；消费端不信任，自己重编                                 |

manifest.json schema:

```json
{
    "format": "texlate-share/1",
    "share_key": "<64hex，key_parts 七组分重算值>",
    "key_parts": {
        "arxiv_id": "1706.03762",
        "version": "v5",
        "model": "deepseek-chat",
        "prompt_ver": "xlat-prompt-v3",
        "target_lang": "zh-CN",
        "glossary_hash": "",
        "pipeline_ver": "texlate-0.1.0|xlat-prompt-v3"
    },
    "artifacts": {
        "zh-src.zip": { "sha256": "<64hex>", "bytes": 0 },
        "zh.pdf": { "sha256": "<64hex>", "bytes": 0 },
        "dual.json": { "sha256": "<64hex>", "bytes": 0 }
    },
    "contributor": "c-<16hex 本地生成匿名 id>",
    "created_at": "<UTC ISO8601 秒>"
}
```

为什么是 `dual.json` 而不是 `zh-src.zip` 当载荷：`zh/` 树是 splice 的**结果**——消费端若直接展开它就没法重跑 splice/validate，信任模型就空了。`dual.json` 的 `chunks[]` 恰好是 xlat 阶段的输出物形态：消费端把它按 `src_file` + `en` 文本对账到本地 parse 出的 chunks，再从 splice 开始全程本地跑——「只信翻译内容，不信任何下游产物」。`zh-src.zip` 留在包里是冗余但与 hjfy `{id}_zh_CN.tgz` 公开下载同形，人类可直接取用。

## 5. 信任模型（核心设计）

下载的共享包**不直接渲染、不直接进阅读器**。消费路径：

1. 本地照常 fetch `id@resolved_ver`——自己的 source cache 保证源码为真；
2. `unpack_share` 机械校验：格式/字段/产物哈希对账/share_key 自洽；
3. `dual.json.chunks[]` 按 `src_file` + `en` 文本对账到本地 chunks——对不上的段丢弃（该段回退自译或原文）；
4. splice → L0/L1 validate → compile → judge **全部本地重跑**；
5. 任一步不过 → 整包丢弃，回退正常自译流程。

效果边界要说清楚：恶意贡献者能造成的最坏结果是「让下载者多跑一遍 validate/compile 后发现不可用」——**浪费一次编译，不会产出坏 PDF，也不会消耗 token**（除非对账后残留段需要补译）。哈希对账 + share_key 自校验防的是传输损坏与索引错配，**不防伪造**——防伪靠的是消费端重跑管线，编译不撒谎。这与 hjfy 把 `{id}_zh_CN.tgz` 公开下载的信任结构一脉相承：产物可验证，所以敢分发。

`zh.pdf` 的角色要分清：它是贡献者侧的编译**证据**（证明这组译文至少在某环境编出了 PDF）与下载菜单的预览物，**不是交付物**——阅读器展示的 PDF 必须是本地重编产物。极端情况（贡献者环境修出了消费端修不出的包）由 fixloop 差异兜住，最差仍是回退自译。

## 6. opt-in 上传与隐私

上传默认**关**：任务完成后 UI 提示「分享本次译文到社区缓存」+ 配置项；v1 不做自动上传。理由直白——译文是用户付费产出，上传即放弃独占，必须显式同意。

隐私面逐组分审过：share key 七组分无凭证/身份；`contributor` 是本地生成的 `c-<16hex>` 匿名 id——刻意不复用 api key 指纹，避免「同一贡献者的所有包」被关联；包内四成员均不含凭证（compile.log 经 `scrub()` 打码才进 files 表，且本就不进包）。自定义 glossary/自定义 prompt 措辞会改变 glossary_hash/prompt_ver → 自然分到不同 key：私有术语表用户的包不污染默认术语表池，反之亦然——**配置差异即隔离，无需额外访问控制**。

一个诚实的提醒：缓存存在性本身是 oracle——任何人可用 share key 探测「某论文是否已被某模型译过」。这与 hjfy 已译列表本就公开同语义，可接受；`per_key` scope 的本地 dedup 与共享上传是两件事，凭证分桶只约束本地表。

## 7. 服务端形态（v1 不锁定实现）

文件级起步：包按 `{share_key}.share.zip` 落在任意静态托管/对象存储（GitHub Releases / OSS / R2 皆可），旁挂 `index.jsonl`，每行一条 `{share_key, url, key_parts, bytes, created_at, contributor}`。查 = 拉 index 或直拼 `GET {key}` 路径 → 取包 → 本地校验；上传 = 生成包 → 推对象存储 → 追加 index 行。

这么选的理由：共享缓存的价值在数据不在服务——先把包格式与信任模型冻结，服务端可以是仓库附件、社区成员自托管、或后续正式 API 中的任何一个，格式都不变。需要排序/GC/举报机制时再加服务层，顺序不反。

## 8. 模块面（`src/texlate/share.py`）

| API             | 签名                                                                                      | 职责                                                                             |
| --------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `share_key`     | `(arxiv_id, version, model, prompt_ver, target_lang, glossary_hash, pipeline_ver) -> str` | 寻址键派生；version 归一（`3`/`"v3"`/`None`）                                    |
| `pack_share`    | `(work_dir, manifest, *, out_dir=None) -> Path`                                           | 三件套打包 + manifest 生成 + sha256 自校验字段                                   |
| `unpack_share`  | `(path, dest) -> ShareManifest`                                                           | 解包 + 全量校验；坏包 `ShareError`                                               |
| `ShareManifest` | frozen dataclass                                                                          | 校验后 manifest 视图（fmt/share_key/key_parts/artifacts/contributor/created_at） |
| `ShareError`    | Exception                                                                                 | 一切格式/校验失败                                                                |

纯库层：不接 cli/app。后续接线点：worker 完成钩子上 opt-in 打包上传；任务创建 fetch 后（此时 resolved_ver 已知）→ share_key lookup → 命中走 §5 验证通道。

## 9. 开放问题

- **chunks 对账协议**：`src_file + en` 文本匹配的隐含假设是同一 `id@ver` 源码在两侧 parse 出逐字节相同的 chunk——同版本 segmenter 下成立；segmenter 演进会让 en 文本分叉，但 `pipeline_ver` 组分已兜住（实现变 → 版本变 → key 变 → 不互相命中），属保守但正确的失效。
- ~~**fault/partial 产物可否共享**：v1 要求三件套齐全（zh.pdf 在场 = 贡献者侧至少编通过）；「译文好但贡献者环境编不过」的包价值存疑，留给 v2。~~ **已放行**（2026-09-16 `c6e4306`）：pack/unpack 同口径只强制 `zh-src.zip`+`dual.json`，zh.pdf 缺席即 partial 包——fixloop_exhausted 型任务的 L2 修复译文经包传播有实证价值（share-live gap#4）；贡献者编不过只是少了证据件，消费端反正本地重编。
- **段级共享**：`translation_cache` 表结构直接就是段级共享素材（key 已含 cfg 指纹），粒度更细、命中收益更高；但单段译文无法在本地 compile 验证语义，信任模型弱一档——v1 选文档级正因为它能被全链重跑验证。
- **配额与滥用**：上传侧限流、包大小配额、恶意包举报通道——等服务选型再定。
- **内容签名**：v1 信任模型不需要签名——伪造包的无害化由消费端重跑全链承担，不靠身份担保。若未来要「可信贡献者快速通道」（跳过部分重验证）或贡献者信誉体系，可在 manifest 增加 `signature` 字段（如对 `share_key`+产物哈希做 ed25519 签名）；stdlib 无 ed25519，届时要么引依赖要么把验签放服务端。

### 参考文献

[^hjfy]: 幻觉翻译 hjfy.top 线上侦察（本仓 `docs/research/product/hjfy-site.md`）。产物三件套 `{id}.pdf`/`{id}_zh_CN.pdf`/`{id}_zh_CN.tgz`、已译论文匿名可看、新建 100 篇/天配额、[hjfy.top](https://hjfy.top)。2026-09.
