# arxiv-resid-audit — arxiv 获取层（unpack/cache/meta/ratelimit）交付

> 2026-09-17 收口。落地 `749fab8`（arxiv/{unpack,cache,meta,ratelimit}.py + test_arxiv_{unpack,meta,ratelimit}.py + test_arxiv_cache.py 新建，+533/-38）。leader 复核 `-k "arxiv or fetch"` 307 绿 1 skip。探针 `tmp/arxiv-resid-audit/`（gitignored）。

# arxiv-resid-audit 报告（unpack/cache/meta/ratelimit + tests）

scope：`src/texlate/arxiv/{unpack,cache,meta,ratelimit}.py` + `tests/test_arxiv_{unpack,meta,ratelimit,cache}.py`。locate.py/fetch.py 仅作接口参照，未动。

## 已修清单（file:line + 机理 + 修法）

### unpack.py（重写面最大）

1. **非 UTF-8 成员名/linkname 落盘后炸 manifest** — `_norm_member` unpack.py:120、`_link` 网关 unpack.py:368-375。机理：tarfile surrogateescape 把 raw 字节名解成代理区码点，POSIX 能落盘，但 `write_manifest`/`meta.json` 写 utf-8 时 UnicodeEncodeError 整包流产。修法：新增 `_SURROGATE_RE`（:52）按路径非法一并 `reject_path`/`reject_link`；告警文本走 `_safe()`（:109-111，backslashreplace）保证 warnings 自身可编码。

2. **tarfile 静默截断 → mtree 谎报完整** — `run()` unpack.py:244-246。机理：实证 getmembers() 遇坏 checksum 头**不抛**（errorlevel=2 无效），静默停枚举，`tf.offset` 停在终止块。修法：检查 offset 处首个 512B 块——全零=正常 EOF 标记（真实包 9702009 标记后有 junk 尾，属正常形态）；非零=无法解析的头、其后成员全丢 → `UnpackError("corrupt member stream at offset N")`。

3. **成员级 IO 病态整包流产** — `_file_member` unpack.py:307-313、`_dir_member` :353-360、`_link` :390-399、`_finish_links` :423-429/:433-439。机理：PAX longname>255B（ENAMETOOLONG）、dangling symlink 作父级（EEXIST/ENOTDIR）、自环链接父级（ELOOP）等纯输入可构造的 errno 直接炸穿 run()。修法：`_MEMBER_ERRNOS` 白名单（:55-57，ENAMETOOLONG/ELOOP/EEXIST/ENOTDIR）→ 成员级 `reject_io:{rel}:{errno}` 告警跳过；ENOSPC/EIO 等全局错仍上抛。`_dir_member` mkdir 失败回滚 `seen` 登记（:358）。

4. **last-wins 被 hardlink 延迟物化破坏** — `_drop_pending` unpack.py:317-320，挂点 :304/:332/:385。机理：实证 `[hardlink x→y, file x, file y]` 产出 x=y-content——`_finish_links` 无条件物化压过后到成员。修法：file/dir/link 每条后到声明先 `_drop_pending(rel)` 清同名 pending hardlink 元组。

5. **symlink 重复名处理与 file 不一致** — `_link` unpack.py:384-411。机理：原实现无条件 `_unique_rename`，精确重名也产 `x~c2` 幽灵链接且旧链接残留（盘上两条活链、mtime 漂移）。修法：与 file 同走 `_claim`（精确重名→`dup_member_overwrite` last-wins、casefold→`~cN`）；symlink 覆盖同名 file 成员时 purge mtree 旧条目（:402-404），否则 mtree 把盘上 symlink 记成 file。

6. **dir 成员压过同名 file 静默幂等** — `_dir_member` unpack.py:347-351。机理：`file x` 在前 `dir x` 在后原路径静默 return，无告警。修法：`target.exists() or is_symlink()` → `reject_dir_clash`，与 file-over-dir 对称（先到者保）。

### cache.py

7. **find_versions glob 注入** — cache.py:87。机理：`arxiv_id="/etc"` → `root.glob("/etcv*")` 绝对模式抛 NotImplementedError；`a*?`/`a[bc]`/`..` 等元字符产生意外匹配。修法：起点 `/` 直接返回空（与既有 `..`/空串/元字符检查同闸）。

8. **commit 备份清理留 .old-* 残渣** — cache.py:155-158。机理：dest 位被散文件占用时 rename 备份成 `.old-{uuid}` 后无条件 `shutil.rmtree`——对文件静默失败，残渣永留。修法：`is_dir() and not is_symlink()` 分流 rmtree，否则 `unlink(missing_ok=True)`。

### meta.py

9. **OAI 版本史信文档序 + v0 成立** — meta.py:207-218。机理：`versions[0]`/`[-1]` 取 published/updated，乱序 feed 会颠倒；`v0` 进 parsed 使 `has_version(0)`/pin=0 成立（版本从 v1 起）。修法：循环滤除 `not nv.isdigit() or int(nv)<1`，再 `tuple(sorted(parsed, key=v.version))`。

### ratelimit.py

10. **文档缺口（不改行为）** — ratelimit.py:13-14。实证：monotonic 无法跨重启持久化（必须用墙钟，NTP 回拨代价已记）；两实例同 state 文件 lost-update（3 请求记 2）——记明单写者假设，不加锁（fetch 路径本就单实例）。

## 新测试（+24）

- `test_arxiv_unpack.py` +10：非 UTF-8 名（ustar raw 0xE9 头注入）、坏头中途截断、dup symlink last-wins、symlink-over-file mtree 一致、hardlink 不反盖、后到 hardlink 物化、longname reject_io、dangling-symlink 父级 reject_io、dir-over-file warn、surrogate linkname
- `test_arxiv_meta.py` +1：乱序版本史 + v0 滤除（published/updated 取真值）
- `test_arxiv_cache.py` 新建 10：find_versions 排序 + glob 注入全家（`/etc`/`a*?`/`a[bc]`/`a/../b`/`..`/``/NUL）、get miss/损坏/非 dict/逃逸、get_latest 跳过坏 meta、commit last-wins 无残渣、stray-file dest、meta 缺失/非对象 CacheError、旧式嵌套 id
- `test_arxiv_ratelimit.py` +3：parked acquire 不烧预算、406 计 strike、5xx 中性（不 strike 不 reset）

## 自验结果

- `uv run pytest tests/ -k 'arxiv or fetch'` → **306 passed, 1 skipped**（10.3s；corpus 项 `test_unpack_corpus[9702009]`/`[0203009]` 单独 PASSED 复核过 junk-tail 不误报）
- `uv run ruff check`（8 文件）→ all clean；`uv run ruff format --check` → 8 files already formatted
- 探针实证：`tmp/arxiv-resid-audit/probe{1_unpack,2_rest,3_tail}.py`（gitignored）

## 未修 + 理由

- **gz-in-tar 嵌套不解**：规格（docs/06 §2.2）未覆盖 nested gunzip，自加会引入解压炸弹面——sniff 层已把 tar.gz 外层解开，成员内 .gz 按普通文件落盘是对的。
- **symlink 环不预检**：keep 的 in-tree symlink 互相成环只在消费侧 OSError(ELOOP)，locate.py 已有 OSError 兜底——预检要维护全图，不值。
- **hardlink→symlink 目标保守拒物化**（`src.is_symlink()` → dangling）：物化成「复制链接目标内容」是另一种合理口径，但现口径更简单且告警留痕。
- **崩溃残留 `.staging-`/`.old-`** 无 sweeper：启动清扫属 cache 新功能面，超出「修缺陷」范畴，残留无害（下次 commit 同 key 正常）。
- **`get()` 不交叉校验 meta.arxiv_id vs 目录名**：调用方写入侧保证一致，读取加校验是防御纵深非缺陷。
- **cache `_save` 磁盘满 OSError 上抛**：调用链上层按传输重试处理，语义可接受。
- **ratelimit 墙钟/单写者**：见已修#10，记档不改行为。

## 外部路由

无——审计中核实的 locate.py OSError 兜底等均在既有口径内，未发现 scope 外缺陷。
