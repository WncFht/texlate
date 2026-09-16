# arxiv-texlog-audit — arxiv/ + texlog.py 代码级审计（18 新测试，278+skip 绿）

> 2026-09-17 收口。scope：arxiv/ + texlog.py + 对应测试。三实证探针 `tmp/arxiv-texlog-audit/probe{1,2,3}.py`（mock httpx 不打真 arxiv）。`pytest -k "arxiv or texlog"` 278 passed/1 skipped（corpus_v2 不在场既有守卫）；ruff 双净。

## 修复清单

### fetch.py
- `_CD_VER_RE` 加 IGNORECASE：HEAD 回 `arXiv-2001.00001V2.TAR.GZ` 大写时 resolved_version 丢失误判 unresolved_version。
- `normalize_arxiv_id` 版本 `int()>=1`：`v0`/`v00` 不再当钉版（非法 id 统一拒），`v01`→v1。
- `_request` docstring 写明只重试 TransportError/OSError（DecodingError/TooManyRedirects 确定性立即上抛不烧日预算）。
- `_across_hosts`/`get_src` 外层/`_head_phase`：catch 放宽 `httpx.RequestError`——确定性客户端失败跨 host failover 归 ERROR，不炸穿契约。
- `head_src`/`get_src`：`ver<1`→ValueError（truthiness 让 `version=0` 静默按最新版取）。
- `acquire_source`：bad-input 闸门合并 `bad_id:`/`bad_version:`→ERROR。

### meta.py
- `_get`/`_head`/degrade 内层 catch 同放宽 RequestError；`degrade` 先算 ver_req 再校验覆盖 `version=0`/`idv0` 两入路。

### cache.py
- `_SAFE_GLOB_ID` 白名单 + `find_versions` 拒 `..` 段：`Path.glob` 不沙箱会逸出缓存根。
- `get`/`commit`：meta.json 非 dict → get 记 warning 按 miss、commit 抛 CacheError（原 AttributeError）。

### unpack.py
- `_CTRL_RE` 成员名/linkname 控制字符全拒（`\t`/`\n` 是 POSIX 合法文件名片段但破坏 files.txt/mtree.txt TSV 结构）。
- `member_index: set[str]` 成员存在判 O(1)，替 `_write_entry` 无条件 O(n) 列表重建（20k 成员包热点）。
- 新 `_dir_clash`：tar 病态成员序（file-then-child、symlink 盖隐式目录）从整包流产降级为成员级 `reject_dir_clash` 告警跳过。

### _texutil.py / locate.py
- `strip_comments(keep_verbatim=False)`：verbatim 族环境体一并遮盖。
- `FileNode.scanned`：documentclass/begin_document/refs/plain-context 判定全从 scanned 取——verbatim 体内的 `\documentclass`/`\input`/`\bibliography` 是字面量，原产生假候选与假边。`check_pdf_wrapper` 仍用 `.stripped`（计文本字节要字面量）。

### texlog.py
**零缺陷**：全无状态函数，栈由消费方各持；Missing-character 跳过逻辑正确；`_SYS_TREE_RX` 先于根判定有意。

## 新测试（+18）

fetch +7 / unpack +5 / locate +3 / meta +3（v0 归一化、version=0 拒、DecodingError failover 分类、重定向环、cd 大小写、非 dict meta、`..` 不逸出、控制字符拒、dir clash、verbatim 假候选）。

## 未修项（理由记档）

- RateLimiter/Fetcher 无锁——消费方串行，无并发调用者，留 caveat。
- `_resolve_bib` 探测 `x.bbl`（jobname.bbl 之外）——pre-erratum 语义并存是取舍，收窄可能引入 unresolved 噪声，留 leader 定夺。
- `_SYS_TREE_RX` `texmf` 宽段启发式窄面误报——有意启发式。
- httpx.Client 不关闭——进程级单例 caveat。
- Retry-After `max(退避,ra)` 保守偏离规格——保留。
- tar 逐成员读错误降级——未观测到，不修投机项。

## 外部路由

- texlog 栈异常平衡责任在消费方（compile/l2.py、engine.py 各持栈）。
- RequestError 放宽模式若复用到 xlat 网关等建议同口径审查（8dc8844 已同款修过，模式一致）。
