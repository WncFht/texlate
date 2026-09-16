# app-boundary-fix — app.py share_pack 异常面 + 请求体闸交付

> 2026-09-17 收口。落地 `1d1ad8d`（app.py + test_share_postpack.py + test_app_endpoints.py，+125/-21）。leader 复核 130 绿。**双归因**：同 commit 含 dedupe-pass 在飞 hunks——app.py 删本地 `_NEW_ID_RE`/`_OLD_ID_RE`/`_LOCAL_HOSTS`/`_is_valid_arxiv`，直引 `fetch._valid_id` + `client._LOOPBACK_HOSTS`（两供应名 HEAD 均已存在，commit 自洽）。探针 `tmp/app-boundary-fix/probe.py`。

## 修 1 — share_pack index 异常面 + NUL flat 漏检

- `src/texlate/server/app.py:1105` — `except ShareError` → `except (OSError, UnicodeDecodeError)`。机理：`index_lookup`（share.py:472-502）函数体不抛 ShareError——FileNotFoundError→None、其它 OSError（perm/EISDIR/ELOOP）与整文件 UnicodeDecodeError 上抛、坏 JSON 行内部跳过。原捕获是死面：非 UTF-8 索引实证 →500。按「真不抛则删」收成二件套（与 worker-share-fix 删 _share_lookup 冗余 ShareError 同向）。
- `src/texlate/server/app.py:1115-1120` — flat 检查补 `"\x00" not in name`。机理：`url` 含 `\x00` 过旧检查后 `stat()` 抛 ValueError("embedded null byte")（不属 OSError）→500；worker `_share_lookup` 靠 `.is_file()` 吞 ValueError 才安全。未复用 share.py `_name_ok`：跨模块私有 import 味重，且其 NAME_MAX 分支此处非承重（>255 名 stat→ENAMETOOLONG OSError 已被捕获走 repack）——NUL 是唯一逃逸类，内联最小修。

## 修 2 — 请求体流式字节闸（multipart + JSON）

- 新增 `_cap_request_body`（app.py:173-198）：包装 `request._receive` 计数，累计 >`UPLOAD_CAP+_MULTIPART_OVERHEAD` → `_ApiError(413, upload_too_large)`。选 receive 层而非整读缓冲：`stream()`/`body()`/`form()` 全经 `self._receive`，一处拦截止全部体消费方且保持流式（文件字段仍 spool→磁盘，peak RAM 不变 ~1MB）；`_body` 回填/重建 Request 两案都要先整读体，会给合法 80MB 上传加 ≥80MB 常驻 RAM。两处 `request._receive` 私有写 noqa SLF001 注明（starlette 无公开包装口）。
- `_parse_multipart`（app.py:215）precheck 后装闸——无 CL（chunked/HTTP2）时 str 字段不再无界进 RAM；文件字段既有 UPLOAD_CAP 累计闸语义不动。
- `_read_body`（app.py:566）同闸——顺手收同类面：JSON 端点 `request.body()` 原亦无界（P4 实证修前 80KB chunked 正常 202）。错误面沿用 upload_too_large 统一词表。
- 未用 starlette 1.6 `request.form(max_part_size=)`：只限单 str part 且越界产 400 非 413，不约束总体/spool 磁盘面；总体闸已含 str 上界。

## 实证（修前→修后）

- P1 index 非 UTF-8：500→200（repack 自愈，warning 留痕）
- P2 url 含 \x00：500→200（miss→重打，新行 last-wins 盖坏行）
- P3 chunked+80KB str 字段（CAP=16）：400（体全吞后缺 file）→413
- P4 chunked+80KB JSON（CAP=16）：202→413

## 测试清单

- tests/test_share_postpack.py 新 `TestIndexDegraded`：test_index_non_utf8_repacks、test_index_nul_url_repacks
- tests/test_app_endpoints.py：test_chunked_text_field_bounded_413、test_chunked_json_body_bounded_413

## 自验

`pytest -k "app or share or upload or multipart"` 318 绿（test_texlog.py 因 peer 在飞改 texlog.py 收集失败，--ignore 划出）；`ruff check`+`format --check` 三文件净。

## 夹带/旁证

- 在飞碰撞：dedupe-pass 在 app.py 删 `_NEW_ID_RE`/`_LOCAL_HOSTS`/`_is_valid_arxiv`、直引 `_valid_id`/`_LOOPBACK_HOSTS`；其 xlat.client import 行未排序顺手归位（同一行重排，无逻辑改）。
- 既有 flaky：tests/test_server_upload.py::test_blob_persisted —— `_epub()` 两次调用跨 DOS mtime 2s 粒度即字节不等（index 10 diff），单跑 3/3 过——记档 backlog。
- 未修残余：index.jsonl 若是**目录**，lookup→OSError 捕获→repack→publish 时 `index_append` 对目录 open("a") 仍 IsADirectoryError→500——目录态无法自愈（rmtree 越界），500 属诚实面，未动。
