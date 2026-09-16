# share-texlog-audit — share.py + texlog.py 交付

> 2026-09-17 收口。落地 `86e4761`（share.py + texlog.py + test_share.py + test_texlog.py，+201/-26）。leader 复核 `-k "share or texlog"` 174 绿。探针 `tmp/share-texlog-audit/`（gitignored）。

## 已修

1. **share.py pack_share TOCTOU + 双读**（现 L214-238）：原 `read_bytes()` 哈希后 `zf.write()` 重读文件——实证探针（read_bytes patch 后篡改磁盘件）复现：manifest 记旧 sha256/bytes、成员是新字节 → 产出自相矛盾包（unpack 自己 size mismatch）。修法：stat 早拒大件 → 单读 blob → len(blob) 复核 → 同一 blob 进 manifest 对账 + `zf.writestr` 成员。顺带 IO 减半（原 stat+read+write 三次访盘 → 两次）；成员 mtime/perm 元数据变化无消费端依赖（unpack 只用 getinfo size + read）。

2. **share.py `_key_parts` None 语义分层**（现 L150-172）：原 `raw is None` 把「键缺席」与「present-but-null」混为 missing——`pack_share(version=None)` 报错与 `share_key(version=None)`=latest 别名矛盾。修后：整键缺席 → missing error（七键必带不变）；键在场但 null → `_EMPTY_OK`（version/glossary_hash）归一 `""`（JSON null 与 "" 同义），非可空组分 null → "key part empty"（原 `str(None)`→"None" 会静默放行，已堵）。

3. **share.py `share_key` 组分 strip 归一**（L130-138）：直调 `share_key(model=" m ")` 与 manifest 侧 `_key_parts` strip 后派生键分叉（实证不同 key）。现各组分 strip——两入口同口径，边缘空白不进键（存量 key 不变：manifest 侧本就 strip）。

4. **texlog.py `is_project_file` NUL/resolve 防爆**（L156-168）：实证 `is_project_file("/abs/a\x00b.tex", root)` 抛 ValueError（`resolve()` → lstat embedded null）——坏 log 行里 NUL 绝对路径 token 会沿 engine `_scan_error_lines`/l2 `_mark_redline` 的 invalid_utf8 归因面炸 parse。修法：含 NUL token 早归工程（真实路径不含 NUL）+ resolve 包 try/except (OSError, ValueError) 保守归工程（symlink 环同理），与「不可归因不掉红线」原则一致。

5. **share.py unpack_share docstring 收敛**（L395 附近）：「任一步失败 → ShareError」改为「包/校验失败 → ShareError；dest 落盘 I/O 失败抛 OSError」——实证 dest 同名目录冲突抛 IsADirectoryError 是 OSError 非 ShareError，消费端 `_share_lookup` 本就两者都捕。

## 新测试（+16 例，共 85）

- test_share.py: `test_pack_artifact_single_read`（TOCTOU 回归：monkeypatch read_bytes 篡改后包仍自洽 + 每产物恰好一次读）、`test_pack_version_none_is_latest_alias`、`test_pack_missing_key_part_rejected` 参数化扩 version/glossary_hash 整键缺席、`test_pack_null_non_emptyable_key_part_rejected`、`test_share_key_strips_whitespace`、`test_unpack_key_parts_extra_fields_tolerated`、`test_unpack_key_parts_version_null`。
- test_texlog.py: `test_paren_inside_filename_pairs_off`（`a(b).tex` 内层自配对/外层 None 占位）、`test_two_opens_one_line`、`test_double_open_inner_token_is_file`（`((x.tex`）、`test_deep_unclosed_nesting`（2000 层）、`test_missing_char_glyph_before_non_space_not_skipped`（`)x` 假想形留档）、`test_is_project_file_bare_name_with_root`、`test_is_project_file_usertree_inside_root_is_sys`（`root/_texmf` 承重场景）、`test_is_project_file_tectonic_case_sensitive`、`test_is_project_file_nul_token_conservative`。

## 自验

`pytest tests/test_share.py tests/test_texlog.py` 85 绿；`-k "share or texlog or logparse or engine or l2 or fixloop or compile"` 883 绿 1 skip；`ruff check` + `ruff format --check` 四文件全净。唯一失败 `test_fixloop_rules.py::test_every_rule_has_provenance`（graphic_ext_relax 缺 source_ref）——rules.yaml 数据文件在飞修改，与本 scope 无关（后由 peer `7bbe3d4` 补上 source_ref，已自愈）。

## 未修 + 理由

- 文件名内嵌括号/引号/79 列折行 → 文件不可见但配对不破：docstring 已声明近似语义，测试已钉，不动。
- engine/l2 把错误行自身括号计入栈 vs logparse `file_stack_at(lines, first_i)` 只重放到错误行前：口径差有意（runaway 的 `)` 在 `!` 前一行，两侧都能找回肇事件），仅错误行文本含括号的假想形分叉。
- `file_stack_at(lines, -1)` 负 stop 静默按 `lines[:-1]`：内部调用方不传负值，不加防御。
- index_append 并发：O_APPEND 单行原子，实证 8 线程×50 行零撕裂；malformed 行 skip+warning 已有测试。
- manifest.json 登记为 artifact：sha256 自指不可能，size mismatch 先拒（实证）。
- 性能：1.5MB/40k 行 file_stack_at 重放 115ms，三处消费均线性单遍，无优化需求。

## 外部路由（不在本 scope，附实证）

1. **worker `_build_dual`（worker.py:3208-3218）**：`zh = r["translation"] or ""` 把 `fallback_orig` 行的 src_text（英文原文）写进 dual.json `zh` 位。实证 `validate_pair(en, en)` 对普通散文 ok=True（CJK 占比仅 WARN）→ 消费端 `_share_apply` 计 `matched`/`status=ok` 落英文「译文」；`zh=""`（failed 行）对无占位符简单 src 也过判 → matched + 空译文。partial 包本就允许，但 fallback 段被标 ok 会污染消费端对账统计与 reader 呈现。建议 pack 侧非 ok 行 zh 写 "" 或剔条目 / 消费端 `_share_row` 对 zh==en、zh=="" 判 miss/dropped。
2. **app.py share_pack 端点（约 L1080-1090）**：`except ShareError` 捕 `index_lookup`——但 index_lookup 实际异常面是 OSError/UnicodeDecodeError（函数体不抛 ShareError）→ 非 UTF-8 索引/目录路径 → 500 而非注释声称的 repack 自愈。同段 flat-name 检查漏 NUL：`url` 含 `\x00` 过 flat 检查后 `(out_dir/name).stat()` 抛 ValueError → 500（实证；worker `_share_lookup` 用 `.is_file()` 吞 ValueError 反而安全）。建议捕 `(OSError, UnicodeDecodeError)` + flat 检查补 `"\x00" not in name` 或复用 share 侧 `_name_ok` 判定。
3. **worker `_share_lookup`（L2273-2277）**：捕 `(ShareError, OSError, UnicodeDecodeError)`——ShareError 为冗余（index_lookup 不抛），口径本身正确，仅提示。

## 谓词放宽 scope 追加的裁断

leader 追加的「looks_like_tex_file 放宽 vs engine/l2 局部 pushback 单源化」评估：integration-verify 的 1070 份真实 .log 三方对照（engine/l2/logparse 文件栈零分歧）表明现状口径已收敛；texlog 栈原语保持单源，graphic-token 回填补丁保留在 engine/l2 消费侧（局部机制，不扩谓词面）。五件三点重复 helper（_is_dos_eps/_DOS_EPS_MAGIC/_last_open_graphic_token/_patch_graphic_top/_GRAPHIC_EXTS 在 normalize/engine/l2 三处）维持复制现状——归并需动 normalize 与 engine 的边界口径，收益不匹配。
