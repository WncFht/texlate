# arXiv 串行探针实测报告：content-disposition 三态 / 条件请求 / 旧 id 归并 / 许可证 / HTML 版本矩阵 / 发现层

日期：2026-09-14 · 依据：本机串行探针 38 发（`tmp/exp/arxiv-probes/headers.jsonl` 逐发记录），间隔 ≥3.1s、零并发、全程无 429；探针脚本 `tmp/exp/arxiv-probes/probe.py`。关联文档：`arxiv-layer.md`（下称 layer §N 指其章节号）。

## 0. 结论速览

1. **content-disposition 后缀即三态判别**：`.tar.gz`（多文件）/ `.gz`（单文件裸 gz，非 `.tex.gz`）/ `.pdf`（PDF 直投，且 `content-type: application/pdf`）——HEAD `/src/{id}` 一次即可定格式分支 + hasSrc 预检，魔数嗅探降级为下载后 sanity check。→ **销 §10.1**
2. **条件请求全面支持**：`If-None-Match` 与 `If-Modified-Since` 对 `/src/` 均返回 **304**（经 Varnish）。→ **销 §10.5**
3. **旧式 id 归并实测**：`math.AG/0301001` →301→ `/abs/math/0301001`（subject-class 写法归并到 archive 形式）；`HEP-TH` →301→ `hep-th`（小写归一）。canonical link 与 `citation_arxiv_id` 均指 archive 形。→ **销 §10.3**
4. **许可证机器可读位** = abs 页 `div.abs-license > a[href]`（URL 即枚举值）；RSS `dc:rights` 用同一 URL 词表。无 `rel="license"`/`citation_license`，RDF 块只是 trackback。
5. **HTML 版本矩阵**：每版本独立 etag/content-length；canonical 恒指无版本形；`x-robots-tag: nofollow`。**重大边缘案**：`1412.6980` latest(v9) 是 20KB **退化 stub**（LaTeXML 只吐 `See pages 1-last of 0_adam_main.pdf`）而 v1/v2 有 150KB/290KB 完整正文——「探最新版」策略会踩到 includepdf 包装壳。
6. **第四态源码形态实证**：1412.6980 v9 的 e-print 是合法 tar.gz + 含 `\documentclass` 的主文件，但正文仅 `\includepdf[pages=1-last]{...}`——解包/定位全成功却无可翻内容。主文件定位后须加「正文含量」检查。
7. **发现层**：`/rss/{cat}` 302→`export.arxiv.org`（export 桶），260 item/日含 license+announce_type+ 版本号 guid；`/list/{cat}/new` 在 arxiv.org 桶直出 818KB。均可作日更种子源，RSS 信息密度更高。
8. **类目表**：`/category_taxonomy` 200 落盘（155 个 h4 类目 + h3 archive 组）；退役 archive 不在表内 → §9.2 旧式白名单仍需手工维护。

## 1. 实测摘录

### 1.1 探针 1 —— 单文件 .gz 的 content-disposition（销 §10.1）

```
HEAD https://arxiv.org/src/0807.5094        → 200
  content-disposition: attachment; filename="arXiv-0807.5094v1.gz"
  content-type: application/gzip · content-length: 7402
  etag: "CJC2qdH9pvICEAE=" · last-modified: Tue, 10 Aug 2021 17:30:04 GMT
HEAD https://arxiv.org/src/math/0404188     → 200
  content-disposition: attachment; filename="arXiv-math0404188v6.gz"
  content-type: application/gzip · content-length: 57656
  etag: "COXyy/PKqPICEAE=" · last-modified: Wed, 11 Aug 2021 08:48:25 GMT
```

**结论**：单文件形态文件名 = `arXiv-{id}v{N}.gz`（**裸 `.gz`**，不是 `.tex.gz`、也不保留投稿原名）。旧式 id 文件名去斜杠拼接：`math/0404188` → `arXiv-math0404188v6.gz`，且裸 id 解析到 **v6**（resolved version 进文件名，与 layer §0.2 一致）。

### 1.2 探针 2 —— PDF 直投稿 content-disposition（hasSrc 预检成立）

```
HEAD https://arxiv.org/src/1602.03837 → 200
  content-disposition: attachment; filename="arXiv-1602.03837v1.pdf"
  content-type: application/pdf · content-length: 935476
HEAD https://arxiv.org/src/1906.11238 → 200
  content-disposition: attachment; filename="arXiv-1906.11238v1.pdf"
  content-type: application/pdf · content-length: 2578342
```

**结论**：PDF 直投文件名直接给 `.pdf` 后缀 + `content-type: application/pdf` 双信号——**HEAD `/src/{id}` 一次 = hasSrc 预检成立**，无需 GET 嗅 `%PDF` 魔数。配合 1.1，`filename` 后缀三分支完备：`.tar.gz` → 解包流、`.gz` → gunzip→单 tex、`.pdf` → 直接进 PDF sidecar。

### 1.3 探针 3 —— etag 重验证（销 §10.5）

```
GET https://arxiv.org/src/2203.02155
  If-None-Match: "sha256:f25763898e65142f6e9319537f7309cd0e13add9094909b082745f8c2d448b78"
  → 304 · etag 同值回显 · via: 1.1 varnish
GET https://arxiv.org/src/2203.02155
  If-Modified-Since: Mon, 07 Mar 2022 07:41:13 GMT
  → 304 · age: 952665 · via: 1.1 varnish
```

**结论**：`/src/` 对两种条件头都正确回 304，缓存重验证路线可用。细节：

- etag 有两种形态——新对象 `"sha256:{hex}"`，旧对象 `"CJC2qdH9pvICEAE="` 类 GCS 风格（0807.5094/math0404188/1602.03837 均后者）。**存原样串整体回送即可**，不要试图解析。
- 304 由 Varnish 边界缓存回（`via: 1.1 varnish`）；IMS 那条还带 `age`——缓存命中不影响正确性。
- 推论：若 etag 变化则回 200 拿新 body，天然覆盖「同版本被 replacement」场景。

### 1.4 探针 4 —— 旧式 id 归并（销 §10.3）

```
GET https://arxiv.org/abs/math.AG/0301001 → 301 · location: /abs/math/0301001
GET https://arxiv.org/abs/math/0301001    → 200
  <link rel="canonical" href="https://arxiv.org/abs/math/0301001"/>
  <meta name="citation_arxiv_id" content="math/0301001"/>
GET https://arxiv.org/abs/HEP-TH/9901001  → 301 · location: /abs/hep-th/9901001
GET https://arxiv.org/abs/hep-th/9901001  → 200 · canonical 同上形态
```

**结论**：

- `math.AG/0301001` 与 `math/0301001` 是**同一篇**；canonical = `math/0301001`——**subject-class 写法 301 归并到 archive 形式**，`.AG` 不进 canonical id。
- 大小写不归一也会 301 纠到全小写 archive 形（`HEP-TH` → `hep-th`）。
- → §9.2 归一化规则落地：`{archive}.{subj}/{7digits}` → `{archive}/{7digits}`，整体 lower-case。引用语料里 `math.AG/0301001` 这类写法常见，不归一会造成重复计数。（实测仅 math.AG 一例 subject 归并 + hep-th 一例大小写；nlin/cs 的 subject-class 写法按同构推断，未逐一实测。）

### 1.5 探针 5 —— 许可证机器可读性（新发现，补入 layer §5）

abs 页 markup（三篇样本三种取值）：

```html
<!-- 1412.6980：非独占 -->
<div class="abs-license">
    <a
        href="http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
        title="Rights to this article"
        >view license</a
    >
</div>
<!-- math/0301001 & hep-th/9901001:2004 前投稿的"假定许可证" -->
<div class="abs-license">
    <a href="http://arxiv.org/licenses/assumed-1991-2003/" ...>view license</a>
</div>
<!-- 2606.31863 (EPTCS) & 1602.03837 (LIGO GW150914)：CC-BY，多 class/icon -->
<div class="abs-license">
    <a
        href="http://creativecommons.org/licenses/by/4.0/"
        title="Rights to this article"
        class="has_license"
    >
        <img
            alt="license icon"
            ...
            src="https://arxiv.org/icons/licenses/by-4.0.png"
        />
        <span>view license</span></a
    >
</div>
```

**结论**：

- 机器可读位 = **`div.abs-license > a[href]`，href URL 即枚举值**；CC 类附 `class="has_license"` + 图标。
- 已观测取值：`nonexclusive-distrib/1.0`、`assumed-1991-2003`（旧文专属）、`creativecommons.org/licenses/by/4.0`。
- 无 `rel="license"`、`citation_license` meta；页内 `rdf:RDF` 块只含 trackback:ping，无 rights。
- **RSS `dc:rights` 用同一 URL 词表**（见 1.8）——批量拉 license 不必逐篇爬 abs。
- 附带发现：`citation_doi` meta 只在有正式 DOI 时出现（hep-th/9901001→`10.1143/PTP.101.1155`、1602.03837→`10.1103/...`、2606.31863→`10.4204/EPTCS.447.11`；1412.6980/math 0301001 无）——**不回填 `10.48550/arXiv.*`**。此为 abs 页证据，§10.4 的 Atom `<arxiv:doi>` 字段仍未直接实测，标半销。

### 1.6 探针 6 —— HTML 逐版本覆盖矩阵

| id         | `/html/{id}`          | `{id}v1`              | `{id}v2`              | 解读                                       |
| ---------- | --------------------- | --------------------- | --------------------- | ------------------------------------------ |
| 2501.14787 | 200 · 1912286B        | 200 · 同 etag 同 size | **404**               | 单版本                                     |
| 1706.03762 | 200 · 188707B         | 200 · 180979B         | 200 · 204363B         | ≥3 版本，逐版本独立 etag/size（latest=v3） |
| 1412.6980  | 200 · **20827B stub** | 200 · 150059B         | 200 · 290669B         | latest=v9 为包装壳 stub（见 1.7）          |
| 2203.02155 | 200 · 679724B         | 200 · 同 etag 同 size | **404**               | 单版本                                     |
| 2605.15481 | 200 · 272315B         | **404**               | 200 · 同 etag 同 size | 边缘案复现：v1 无 HTML、v2 有              |

公共特征：所有 HTML 响应 `x-robots-tag: nofollow` + `link: <https://arxiv.org/html/{id}>; rel='canonical'`（**canonical 恒指无版本形**，v1/v2 页也一样）；每版本独立 `etag`（内容寻址，可直接做版本级缓存键）；`last-modified` 是页面再生日（2026-08-24 批量重建痕迹），非论文时间。

**结论**：「探 `{id}`（最新版）」方向正确但**不充分**——latest 可能是 stub；逐版本 HEAD 成本低（~0.2–0.5s），降级路径应做「latest → 逐版本回退」探测。→ 推进 §10.7（接口位确认 + 新增 stub 输入）。

### 1.7 探针 7 —— HTML 样本下载 + 第四态源码形态

```
GET /html/1706.03762 → 200 · 188707B  → tmp/exp/arxiv-probes/html/1706.03762.html
GET /html/1412.6980  → 200 ·  20827B  → tmp/exp/arxiv-probes/html/1412.6980.html  ⚠ stub
GET /html/2203.02155 → 200 · 679724B  → tmp/exp/arxiv-probes/html/2203.02155.html
```

1412.6980 stub 正文全貌（LaTeXML 0.7.6 合法输出但无正文）：

```html
<div id="infobox" class="infobox">
    <a
        id="license-tr"
        href="https://info.arxiv.org/help/license/index.html#licenses-available"
    >
        License: arXiv.org perpetual non-exclusive license</a
    >
    <div id="watermark-tr">arXiv:1412.6980v9 [cs.LG] 30 Jan 2017</div>
</div>
<article class="ltx_document">
    <div id="p1" class="ltx_para">
        <p id="p1.1" class="ltx_p">
            See pages 1-last of
            <a href="https://0_adam_main.pdf">0_adam_main.pdf</a>
        </p>
    </div>
</article>
<!-- footer 附 ./1412.6980v9/__stdout.txt build log 链接 -->
```

根因（本地 corpus `bench/corpus/1412.6980/` 佐证）：v9 e-print 是合法 tar.gz，主文件 `arxiv.tex` 有 `\documentclass`，但正文只有 `\includepdf[pages=1-last]{0_adam_main.pdf}`。

**结论 —— 源码三态之外存在第四态「PDF 包装壳」**：

- 表现：e-print 非 `.pdf`（HEAD 预检判成有源码）、解包成功、`\documentclass` 定位成功，但正文是 `\includepdf`——解析管线「全绿」却产出空文档。
- 对策：主文件定位后加**正文含量检查**（剥 preamble 后正文 <阈值字节 / 探测 `\includepdf`、`\includegraphics` 独占正文）→ 判 `wrapper_pdf`，路由到 PDF sidecar（或回退更早版本 HTML——本案 v2 有 290KB 真内容）。
- stub 内 `id="license-tr"` 锚点也带许可证文本，是 HTML 路径的第二个 license 读取位。

### 1.8 探针 8 —— 发现层

```
GET https://arxiv.org/rss/cs.LG  → 302 · location: http://export.arxiv.org/rss/cs.LG
GET http://export.arxiv.org/rss/cs.LG   → 301 → https
GET https://export.arxiv.org/rss/cs.LG  → 200 · 558541B · application/rss+xml
GET https://arxiv.org/list/cs.LG/new    → 200 · 818770B · text/html（arxiv.org 直出）
```

RSS item 字段（260 items，与 list 页三节同数）：

```
99  <arxiv:announce_type>new</> · 59 cross · 49 replace · 53 replace-cross
260 <dc:creator> · 260 <dc:rights>{license URL}</> · <guid>oai:arXiv.org:{id}v{n}</guid>
dc:rights 分布: 120 CC-BY · 13 BY-NC-ND · 8 BY-NC-SA · 9 BY-SA · 1 CC0 · 109 nonexclusive
skipDays: Sat/Sun（工作日日更）· channel self-link 称 http://rss.arxiv.org/rss/cs.LG
```

list 页三节：`New submissions (99) / Cross submissions (59) / Replacement submissions (102)`，条目 `/abs/{id}` 链接 260 个。

**结论**：可作「每日新文预译」种子源。**优先 RSS**——单请求拿到 id+ 版本号+announce_type+license+abstract 五元组，密度远高于 list HTML；注意它落在 **export 桶**（限流与 Atom API 同池），调度归 export 队列。list/new 在 arxiv.org 桶可作热备。

### 1.9 探针 9 —— 类目表

```
GET https://arxiv.org/category_taxonomy → 200 · 83909B → tmp/exp/arxiv-probes/category_taxonomy.txt
结构：<h3>{Group}<br><span>({archive})</span></h3> 组 + <h4>{cat} <span>({full name})</span></h4> 类目 ×155
覆盖：math.* / nlin.* / stat.* / cs.* 等全部现行 subject class；astro-ph/cond-mat/hep-*/gr-qc 组齐
缺：退役 archive（alg-geom/dg-ga/funct-an/q-alg/cmp-lg/adap-org/chao-dyn/solv-int/patt-sol/mtrl-th…）
    —— 全表仅 "supr-con" 在描述文字出现 1 次，无类目条目
```

**结论**：现行类目 → 术语包映射底表已齐（存盘可 diff 跟踪新增类目）；§9.2 旧式 archive 白名单**不能**从该表生成，仍需手工维护退役清单。

## 2. §10 销号表

| §10 条目                       | 状态     | 结论                                                                                                 |
| ------------------------------ | -------- | ---------------------------------------------------------------------------------------------------- |
| 1. 单文件 .gz 文件名形态       | ✅ 销    | `arXiv-{id}vN.gz` 裸 `.gz`；旧 id `arXiv-{archive}{digits}vN.gz`；三分支 `.tar.gz`/`.gz`/`.pdf` 完备 |
| 2. export 429 窗口/Retry-After | ⏸ 未跑成 | 今日 export 无 429（RSS 落 export 正常 200），窗口仍未知，保留 park 策略                             |
| 3. math.AG vs math 归并        | ✅ 销    | 301→`math/`，canonical=archive 形；`HEP-TH`→`hep-th` 小写归一                                        |
| 4. Atom `<arxiv:doi>` 回填     | 🔶 半销  | abs `citation_doi` 仅真 DOI、不回填 10.48550；Atom 字段未直接实测                                    |
| 5. /src/ If-None-Match 304     | ✅ 销    | INM + IMS 均 304（Varnish），etag 存原样回送                                                         |
| 6. S3 manifest 边界            | ⏸ 未跑   | 本轮无 AWS 侧探针                                                                                    |
| 7. HTML DOM 分块规格           | 🔶 推进  | 3 篇样本落盘 `tmp/exp/arxiv-probes/html/` 供 DOM agent；新增 stub 边缘案输入                         |

## 3. 对 arxiv-layer.md 的修订建议

1. **§3.1 三态 → 四态**：补「includepdf 包装壳」——HEAD 判成有源码、解包/定位全成功但正文空；主文件定位后加正文含量检查（`\includepdf` 探测 + 正文字节阈值），判 `wrapper_pdf` 进 PDF sidecar 或回退早期版本。
2. **§2.2 HEAD 预检升级**：`content-disposition` 后缀（`.tar.gz`/`.gz`/`.pdf`）可直接定格式分支 + hasSrc 判决；魔数嗅探降为下载后 sanity check。
3. **§7 降级链**：`/html/{id}` latest 可为 stub（1412.6980v9 实证）→ L2 探测改「latest → `{id}v{n}` 逐版本回退」，且可用 content-length/正文嗅探判 stub。
4. **§9.2 归一化补实**：`{archive}.{subj}/NNNNNNN` → `{archive}/NNNNNNN` + lower-case（math.AG/HEP-TH 双实证）。
5. **§5 元数据**：license 机器可读位 = `div.abs-license a[href]`（URL 枚举）；`citation_doi` 仅真 DOI；RSS `dc:rights` 同词表可批量取。
6. **§8 发现层新增**：RSS `/rss/{cat}`（export 桶）为日更种子源首选，list/new（arxiv.org 桶）热备。
7. **etag 注意**：双形态并存（`"sha256:…"` 与 GCS 风格短串），按原样不透明串处理。

## 4. 产物清单

```
tmp/exp/arxiv-probes/
├── headers.jsonl          # 38 发逐条：label/method/url/req_headers/status/headers/elapsed/body_bytes
├── probe.py               # 探针脚本（串行限速器，可复用扩展）
├── probe_stdout.log       # 控制台摘要
├── abs/                   # 6 个 abs 页（含 canonical/license 证据；HEP-TH 与 hep-th 同文件——大小写不敏感 FS 实证）
├── html/                  # 1706.03762(189KB) 1412.6980(20KB stub) 2203.02155(680KB)
├── rss_cs.LG.txt          # 559KB 全日 RSS
├── list_cs.LG_new.txt     # 819KB /list/cs.LG/new
└── category_taxonomy.txt  # 84KB 类目表
```
