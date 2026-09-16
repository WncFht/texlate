# share-audit — share 生态安全+健壮性残余审计

> 2026-09-17。scope：`share.py` 全文件、`cli.py` share 段、`app.py`/`worker.py` share 端点/函数段、`tests/test_share*.py`。84 share 测试绿、ruff 净。

## 处置清单（已修，6 项）

1. **`cli.py share_unpack` — 包文件名逃逸（中）**：`"...share.zip".removesuffix(".share.zip")` → `".."`，`dest = cwd/".."` 把产物写进父目录；`"..share.zip"` → `"."` 直接合并进 cwd（可盖同名文件）。修：剥出的 stem 过扁平校验（`.`/`..`/`/`/`\`/空 → 回退 `share-unpacked`）。已实测构造包确认。
2. **`share.py _name_ok` — NUL/超长产物名 → 500（中）**：manifest artifacts 名含 `\x00` 或 >255B 全过校验 → `_extract_verified` `write_bytes` 炸 ValueError/OSError（非 ShareError）→ `/api/share/import` 500 且孤儿 `tasks/{tid}`。修：`_name_ok` 加 `"\x00" not in name` + `len(os.fsencode(name)) <= 255`（NAME_MAX），统一归 ShareError→400。
3. **`share.py unpack` 异常面缺口（中）**：成员名标 UTF-8 flag 但字节非法 → `UnicodeDecodeError` 在 `ZipFile()` open 炸出（实测确认）；未知压缩方法 → `NotImplementedError` 在读成员时炸出——两者都逃逸成 500。修：open catch 加 `UnicodeDecodeError`；`_read_manifest`/`_extract_verified` read 路径补 `OSError/RuntimeError/NotImplementedError`。
4. **`pack_share`/`share_pack_publish` 并发发布竞态（中）**：`pack_share` 直写终名——并发同键发布会交错撕包、静态托管读者可见半成品；`.share-verify` 固定 scratch 名——并发同任务双发互删校验现场。修：包写临时文件 + 原子 rename；scratch 改 `tempfile.mkdtemp` 唯一目录。8 线程并发压测：0 错、无 .tmp 残留、单包原子可验。
5. **`app.py share/pack` 幂等路径 `hit["bytes"]` KeyError → 500（低）**：index 行缺 `bytes` 字段（手改/敌对 index）即炸。修：改 stat 实际文件（报真值尺寸），OSError 按未命中走重打。
6. **`cli.py share_pack` — `bundle.replace(out)` 跨设备炸栈（低）**：`-o` 指异设备 → OSError traceback。修：`_share_final_move` 用 `shutil.move`（EXDEV 退化 copy+unlink）+ 干净 exit 1。

另：ruff format 顺手收掉了 `worker.py` HEAD 上就未格式化的 `reuse_hit` 摘除 hunk（~:1484，share 邻域，3 行→1 行）。

## 测试新增

- `test_share.py` +4：NUL/超长名参数化拒绝、bad-UTF8 成员名、未知压缩方法成员。
- `test_share_cli.py` +1：`...share.zip` → `share-unpacked` 回退不外溢。

## 抽查判干净的面

- **zip-slip**：白名单抽取 + 扁平名闸；symlink 成员 `zf.read` 返回链接目标字节、`write_bytes` 落成普通文件（实测）；重复 `manifest.json` 成员 getinfo 恒取末位、两读点一致；manifest 自荐为产物需 sha256 自指不动点（不可行）。
- **zip bomb**：`zf.read` 按声明 file_size 截断 + CRC 对账（实测：声明 10B 实际 1MB → BadZipFile）——上界 `_MEMBER_MAX` 256MB + manifest 1MB，无放大。
- **path traversal（pack 端点）**：`task_id` 过 `valid_task_id`（`t_`+16hex 死白名单）；index url 扁平检查覆盖 `/` `\` `..` `.` 空名；Unicode 名在 FS 上按字面（无 NFKC 归一化 → 无绕过面）；`share_key` 七组分 `|` 注入在建键处闸死。
- **manifest 信任边界**：share_key 由 key_parts 重算对账；artifacts 逐成员 size+sha256 对账后才写盘；多余成员忽略（设计文 §4 前向兼容，有测试钉）。
- **reuse_hit 一致性**：写 `_finish_reuse`（worker.py:1636）、读 app.py:945、真跑取源落 `.fetch-done` 后摘除（worker.py:1481）——生命周期闭环，端点只读 options_json 判定。
- **静默吞错**：`JSONDecodeError→{}` 良性（reuse 行的 options_json 由 json.dumps 写出不可能坏）；index 损坏 `log.warning`+重打；`_maybe_share_pack` 失败走 `self._warning` 留痕——无静默。

## 残余观察（未改，按纪律列出）

- **`_parse_multipart`（app.py:189-193）**：Content-Length 缺席（chunked/HTTP2）→ `await val.read()` 全量进 RAM，413 预检被绕——影响 share_import 与 upload 两端点；共享 helper 非 share 专属，建议 owner 改 `val.read(UPLOAD_CAP+1)` 截断读。
- share_import 解包后若抛非 ShareError/_ApiError 异常（如 sqlite3.Error）→ 500 + 孤儿 `tasks/{tid}` 目录。
- verify/append 失败的残包留 out_dir 无 index 行（cosmetic）——不能安全 unlink：并发下同键包可能是别家刚发布的好包。
- `index_append` 并发追加：POSIX O_APPEND 单行小写原子；TEXLATE_SHARE_DIR 若指 NFS 则无保证。
- `index_lookup` 每次全量 `read_text`——append-only 无界增长后是性能点。
- `share_key()`（app.py:973）在 try 外——任务行字段含 `|` 会 500（字段建行时已校验，理论不可达）。
- `options.reuse_hit` 用户可经 options 注入 → 仅自残锁自己打包资格。
- `-o "~/x.zip"`（引号内 tilde）typer 不 expanduser → 建字面 `~` 目录（typer 惯例）。
