# docs-sync — spec↔impl 对照勘误交付（第二轮）

> 2026-09-17 收口。落地 `eccac1b`（6 docs 文件，+29/-17）。全部 7 项核对（#247-253）完成；结论为「impl 是确认修复/实装补记」类——**无 impl 疑似错项、无存疑待裁**，统一以「勘误 2026-09-17」记法入 spec。（首轮 tools-runbook/web-layer/shared-cache 对齐已随 `6c9d567` 落地，见同目录 report.md。）

## 各文件勘误要点

- `docs/06-arxiv-source.md` §2.2（unpack.py）：拒绝面补 setgid `mode & 0o6000`、控制字符 `[\x00-\x1f\x7f]`+代理区（成员名 reject_path / linkname reject_link 原始形先查）；规范化改 last-wins `dup_member_overwrite` + `casefold_dir` 只告警；新增 `reject_dir_clash` 三向、`reject_io` errno 白名单 {ENAMETOOLONG,ELOOP,EEXIST,ENOTDIR}、corrupt-stream 整包拒（offset 后 512B 非零）、成员 >20k 整包拒 vs size cap 成员级；落盘改 `raw.{tar.gz|gz|pdf|bin}` 单文件；mtree TSV 五列；hardlink `_finish_links` 二遍物化。
- `docs/research/product/shared-cache.md` §3/§4（share.py）：七组分逐组 strip + `_EMPTY_OK`={version,glossary_hash} JSON null≡"" + 缺一拒；`pack_share` 单 `read_bytes()` 双用（TOCTOU 消灭）+ 原子 rename + `_MEMBER_MAX` 256MB；`unpack_share` 校验序 + `_name_ok` 扁平白名单 + 只抽登记成员免 zip-slip + dest 临时目录全对账 rename。
- `docs/research/product/web-layer.md`（server）：retry 状态守卫先于 mutation + needs_auth 401 + body 白名单 400 + main 变更清理面（DELETE chunks + rmtree + delete_file + resolve 限界 unlink）；reader 404 双条件 + `view` 仲裁；`_invalidate_splice` + `_SPLICE_STALE_KINDS` 五件套 + `_opt_int`；`--port` 双入口闸；SPA `_SpaFiles(html=True)` 整目录挂载实装漂移（index no-cache / assets immutable / TEXLATE_SPA_DIR）；babeldoc start_new_session + killpg→proc.kill + errors deque(64)。
- `docs/08-translate-compile.md`：L2 `_FILE_LINE_RX` 扩展名放宽 `[A-Za-z0-9_-]{1,10}`（loop1 白名单漏 586 真错含 3 例假干净）+ `_NONERR_FILELINE_RX` + `eof_file` 字段（`_EOF_POP_WINDOW=16`）；TABLE_FITTING 出分支统一判；`_BEGIN_DOC_RE` 同锚 search+split；§4.3 红线两层类集并列实集复核 blockquote + `_MISSING_CHAR_RX` 双形态 + dos-eps 降级尾挂；§4.4 `allow_net` 双实现 + `_kill_tree` 触发面扩到 BaseException。
- `docs/research/latex/doc-formats.md`（epub）：member_path unquote-先-raw-后；mimetype 缺省兜底；`owner.name=="nav"` 受限容器分支克隆 landmark；`safe_language` `[\w-]+` fullmatch 防 XML 注入；PUA 哨兵 `{i}`。
- `docs/10-benchmark-suite.md`：B5 构建方法补 `d240b43` 单源化注记；Mode C 删「待跑」（pipeC 双臂已跑）+ pipeB -tec 臂补记；Mode D n100 已跑。

## 范围外

docs/09（语料 spec）无本轮改动面未动；HANDOFF-2026-09-16 为 point-in-time 交接不回改。遗留 `tmp/fix_pua.py` 一次性脚本（gitignored，可弃）。
