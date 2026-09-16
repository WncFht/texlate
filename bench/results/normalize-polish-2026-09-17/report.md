# normalize-polish — normalize.py + textutil.py 交付

> 2026-09-17 收口。落地 `07633b4`（normalize.py + textutil.py + test_compile_normalize.py + test_textutil_encoding.py，+87/-8）。leader 复核 normalize/textutil/mask/aux/probe 域 159 绿。注意：textutil.py 同 commit 内含 dedupe-pass 在飞的 `BEGIN_DOC_RX` 导出 hunk（独立常量、无害，双归因）；texlog.py 同期被 peer 在飞改名 `looks_like_tex_file`→`looks_like_input_file` + 导出 `DOS_EPS_MAGIC`/`is_dos_eps`（单源化由 peer 实施中），本批不涉。

## 修复（4 处，均实证后改）

1. **textutil.py cp54936 死链**——cp54936 是 GB18030 的 Windows codepage 号，但三重断头：5 位过不了 `cp\d{3,4}` fullmatch、`codecs.lookup("cp54936")` Python 未注册、`_CODEPAGE_RX \d{3,4}` 把 `CodePage: 54936` 截成 `5493`。实证后果：声明 `!TEX encoding=cp54936` 的真 GB18030 文件 declared=None → CJK 声明先验丢失 → detector 误判 **cp1251**。修法：`_DECLARED_CODECS` 加 `"cp54936": "gb18030"`（三条声明路径齐归一）；`_CODEPAGE_RX` → `\d{3,5}`；`_CJK_DECLARED` 删 "cp54936"（归一后该名永不可达，死项）；`_declared_codec` 删死 fallback map `{"cp936":"gbk","cp950":"cp950"}`（两键 lookup 恒成功，except 永不到达）。

2. **normalize.py `_sanitize_ps_comments` \r 腐蚀**——`decode_tex` 的 `_eol_norm` 把注释行尾 `\r` 改写成 `\n`：CRLF EPS 净化后行尾字节被改且 join 出多余空行。实证 `caf\xe9 fig\r` → `caf\xc3\xa9 fig\n\n`。修：剥尾 \r 转码后拼回。

3. **normalize.py `prepare_legacy_latin_fonts` 悬空改写**——documents 判定 `\\documentclass\b` 宽于注入定位 `\\documentclass...{`：无参 documentclass 文件计入 documents 但注不进定义块，`\usefont` 改写 `texlate-ptm` 后定义悬空（实证重现）。修：判定正则与注入同形。

4. **normalize.py `_transcode_one` 死防御**——`(verdict.encoding or "")`：EncodingVerdict.encoding 恒非空 str，去 `or ""`。

## 测试

tests/test_textutil_encoding.py +test_gbk_declared_cp54936（三路径归一）；tests/test_compile_normalize.py +test_sanitize_ps_comments_crlf_preserved +test_legacy_latin_fonts_no_dangling_rewrite。

## 死角扫描其余结论（确认活/良性，未动）

- `dos_eps_skipped` 写→读一致：normalize 写入，engine.py:249/298 + validate/l2.py:326/417 消费降级，texlog.py:197 引用——活。其余 ledgers 测试断言+worker rec 落账——活。
- `JUNK_FILE_STUBS["aipcheck.tex"]` 与 fixloop rules.yaml 条目逐字同文核对 ✓。
- `sniff` 截断判定 `any(高字节 in prefix)`：能走到 EOF 报错 ⇒ 前缀已合法解码 ⇒ 高字节必属合法多字节序列——逻辑正确。
- `_decode_high_run` `or byte.decode("latin-1")`：latin-1 恒成功的死防御，无害留。
- 良性边角未动：`use_bundled_bibliography` 的 `startswith("..")` 对 `..foo/` 隐藏目录误伤（保守方向）；仅 `.tex` 跑 bbl 臂（.ltx 漏=保守）；`_try_shadow` 闭包丢 classes（.sty 内 LoadClass 罕见）；无后缀主文件不进手术面（TEX_SOURCE_SUFFIXES 在 mask.py，scope 外）。

## fallback_unverified（任务3）

不在本域。位在 e2e.py:746 + worker.py:3017，语义「L2 回落原文+重 splice 后未再编，fixloop 代验」。实证：该位为真时源树已改但编译产物对应 res2（重编仍非 clean 那次）——stale-PDF 是否照发属 worker 下游裁决面，产品裁决项未动。

## 自验

pytest 文件级：normalize/textutil/mask/aux/probe 域 180 绿 + e2e_mock/arxiv_sniff/l0/l2 下游 109 绿；ruff check+format 净。注：test_texlog.py 收集期 ImportError（`looks_like_tex_file` 暂缺）系 peer 在飞 texlog.py 改名，与本改动无关。
