# 社区共享译文缓存设计

> **结论**：share key 组分寻址（七必备 + 可选 `front_matter`）+ `.share.zip` 包格式 + 「下载译文不直接渲染、本地全链重跑」信任模型已冻结并实装（`src/texlate/share.py` + worker 完成钩 + share 域路由 + Reader 分享按钮 + `texlate share pack`）。
> **状态**：已落地——设计与 `src/texlate/share.py`、`server/routers/share.py`、`server/worker/share.py` 实装对齐；规范口径以 spec/ 层为准，本文留设计推理作参考。
> **日期**：2026-09-16（2026-09-19 复核实装）

## 0. TL;DR

- **寻址**：`share_key = sha256(arxiv_id | resolved_ver | model | prompt_ver | target_lang | glossary_hash [| front_matter] | pipeline_ver)`——与本地 dedup 键同构，多 `glossary_hash` 一个组分，且永不拼凭证指纹；`front_matter`（preamble 前置发射集排序清单，`"abstract,title"` 形）是可选第八组分，非空才进键插在 `pipeline_ver` 前，空串省略与前置全盖过的历史包同键。
- **包格式**：`{share_key}.share.zip` = `manifest.json` + `zh-src.zip` + `dual.json` + 可选 `zh.pdf`（partial 包合法——zh.pdf 只是贡献者侧编译证据，译文载荷在 dual.json；manifest artifacts 表即在场清单）。manifest 自校验：key_parts 重算 share_key、逐产物 sha256/bytes 对账。
- **信任模型**：下载的译文**不直接渲染**——进本地管线只跳 xlat 阶段，splice/validate(L0/L1)/compile/judge 全部本地重跑；对不上的段回原文、validate 不过则该块回原文（v1 零 token 结构承诺：导入链永不消耗 token）。恶意包最坏结果是浪费一次编译，不会产出坏 PDF。
- **上传 opt-in**：默认关，任务完成后提示——已落地四面：`options.share_pack` worker 完成钩、`POST /api/task/{id}/share/pack` 端点、Reader「分享本译文」按钮、CLI `texlate share pack`（同口径打包）；glossary/自定义 prompt 进 key 天然隔离。
- **服务端 v1**：任意静态托管/对象存储 + `index.jsonl`，不锁定具体实现。

## 1. 动机：BYOK 下的成本池化

hjfy 是中心化模式：平台付 token，代价是每日 100 篇新建配额与登录墙，换来的产品特性是「已译论文匿名随便看」[^hjfy]。texlate 走 BYOK，每个用户自付 LLM token——零配额、零账单风险，但同一篇论文会被 N 个用户重复付费翻译。共享缓存把「已付过的 token」沉淀成社区资产：命中即秒回、零 token 成本。这是对 hjfy「已译随便看」的对等实现，但所有权反过来——缓存由用户各自的付费产出汇聚而成，不是平台资产。

## 2. 现状盘点：本地三级缓存

管线已有三层缓存，共享缓存是在产物级之上做**跨实例**延伸。

| 层     | 键                                          | 命中物                  | 位置                            |
| ------ | ------------------------------------------- | ----------------------- | ------------------------------- |
| 源级   | `arxiv_id@resolved_ver`                     | arXiv e-print 解压树    | `data/src-cache/`（SourceCache） |
| 产物级 | `sha256(id@ver\|model\|pipeline_ver\|lang)` | 整任务产物复用（reuse） | `tasks.cache_key`（store）      |
| 段级   | `{cfg16}:{seg_key}`                         | 单 chunk 译文           | `translation_cache` 表（store） |

产物级 `cache_key_for` 的 docstring 已注明「公开论文的确定性函数可跨租户 reuse——hjfy 对等共享缓存是既定产品特性」，并提供 `TEXLATE_CACHE_SCOPE=per_key` 凭证分桶开关（`k:{key指纹}` 拼进键材料）消除本地缓存存在性 oracle。共享缓存是同一方向的跨实例化：本地 dedup 只能命中自己跑过的任务，共享包让其他人的付费产出可被复用。

与 `cache_key_for` 的关系——同构但独立：dedup 键面是本地任务表去重，per_key scope 下可按凭证分桶；share key 是**公开寻址**，永不拼凭证/租户成分，且多 `glossary_hash` 组分。术语表改变译文内容，不进键会让不同术语表用户的译文串桶——段级 cfg 指纹（worker `_make_cache`，规范口径见 `spec/translate.md` 的 `cfg_hash`：`sha256(model|PROMPT_VERSION|target_lang|base_url|u:user_glossary_sig|l:local_sig|c:categories|ag:auto_glossary)[:16]`）其 `u:`/`l:`/`ag` 组分已含术语表成分，share key 对齐其口径。

## 3. 寻址与版本漂移

share key 组分按下序 `|` 拼接进 sha256（七必备 + 可选 `front_matter`）：

| 组分            | 来源                          | 说明                                                                                                                               |
| --------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `arxiv_id`      | 任务行                        | 无版本号基底（`YYMM.NNNNN` 或旧式 `subject/YYMMnnn`）                                                                              |
| `version`       | 取源时 resolve                | 归一形 `v5`；`""` 表 latest 别名                                                                                                   |
| `model`         | 任务行                        | 模型全名，口径按 cfg 原文                                                                                                          |
| `prompt_ver`    | `xlat.prompts.PROMPT_VERSION` | 模板措辞变更必 bump                                                                                                                |
| `target_lang`   | 任务行                        | 目标语言代码                                                                                                                       |
| `glossary_hash` | 术语表内容指纹                | `""` 表默认/无术语表                                                                                                               |
| `front_matter`  | 任务 options（可选组分）      | preamble 前置发射集逗号排序清单（`"abstract,title"` 形）；非空才进键插在 `pipeline_ver` 前，空串省略组分、与前置全盖过的历史包同键 |
| `pipeline_ver`  | `worker.PIPELINE_VERSION`     | `texlate-{ver}\|{prompt_ver}` 产品级版本                                                                                           |

版本漂移语义：用户提交 `1706.03762`（无 v）→ 取源阶段 resolve 出具体版本（如 v5）→ **进键的是 resolved 版本**。arXiv 日后发 v6 时，同一请求 resolve 出 v6 → 新 key → 旧包自然失效不串味；而显式要 v5 的请求继续命中 v5 的包。`""`（latest）只是上传时刻的别名形态，不用于回读寻址——消费端总是先 resolve 再查。

两个刻意决策值得记：其一，`model` 组分的含义是「译文内容生产者」——BYOK 下 Alice 用 deepseek 译出的包不会命中 Bob 用其他模型的请求，这不是缺陷而是特性（用户只检索自己信任的模型池）；要做「跨模型共享」是另一层产品决策（比如白名单模型互通），v1 不做。其二，`pipeline_ver` 之前的组分（含 `front_matter`）禁止含 `|`（否则分隔歧义可撞键），`pipeline_ver` 是末位组分允许自带 `|`——`worker.PIPELINE_VERSION` 本就长成 `texlate-{ver}|{prompt_ver}`，末位含分隔符无解析歧义。

组分归一化实装口径（`share.py`）：各组分进键前逐组分 `strip()`；`front_matter` 非空才记入 key_parts（缺席即与前置全盖过的历史包七组分形完全一致）。manifest 侧 `_key_parts` 同口径归一，且 `version`/`glossary_hash` 两可空组分的 JSON `null` 与 `""` 同义（latest 别名/无术语表），其余五必备组分 `None` 或 strip 后空串按缺键拒（`ShareError`）；`version` 另过 `_norm_version`（`3`/`"v3"`/`None` → `v3`/`""` 归一形）。

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

`key_parts` 另有可选 `front_matter` 字段（preamble 前置发射集排序清单）：非空才在场、重算时插在 `pipeline_ver` 前进键；缺席即七组分形，与「前置全盖过」的历史包同键。worker 侧由 `share_pack_manifest` 按 `ran_front_matter` 实跑集派生，导入端 `share/import` 按 manifest 值锁回任务 options。

为什么是 `dual.json` 而不是 `zh-src.zip` 当载荷：`zh/` 树是 splice 的**结果**——消费端若直接展开它就没法重跑 splice/validate，信任模型就空了。`dual.json` 的 `chunks[]` 恰好是 xlat 阶段的输出物形态：消费端把它按 `src_file` + `en` 文本对账到本地 parse 出的 chunks，再从 splice 开始全程本地跑——「只信翻译内容，不信任何下游产物」。`zh-src.zip` 留在包里是冗余但与 hjfy `{id}_zh_CN.tgz` 公开下载同形，人类可直接取用。

包完整性实装面：`pack_share` 对每个产物**单遍流式读**（`_pack_member`：1MB 块经 `zf.open()` 成员流边写边算 sha256）——manifest 记的是真实入包字节流的指纹，同一份字节既进 sha256/bytes 对账字段又写 zip 成员，消灭「对账到写入之间文件被改 → 包自矛盾」的 TOCTOU；发布走临时文件 + 原子 rename（并发同键打包/静态托管读取不见半成品）；单产物 >256MB（`_MEMBER_MAX`）拒（stat 预检之外，循环内实时字节计数兜底 stat 后文件增长）。`unpack_share` 校验序：zip 可读 → `manifest.json` 在场且 ≤1MB（`_MANIFEST_MAX`）→ `format`/`key_parts`/`share_key` 重算自洽 → `artifacts` 逐条校验（产物名扁平白名单 `_name_ok`：拒 `/`、`\`、NUL 与 >255B 名；sha256 定长 64hex；`bytes` ∈ [0,256MB] int）→ 逐成员 size+sha256 对账；只抽 manifest 登记成员（多余成员忽略，天然免 zip-slip）；产物先落 `dest` 内临时目录、全部对账过才逐件 rename——中途失败 `dest` 零残留。

## 5. 信任模型（核心设计）

下载的共享包**不直接渲染、不直接进阅读器**。消费路径：

1. 本地照常 fetch `id@resolved_ver`——自己的 source cache 保证源码为真；
2. `unpack_share` 机械校验：格式/字段/产物哈希对账/share_key 自洽——不过则端点 400 拒收，不建行；
3. `dual.json.chunks[]` 按 `src_file` + `en` 文本对账到本地 chunks——对不上的段 `fallback_orig` 回原文（v1 **不回退自译**：导入承诺结构零 token，漏段宁可原文呈现）；
4. splice → L0/L1 validate → compile → judge **全部本地重跑**；
5. 编译侧任一步不过 → 该任务按普通 partial/reject 终态收口（`reject_at=share_verify` 等留痕），不消耗 token 重译。

效果边界要说清楚：恶意贡献者能造成的最坏结果是「让下载者多跑一遍 validate/compile 后发现不可用」——**浪费一次编译，不会产出坏 PDF，也不会消耗 token**（除非对账后残留段需要补译）。哈希对账 + share_key 自校验防的是传输损坏与索引错配，**不防伪造**——防伪靠的是消费端重跑管线，编译不撒谎。这与 hjfy 把 `{id}_zh_CN.tgz` 公开下载的信任结构一脉相承：产物可验证，所以敢分发。

`zh.pdf` 的角色要分清：它是贡献者侧的编译**证据**（证明这组译文至少在某环境编出了 PDF）与下载菜单的预览物，**不是交付物**——阅读器展示的 PDF 必须是本地重编产物。极端情况（贡献者环境修出了消费端修不出的包）由 fixloop 差异兜住，最差是漏段回原文的 partial 终态——v1 不为导入任务回退自译（零 token 承诺）。

## 6. opt-in 上传与隐私

上传默认**关**：任务完成后 UI 提示「分享本次译文到社区缓存」+ 配置项；v1 不做自动上传。理由直白——译文是用户付费产出，上传即放弃独占，必须显式同意。

落地现状（2026-09-17）：提示面 = Reader「分享本译文」按钮三挂载点（done 阅读器 share-banner、partial 等非干净终态 result-banner 操作行、doc 类任务整页产物面板；`canShare` 门控 = done/partial + `kind∉{share,arxiv_html}` + 有 arxiv_id）→ `POST /api/task/{id}/share/pack`（幂等，响应 `{share_key,url,bytes}`；`kind=share`/`arxiv_html`/reuse 命中 422、非终态 409、缺产物 422）；配置项 = Home 高级选项 `share_pack`（worker `_maybe_share_pack` 完成钩自动打包）；CLI `texlate share pack` 与端点同口径（`share_pack_manifest` 单一派生面）。

隐私面逐组分审过：share key 各组分无凭证/身份；`contributor` 是本地生成的 `c-<16hex>` 匿名 id——刻意不复用 api key 指纹，避免「同一贡献者的所有包」被关联；包内四成员均不含凭证（compile.log 经 `scrub()` 打码才进 files 表，且本就不进包）。自定义 glossary/自定义 prompt 措辞会改变 glossary_hash/prompt_ver → 自然分到不同 key：私有术语表用户的包不污染默认术语表池，反之亦然——**配置差异即隔离，无需额外访问控制**。

一个诚实的提醒：缓存存在性本身是 oracle——任何人可用 share key 探测「某论文是否已被某模型译过」。这与 hjfy 已译列表本就公开同语义，可接受；`per_key` scope 的本地 dedup 与共享上传是两件事，凭证分桶只约束本地表。

## 7. 服务端形态（v1 不锁定实现）

文件级起步：包按 `{share_key}.share.zip` 落在任意静态托管/对象存储（GitHub Releases / OSS / R2 皆可），旁挂 `index.jsonl`，每行一条 `{share_key, url, key_parts, bytes, created_at, contributor}`。查 = 拉 index 或直拼 `GET {key}` 路径 → 取包 → 本地校验；上传 = 生成包 → 推对象存储 → 追加 index 行。

这么选的理由：共享缓存的价值在数据不在服务——先把包格式与信任模型冻结，服务端可以是仓库附件、社区成员自托管、或后续正式 API 中的任何一个，格式都不变。需要排序/GC/举报机制时再加服务层，顺序不反。

## 8. 模块面（`src/texlate/share.py`）

| API                     | 签名                                                                                                          | 职责                                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `share_key`             | `(arxiv_id, version, model, prompt_ver, target_lang, glossary_hash, pipeline_ver, *, front_matter="") -> str` | 寻址键派生；version 归一（`3`/`"v3"`/`None`）；`front_matter` 非空时作为可选组分插在 `pipeline_ver` 前进键                        |
| `pack_share`            | `(work_dir, manifest, *, out_dir=None) -> Path`                                                               | 三件套打包 + manifest 生成 + sha256 自校验字段                                                                                    |
| `unpack_share`          | `(path, dest) -> ShareManifest`                                                                               | 解包 + 全量校验；坏包 `ShareError`                                                                                                |
| `index_append`          | `(index_path, manifest, url, package_bytes) -> dict`                                                          | §7 index.jsonl 追加一行（share_key/url/key_parts/bytes/created_at/contributor）                                                   |
| `index_lookup`          | `(index_path, share_key) -> dict \| None`                                                                     | 线性扫 index，同 key 后写胜；malformed 行跳过、扫完一条 warning 带行号（单行坏数据不毒死全索引）；整文件非 UTF-8 仍抛由调用方降级 |
| `glossary_content_hash` | `(*, user_layer, local_layer, fallback_user=None, strict_layers=frozenset()) -> str`                          | `glossary_hash` 键组分派生：翻译时生效的自定义术语层（user→local）内容复合指纹；cli 与 worker 两臂共用（各按自己生效层喂参）      |
| `ShareManifest`         | frozen dataclass                                                                                              | 校验后 manifest 视图（fmt/share_key/key_parts/artifacts/contributor/created_at）                                                  |
| `ShareArtifact`         | frozen dataclass                                                                                              | manifest `artifacts` 单条校验记录（`sha256`/`size`），`ShareManifest.artifacts` 的值型                                            |
| `ShareError`            | Exception                                                                                                     | 一切格式/校验失败                                                                                                                 |

纯库层：不接 cli/app。接线现状：worker 完成钩已落地（`options.share_pack` opt-in，三终态出口 `pack_share`+`unpack_share` 回验后 `index_append` 进 `share_dir/index.jsonl`；`kind∈{share,arxiv_html}` 与 reuse_hit 永不自包）；`POST /api/task/{id}/share/pack` 事后打包端点同口径（`share_pack_manifest` 单一派生面，幂等 + 409/422 守卫阶梯）。消费侧 v1 = 显式导入：`POST /api/share/import`（`unpack_share` 机械校验 + key_parts 白名单 → `kind="share"` 任务，model/lang/arxiv_id/version/front_matter 取 manifest 自描述值）→ worker `_run_share` 走 §5 全链（fetch→parse→`(src_file,en)` 对账回灌→compile，零 token——包内 zh-src.zip/zh.pdf 只作证据不解不进产物面）；web 端 `.share.zip` 上传自动路由此端点。

隐式命中亦已接线：`_run_tex` 在 `_stage_parse` 后经 `_to_thread` 调 `_share_lookup`（`server/worker/share.py`，挂点在 `worker/core.py::_run_tex`）——选 parse 后而非 fetch 后是刻意的：share_key 的 `glossary_hash` local 层（`base/glossary.local.yaml`）与 `_glossary_path` confine 根都依赖 `_build_base` 产物，fetch 后即查会把生效术语表算漏。闸面：`kind=="arxiv"` + 非 dedup 命中 + `prefer!="fresh"` 才查；命中 → 包校验解包 `ctx.root/"share"` + `options["share"]` 审计载荷（与导入端点同形）+ `options["reuse_hit"]="share:{key}"` 来历标记（share/pack 端点据以拒自包）→ `_stage_share_apply` 对账通道零 token；miss/索引损坏/包缺失/校验失败一律 log 留痕回退自译。幂等：标记与 `share/` 现场持久化，resume 重验 key 符且 `dual.json` 在场即直返；retry 改 options 致 key 漂移、`share` 载荷伪造/残缺、对账拒绝，都由 `_share_unmark` 摘除标记与解包现场后按现状重查。

## 9. 开放问题

- **chunks 对账协议**：`src_file + en` 文本匹配的隐含假设是同一 `id@ver` 源码在两侧 parse 出逐字节相同的 chunk——同版本 segmenter 下成立；segmenter 演进会让 en 文本分叉，但 `pipeline_ver` 组分已兜住（实现变 → 版本变 → key 变 → 不互相命中），属保守但正确的失效。
- ~~**fault/partial 产物可否共享**：v1 要求三件套齐全（zh.pdf 在场 = 贡献者侧至少编通过）。~~ **已放行**（2026-09-16）：pack/unpack 同口径只强制 `zh-src.zip`+`dual.json`，zh.pdf 缺席即 partial 包——fixloop_exhausted 型任务的 L2 修复译文经包传播有实证价值；贡献者编不过只是少了证据件，消费端反正本地重编。
- **段级共享**：`translation_cache` 表结构直接就是段级共享素材（key 已含 cfg 指纹），粒度更细、命中收益更高；但单段译文无法在本地 compile 验证语义，信任模型弱一档——v1 选文档级正因为它能被全链重跑验证。
- **配额与滥用**：上传侧限流、包大小配额、恶意包举报通道——等服务选型再定。
- **内容签名**：v1 信任模型不需要签名——伪造包的无害化由消费端重跑全链承担，不靠身份担保。若未来要「可信贡献者快速通道」（跳过部分重验证）或贡献者信誉体系，可在 manifest 增加 `signature` 字段（如对 `share_key`+产物哈希做 ed25519 签名）；stdlib 无 ed25519，届时要么引依赖要么把验签放服务端。

### 参考文献

[^hjfy]: 幻觉翻译 hjfy.top 线上侦察（本库 `research/product/hjfy-site.md`）。产物三件套 `{id}.pdf`/`{id}_zh_CN.pdf`/`{id}_zh_CN.tgz`、已译论文匿名可看、新建 100 篇/天配额、[hjfy.top](https://hjfy.top)。2026-09.
