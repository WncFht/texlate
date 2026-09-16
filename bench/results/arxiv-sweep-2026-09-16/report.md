# arxiv-sweep — arxiv/ 残余审计（fetch.py 冻结）

> 2026-09-16/17。scope：arxiv/ 全模块（fetch.py 冻结只读）+ test_arxiv_*.py。4 文件小修，217 测试过、ruff 净、vulture 22 条全误报。

## 处置清单（已落盘）

- `arxiv/cache.py:96` — `SourceCache.get` 对损坏 meta.json 原静默按 miss 处理 → `log.warning`（静默重下会烧日预算）；新增 module logger。
- `arxiv/ratelimit.py:148` — `_load` 状态文件损坏原静默干净起步 → `log.warning`（预算/断路器状态丢失可追）；新增 module logger。
- `arxiv/unpack.py:80` — `tex_files` docstring「.tex/.ltx」→ 补 `.latex`（实现本就含）。
- `arxiv/__init__.py:12,64` — `CacheError` 补入公共导出（`SourceCache.commit`/`entry_dir` 会抛，属本层公共异常面）。

## 清点结果

- TODO/FIXME/XXX/HACK：零命中。
- vulture 22 条全误报：dataclass schema 字段（PaperMeta/VersionInfo/WrapperVerdict/SrcResult）、测试消费属性（requests_today/parked_until/stub_files/has_includepdf）、外部消费者（raw_path/extracted_dir 被 worker/cli 用）、DegradeReason.STUB 经测试触达。
- 错误路径：无裸 except、无 print/pdb；失败分支均有 warnings/probed/detail 留痕或 documented-miss 语义（locate 记 unreadable:/cycle:/max_depth:、degrade 全程 probed、unpack 拒绝项全进 warnings）。
- 网络纪律：meta.py 全部流量经 Fetcher.get_url/head_path → _request（同一 retry/Retry-After/jitter/限速桶/断路器/日预算），无旁路 httpx，与 fetch.py 标杆一致。

## 规格对账（docs/06）

一致：§1.2 UA/3.05s/零并发/HEAD/150MB/etag；§1.3 退避表+park 30min 翻倍封顶 2h+预算 180+断路；§2.1 魔数序+wrapper 2KB；§2.2 七项拒绝+casefold+512MB/20k/100MB+stub<100B；§2.3 裁决序；§2.4 八形态+CWD→root→including+jobname.bbl；§3.2 schema；§5 _L2_FIRST 路由。

drift/开放项：

- **§1.4「Atom resolved_version > 缓存 → 标 stale 提示新版」未落**——_head_phase 只比同版 etag，全仓无 stale 路径。产品层职责，记 M2 backlog。
- §2.2「raw/ 目录」实现为 `raw.{ext}` 平级文件——语义等价、meta.json 记 raw_file，勘误级。
- §3.1 批量面（id_list ≤200、OAI ListRecords、DataCite）不在产品模块——M4 范畴与落地注记一致。
- §5 L2 探测序：实现钉版优先（[pin, None, v(latest-1)..v1]）——合理超集。
- unpack `_link` 同名重复 symlink 记 casefold_rename（文件同路径记 dup_member_overwrite）命名小不一致，无功能影响。

## 残余建议（不阻塞）

- `locate._scan_nodes` 对树内 symlink 目标无出树校验——unpack 保证 extracted/ 内全 in-tree；locate 吃任意目录时可读包外文件（内容不出进程，仅污染扫描）。低危留档。
- `degrade` L2 回退内 `resolve_version` 元数据请求不进 probed 轨迹（meta.py:371）。
- `sniff` oversized 分支 kind 暂记 TAR（注释自承「种类未定」）——消费方全先查 oversized，无歧义。
