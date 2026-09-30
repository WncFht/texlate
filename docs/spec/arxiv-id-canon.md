# arXiv 标识符规范化（canon）

`canon(raw) -> CanonId` 是 arXiv 标识符归一化的单源契约：裸 id、URL、DOI、OAI 标识符、`arXiv:` 前缀、存储拼写等任意常见输入形态 → 规范形 id 或拒收。本体在 `arxiv/fetch.py`（server/CLI 共用），web 侧 JS 镜像在 `web/src/arxidcanon.ts`；任务落库与 dedup 键统一走 canon base。本文是该契约的唯一事实源——与代码冲突以代码为准；远端行为判例与语料普查证据引 `research/arxiv/2026-09-22-id-canon-probes.md`，不复述[^canon-probes]。

两个正交概念必须分清：**canon**（用户输入 → 规范 id：锚定剥离管线 + 校验）与 **scan**（自由文本 → 候选 id）。本规格只管 canon；scan 有自己的精度权衡（`reader/cite/citations.ts::extractRefIds` 用 YYMM 硬约束防 `1234.56789` 式误报；server 侧 `ARXIV_ID_FIND_RX` 只产候选，上下文前缀闸归消费方），不并入本件。

## 0. 消费方与落点

| 端     | 位置                        | 符号                                               | 职责                                                                                         |
| ------ | --------------------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| server | `arxiv/fetch.py`            | `canon` / `try_canon` / `CanonId` / `CanonError`   | canon 本体：剥离管线 + 校验 fused                                                            |
| server | `arxiv/fetch.py`            | `normalize_arxiv_id` / `valid_id` / `req_base_ver` | 薄壳兼容层：旧签名转发 canon，调用点零签名变化（§5）                                         |
| server | `arxiv/fetch.py`            | `ARXIV_ID_FIND_RX`                                 | 自由文本候选抽取正则（scan 面单源；`bibexport.extract_ids` 等消费，上下文闸归消费方）        |
| server | `routers/tasks.py`          | `POST /api/arxiv/{id}/translate`                   | `normalize_arxiv_id` + `valid_id` 闸；建行 `arxiv_id=canon base`（原始拼写留 `source_name`） |
| server | `routers/refs.py`           | `normalize_arxiv_id` + `valid_id`                  | 文献表 `arxivId`（`math.GT/`、DOI 形）经 canon 落 `ARXIV:` 道而非漏进 DOI 道                 |
| web    | `web/src/arxidcanon.ts`     | `canonStrip`                                       | 剥壳镜像：loose/strict 双口径，只做剥壳不做校验（§3/§5）                                     |
| web    | `web/src/arxidcanon.ts`     | `canonArxivKey`                                    | 双侧归一匹配键（loose 剥壳 + 整串小写）；`citations.ts::canonRefId` 是同键别名               |
| web    | `home/search.ts`            | `parseArxivId`                                     | 输入框提交校验：strict 剥壳 + MM/era/vN 闸叠层（刻意比服务端窄，§3）                         |
| bench  | `bench/py/kernel/idnorm.py` | `canon_id` / `safe_id` / `idc_from_safe`           | **独立 canon 域**：语料身份归一，口径刻意与本件不同（§4.2）                                  |

落库键：`arxiv_id = canon base`——class/大小写归一后同文同 task 键同 cache_key（dedup 语义变化是特性；存量异键任务/缓存不迁移）。

## 1. 规范形定义（输出侧）

```
canon(raw: str) -> CanonId | raises CanonError

CanonId:
    base:     str        # YYMM.NNNNN | archive/YYMMNNN
    version:  int | None # 仅用户钉版时非 None；>=1、无导零
    scheme:   "new" | "old"
    str()  -> base 或 f"{base}v{version}"
    safe() -> base.replace("/", "--")   # 存储拼写编码（§4）
```

规范形两条铁律（均已向 arxiv.org 实证[^canon-probes]）：

1. **旧式不带 subject class**。`math.GT/0309136`、`cs.SE/0501001`、`q-bio.GN/0611042`、`physics.atom-ph/9801001`、`cond-mat.mes-hall/9701001` 一律 301 → 裸 `archive/YYMMNNN`。class 是元数据不是标识符部件，canon 剥掉。
2. **archive 全小写**。`Hep-Th/9901001`、`HEP-TH/9901001` 均 301 → `hep-th/`。版本 `V` 大写同理 → `v`（导零 `v03` → `v3`）。

新式 id 全数字无 case 面。幂等：`canon(str(canon(x))) == canon(x)`。

## 2. 输入面全集（剥离顺序即管线序）

```
strip()                                        # 空白（含 unicode ws）
unfold safe_id: "--" → "/"                     # 存储拼写回流（§4）
strip 前缀（大小写不敏感，循环至不动点——可叠套，如 arXiv:10.48550/arXiv.…）:
    ^(?:https?://)?(?:[\w.-]+\.)?arxiv\.org/(abs|pdf|src|e-print|html|format)/+
    ^https?://(?:[\w.-]+\.)?(ar5iv|alphaxiv)\.org/(abs|pdf|html)/+   # 镜像白名单臂
    ^https?://(dx\.)?doi\.org/                   # DOI 前缀
    ^doi:\s*                                    # doi: 裸前缀
    ^10\.48550/ar[Xx]iv\.                       # DataCite DOI 尾
    ^oai\s*:\s*arxiv\.org\s*:\s*                # OAI-PMH identifier
    ^arxiv\s*[:.]\s*                            # arXiv: 与 arXiv. 两形
截断 ? 与 # 尾
strip 尾 "/" 与首尾空白
尾注/扩展名循环至不动点（两序皆收——id [cs.CL].pdf 与 id.pdf [cs.CL] 同归）:
    \s*\[[^\]]{1,20}\]\s*$                      # [cs.CL] 引用尾注
    \.(pdf|ps|eps|dvi|gz|tgz|tar\.gz)$          # 下载扩展名（逐层剥）
剥版本尾 ^(.+?)[vV](\d{1,3})$：ver<1 → CanonError(bad_version)，不静默去钉
旧形剥 class：^([-a-zA-Z]+)(?:\.[A-Za-z][A-Za-z-]*)?/(\d{7})$ → archive/NNNNNNN
archive lowercase → 白名单校验（§3），不过 → CanonError
```

两条结构性防线（misc-pack 对抗探针面钉死）：

- **锚定正则前缀剥，不 urlparse 任意 host**——`ftp://`/`javascript:` 等怪 scheme、`:8080` 端口、`//` 双斜杠结构性拒收（剥不掉前缀的剩件过不了 §3 形检）。
- **子域点界**：arxiv.org 臂的子域组是 `(?:[\w.-]+\.)?`（显式 `.` 边界）——`notarxiv.org`、`arxiv.org.evil.com` 这类寄生/拼合域不得命中。镜像白名单臂（`ar5iv.org`/`alphaxiv.org`）**须带 http(s) scheme 且动词限 `abs|pdf|html`**——`/overview` 等未实证动词不收，裸域无 scheme 不收。

必收形态实例（`tests/arxiv/test_arxiv_canon.py` 30 形态表摘）：

| 输入                                            | canon base         |
| ----------------------------------------------- | ------------------ |
| `physics.atom-ph/9801001`                       | `physics/9801001`  |
| `cond-mat.mes-hall/9701001`                     | `cond-mat/9701001` |
| `math.GT/0309136`                               | `math/0309136`     |
| `Hep-Th/9901001`                                | `hep-th/9901001`   |
| `10.48550/arXiv.2301.00001`                     | `2301.00001`       |
| `https://doi.org/10.48550/arXiv.hep-th/9901001` | `hep-th/9901001`   |
| `arXiv.2301.00001`（DOI 尾形）                  | `2301.00001`       |
| `arXiv:2301.00001 [cs.CL]`                      | `2301.00001`       |
| `oai:arXiv.org:math.GT/0309136`                 | `math/0309136`     |
| `hep-th--9901001`（safe_id 回流）               | `hep-th/9901001`   |
| `2301.00001.tar.gz`（e-print 文件名粘贴）       | `2301.00001`       |
| `https://ar5iv.org/abs/2301.00001`              | `2301.00001`       |

必拒面（结构性保证，非错误路径补丁）：`..` 路径逃逸（`2301.00001/../2301.00002`——经 URL 归一化能拿远端 200，但会把别篇内容写进错误缓存键/逃逸缓存根，`CanonError(unsafe)`）、`v0`/`v1234` 钉版（前者 `bad_version`，后者超 `\d{1,3}` 不归出版面归 `bad_shape`）、寄生域、`ftp://` 等非 http(s) scheme、unicode 数字（`re.ASCII`）。

非目标（明确不收）：`xxx.lanl.gov` 等历史镜像域名、ADS bibcode `1999hep.th....1001X`、`arXiv preprint` 散文形态、`.bak-mock` 测试残尾（manifest 实证存在的脏拼写——canon 不洗，留给 triage 暴露分裂信号[^canon-probes]）。

## 3. 校验（canon 内 fuse）

```
OLD: ^([A-Za-z-]+)(?:\.[A-Za-z][A-Za-z-]*)?/(\d{7})$   # class 可选、archive 大小写不拘
NEW: ^(\d{4})\.(\d{4,5})$                            # YYMM.NNNNN
语义闸：MM∈[01,12]；strict_era（默认开）要求 形↔时代窗一致——
        旧形窗 = YYMM∈9107–9912 ∪ 0000–0703，新形须落窗外（0704–9106）
```

- `MM` 校验为默认：`9913.00001`/`2300.00001`/`0601.00001` 本地即拒，省一轮远端 404。
- `strict_era`：新形 `YYMM<0704`（如 `9912.00001`——2099 年的串其实是旧形时代的 YYMM）与老形 `YYMM>0703`（如 `hep-th/0801001`）都是不可能存在的 id，本地拒。
- seq `\d{4,5}`：0704–1412 为 4 位、1501+ 为 5 位，但 arXiv 服务端跨时代互认（`0704.00001`→301→`0704.0001`，`1501.0001`→301→`1501.00001`），canon 不做按时代位数闸——收 superset[^canon-probes]。
- 版本 `\d{1,3}` 上限保留（真实最高 ~46），导零 `v03`→`v3`。
- 所有正则 `re.ASCII` 等效（JS 侧 `[0-9]`/显式类）。
- web `parseArxivId` 的 era 闸**刻意更窄**：新形 `YYMM∈[0704, 当前YYMM]`——上界钉当前年月把未来态 id 也本地拒（服务端只挡时代错位不挡未来形）；旧形窗与服务端一致。cite-scan（`extractRefIds`）另有自己的宽口径 YYMM 闸——那里防的是误报，规则不同不照搬。

## 4. 存储拼写层（safe_id）

### 4.1 编码与归并位

`--` 永不可能出现在合法 id 内（旧 archive 只带单 `-`、新形无连字符），故 unfold `--`→`/` 无歧义，**并进 canon 前置步**而非独立函数——凡经 canon 入口，raw/safe 两形同键，`mixed-id-forms` 类双形分裂坑在源头消除。`CanonId.safe()` 产出存储拼写（`/`→`--`）。

### 4.2 bench 侧是独立 canon 域（刻意不归并）

`bench/py/kernel/idnorm.py::canon_id` 是 trizone 内核的语料身份归一（规格 `spec/bench-trizone.md` §3.7/§3.10.7），**与本件语义刻意不同**：其 canon 定义为「arXiv 铸发拼写」——`math.QA/9703043` → `q-alg/9703043`（registry 知铸发形时），改名 archive 映射只用于归并、绝不改写新拼写；本域则统一到 arxiv.org 301 重定向目标（剥 class、archive 小写，`math.QA/9703043` → `math/9703043`）。差异根源是职责：本域服务「获取与任务 dedup」，bench 域服务「语料身份」（铸发拼写即真相）。另：bench 裸 7 位尾只经 PapersRegistry 解析绝不猜、`idc_from_safe` 只解最后一个 `--`（合法 id 至多一个 `/`，与本域全局 unfold 同效）。两域共享面仅 `safe_id` 编码方向（`/`→`--`）一致——不互通、不归并。

## 5. 接口

```python
def canon(raw: str, *, strict_era: bool = True) -> CanonId: ...   # raises CanonError
def try_canon(raw: str, *, strict_era: bool = True) -> CanonId | None: ...
```

- `CanonError.reason` ∈ `bad_shape`/`bad_month`/`bad_era`/`bad_version`/`unsafe`——需分因文案的调用方自取（`req_base_ver` 把 reason 折进 `ValueError` 文案）；HTTP 建任务入口走 `normalize_arxiv_id`+`valid_id` 平文案，前端同样不逐因渲染（统一格式错）。
- 薄壳三件套（旧签名零变化）：`normalize_arxiv_id(raw) -> (base, ver)`——canon 拒收时回剥离剩件+`None`（保留「任意输入不抛」旧契约，剩件恒过不了 `valid_id`）；`valid_id(base)` 收窄为「已是规范形」判定（canon 成立、无钉版、`str()` 回读等于输入）；`req_base_ver(id, version)` 归一+钉版合并+校验（`version` 实参优先于串内 `vN`）。
- web `canonStrip(raw, strict=false)` 双口径（剥壳单源，校验归调用方叠层）：**loose**=匹配键口径（host `[\w.-]*` 不挡寄生域、无镜像臂、多 `www.doi.org` 臂、只剥尾 `/`——坏输入只是匹配不上，宁宽不漏）；**strict**=提交校验口径（子域点界 + 镜像白名单臂 + 首尾 `/` 同剥）。仍刻意比服务端窄——怪输入留给服务端 400。
- `canonArxivKey`（loose+整串小写）是双侧归一匹配键：`stores/tasks.ts` 的 taskByArxiv/preflight、`citations.ts::canonRefId` 同键两名——历史落库行保留 class/大小写、新落库是 canon base，两侧都过本键才比。

## 6. 未落地清单

- 设计稿原预想的「bench `canon_id`/`safe_id` 归并进本件薄壳」未发生且已被取代——trizone 内核 `kernel/idnorm.py` 是刻意独立的第二 canon 域（§4.2），非缺陷。
- `ARXIV_ID_FIND_RX` 的 bench 侧消费点接线（booster/iclr_map/corpus_hot/_layoutqc 等已知点，`fetch.py` 注释面挂账）未完成。
- DOI/S2 等非 arXiv 文献 id 的统一 parse（`parse_paper_ref` 式三臂）不在本件范围，未 spec 化。

判例实证（301/404 实录、官方标识符规则、manifest 双形普查、取证→落地链路）见 `research/arxiv/2026-09-22-id-canon-probes.md`[^canon-probes]。

### 参考文献

[^canon-probes]: TeXlate 调研档案 `research/arxiv/2026-09-22-id-canon-probes.md`：canon 契约的远端行为实录与本仓语料普查。
