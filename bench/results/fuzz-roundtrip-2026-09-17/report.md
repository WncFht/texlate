# fuzz-roundtrip — texlog/unpack/share 三面 fuzz oracle 交付

> 2026-09-17 收口。落地 `1ca09e2`（test_fuzz_unpack.py + test_fuzz_share.py，+1294；test_fuzz_texlog.py 早前由 1d texlog commit d42003a 收编）。44 passed + 6 xfail(strict) 钉住 6 确认缺陷——修复后 XPASS 即报警。探针 `tmp/fuzz-roundtrip/`（gitignored）。

## 确认缺陷（strict-xfail 钉住）→ 路由：share.py 五项 → server-security-sweep（其 #280 正在改 share.py，避同文件双改）；unpack 一项 → 新 fixer

1. **unpack.py mtree 别名谎报** — `_write_entry` ~L201-203 按字面 `rel` 去重 + `_dir_clash` ~L174 不查 resolved 路径：tar `dir e; sym d→e; file d/x.tex=A; file e/x.tex=B` → mtree `d/x.tex` 记 sha(A) 盘上却是 B（穿 kept symlink 祖先写穿）；kind 谎报同理。钉：`test_alias_via_symlinked_dir_lies_in_mtime`。
2. **share.py:300-304** — `json.loads(bytes)` 先 decode：非 UTF-8 manifest 成员抛 `UnicodeDecodeError` 逃逸 ShareError/OSError 契约（`writestr("manifest.json", b"\xbb\x87…")` 复现）。
3. **share.py:387-395 + 291-299** — except 名单缺 `zlib.error`：DEFLATE 流损坏解压中途炸裸 zlib.error 逃逸（覆写成员数据区 8B 复现）。
4. **share.py:415-421** — `ZipFile()` 构造侧 except 缺 `NotImplementedError`（extract_version>MAX_EXTRACT_VERSION 时 _RealGetContents 抛）；成员读取侧名单反而含它，两路径不一致（PK\x01\x02+6B 写 200 复现）。
5. **share.py pack 侧无 manifest 尺寸闸** — contributor/created_at/组分串无上界 → pack 产出自家 unpack 拒收的包（`contributor="x"*2MB` 超 `_MANIFEST_MAX`）。
6. **share.py:431-432** — rename 发布非原子：校验全过后逐件 replace，中段 OSError（dest 既有同名目录）→ 部分发布，与 docstring「零残留」精神相悖（OSError 契约内）。

## 观察项（未钉）

- `unpack_single` stem_hint 超 NAME_MAX → 裸 OSError(ENAMETOOLONG) 逃逸（tar 路径降级 reject_io，single 不降级）；调用方 fetch.py:614/worker.py:1470 本 catch OSError——低危不一致。
- hardlink 链单遍物化序依赖（h2→h1 先于 h1→f 声明 → h2 dangling）——docstring 语义内，已用通过性测试钉住与 GNU tar 全序解析的差异。
- 良性核实：tar 恰块界截断接受、PAX 坏 UTF-8 名→reject_path、zip 谎报 file_size→BadZipFile→ShareError 均正确。
- leader 早前转的 symlink-loop ELOOP 已定性并修 oracle（resolve() 撞环路径）——本轮 25 passed + 1 xfail 内已含其处置。

## 覆盖面

- test_fuzz_texlog：栈深==括弧余额、popped==有效闭括弧数、file_stack_at==前缀重放、missing-char 行栈中性、脏输入 never-raises、具名帧⊆token、60k 括弧线线性。
- test_fuzz_unpack：mtree↔盘上实况全一致（成员唯一、落点不出 dest、赢家 kind/sha 相符、无 phantom）、files/mtree 逐字段重构全等、告警前缀白名单、单异常面。
- test_fuzz_share：manifest 七组分矩阵（700 例）+ 产物集边界（400 例）+ 篡改 unpack（manifest 700+字节 500）→ ShareError 或逐件 sha 对账 + 失败零残留 + share_key iff-pipe oracle（3000 例独立重算）。

## 自验

六相关文件 297 passed + 6 xfailed；三 fuzz 文件 ruff check/format 全净。
