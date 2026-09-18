r"""normalize.py 对抗 fuzz——随机工程树 × 字节载荷矩阵 + 性质不变量。

覆盖臂：``normalize_engine`` 文本手术 / ``normalize_project`` 全树编排
（编码转码、aux 截尾整形、PS 注释净化、atend bbox 改写、junk stub、
bbl 替换、路径 rebase、violation 审计、kpse 遮蔽）。kpsewhich 遮蔽臂在
性质循环里一律关停（host 依赖、非确定性），由独立钉测试覆盖。

核心不变量：

- ``normalize_engine``：返回 str、幂等（``f(f(x)) == f(x)``）、删除类
  编辑行数不减、xelatex/tectonic 文档源输出可见面上无 pdfTeX 输出控制 /
  inputenc/fontenc / CJK 环境 / 非法驱动 token（遮盖区命中属合法残留）；
- ``normalize_project``：任意字节载荷不炸；写回件必 strict-UTF-8；
  二进制 allowlist / 软链 / DOS-EPS 魔数件逐字节不动；隐藏路径件
  （``.git`` 目录、``.dotfile``）非手术面一律不动；
- ``.aux`` 系中间产物：在场 ⇒ 空文件或 ``\n`` 收尾（截尾整形）；
  缺席 ⇒ 落 ``purged_intermediates``；
- ``aipcheck.tex`` 逐名 stub（区分大小写；须带垃圾签名，无签名撞名件放行）；
- PS 臂：行数不减；数据段与非注释行逐字节保留；atend 占位有实值
  时头行改写为末个实值；
- stats：键在已知台账集内、JSON 可序列化、台账相对路径排序去重；
- **幂等**：二跑 ``rewritten == 0``、零改写型台账、全树字节同
  （``dos_eps_skipped``/``encodings`` 是扫描报告，允许复现——后者
  二跑时 basis 只能 strict-utf8）。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng

from texlate.compile import shadow
from texlate.compile.mask import TEX_SOURCE_SUFFIXES, visible_tex
from texlate.compile.normalize import (
    JUNK_FILE_MARKERS,
    JUNK_FILE_STUBS,
    normalize_engine,
    normalize_project,
    rebase_project_paths,
    source_path_violations,
    use_bundled_bibliography,
)
from texlate.compile.transcode import (
    AUX_BIB_SUFFIXES,
    BINARY_SUFFIXES,
    INTERMEDIATE_SUFFIXES,
    PS_GRAPHIC_SUFFIXES,
)
from texlate.textutil import decode_tex, sniff_tex_encoding

if TYPE_CHECKING:
    import random
    from collections.abc import Mapping

_DIR = object()  # 目录占位（rglob 只见文件，断言其存活即可）
_LINK = object()  # 软链占位——目标在 root 外，断言写不穿

#: 发生器概率常量（PLR2004：阈值字面量一律提名）。
_P_SOUP = 0.30
_P_SYMLINK = 0.05
_P_DIR = 0.05
_P_BBL_BAD = 0.35
_P_BIB_PRESENT = 0.5
_P_BBL_PRESENT = 0.6
_P_REBASE_TARGET = 0.3
_P_TRIM_KEEP = 0.5
_P_BIBLIO = 0.35
_P_CRLF = 0.2
_P_DATA_SECTION = 0.4
_P_ATEND = 0.35
_P_TRAILER_VAL = 0.8
_P_BAD_COMMENT = 0.5
_P_TRUNC_TAIL = 0.45
_P_NUL = 0.08
_P_NO_EOL = 0.3
_P_BOM = 0.15

_TREE_ITERS = 220
_ENGINE_ITERS = 500
_PS_ITERS = 300
_AUX_ITERS = 250
_BBL_ITERS = 260
_PATH_ITERS = 300
_MAX_FILES = 14
_NEST_CAP = 200  # 生成器嵌套上界——更深嵌套由 test_group_end_deep_nesting_no_crash 覆盖

_DOS_EPS_MAGIC = b"\xc5\xd0\xd3\xc6"  # oracle 独立常量（spec 魔数）

#: stats 键全集——表外新键即未登记台账，需人工定性。
_STATS_KEYS = frozenset(
    {
        "files",
        "rewritten",
        "encodings",
        "junk_stubbed",
        "transcoded_aux",
        "transcoded_data",
        "sanitized_ps_comments",
        "resolved_atend_bbox",
        "trimmed_intermediates",
        "purged_intermediates",
        "dos_eps_skipped",
        "legacy_latin_files",
        "rebased_paths",
        "package_shadows",
    }
)
#: 二跑必须归零的改写型台账键。
_MUTATING_KEYS = _STATS_KEYS - {"files", "rewritten", "encodings", "dos_eps_skipped"}

# ---------------------------------------------------------------- 载荷池
_LATIN1 = "café naïve Schröder Jörg - ok".encode("latin-1")
_CP1252 = "“quotes” – en-dash … ellipsis €".encode("cp1252")
_GBK = "第一章 标题内容 汉字文本 第二章".encode("gbk")
_BIG5 = "繁體中文標題內容章節".encode("big5")
_SJIS = "日本語テキスト内容章節".encode("shift_jis")
_UTF16LE = "plain text ünïcodé 中文内容".encode("utf-16-le")
_UTF16BE = "plain text ünïcodé 中文内容".encode("utf-16-be")
_OVERLONG = b"before \xc0\xaf overlong \xed\xa0\x80 surrogate"
_C1_BAND = b"ascii " + bytes(range(0x80, 0xA0)) + b" tail"
_NUL_MIX = b"line one\x00mid\x00nul\nlast\n"
_MIXED = "ascii é中".encode() + b"\xe9latin-run" + " more 中文段".encode()
_LONE_CONT = b"text \x80\x81\x82 lone continuation bytes"
_SWP54936 = b"% ----\n%   CodePage: 54936\n" + _GBK + b"\n"
_CP936_DECL = "成段汉字内容标题章节文本".encode("gbk")
_CP936_DECL = b"\\usepackage[cp936]{inputenc}\n" + _CP936_DECL + b"\n"

#: 手术锚点 token——逐行形态，花括号参数内不放换行（多行参丢行缺陷独立钉）。
_TEX_ANCHORS = [
    "\\documentclass{article}\n",
    "\\documentclass[dvips,twocolumn]{article}\n",
    "\\documentclass[pdftex]{scrartcl}\n",
    "\\documentclass[ 10pt ]{article}\n",
    "\\usepackage{amsmath}\n",
    "\\usepackage[utf8]{inputenc}\n",
    "\\usepackage[T1]{fontenc}\n",
    "\\usepackage{inputenc,amsmath}\n",
    "\\usepackage{fontenc}\n",
    "\\usepackage[protrusion=true,expansion=true]{microtype}\n",
    "\\usepackage[expansion=false]{microtype}\n",
    "\\PassOptionsToPackage{dvips}{color}\n",
    "\\PassOptionsToClass{pdftex}{article}\n",
    "\\usepackage[pdftex]{hyperref}\n",
    "\\usepackage[dvips]{graphicx}\n",
    "\\usepackage[dvipdfmx]{graphicx}\n",
    "\\pdfcompresslevel=9\n",
    "\\global\\pdfminorversion=7\n",
    "\\pdfgentounicode=1\n",
    "\\input{glyphtounicode}\n",
    "\\input glyphtounicode.tex\n",
    "\\pdfoutput=1\n",
    "\\pdfoutput = 1\n",
    "\\pdfinfo{/Title (X)}\n",
    "\\pdfinfo{/Author (A) /Subject (S)}\n",
    "\\DisableLigatures{o}\n",
    "\\DisableLigatures[e]{o,f}\n",
    "\\begin{document}\n",
    "\\end{document}\n",
    "\\begin{figure}[!htbpX]\nfig\n\\end{figure}\n",
    "\\begin{figure*}[xyz]\n\\end{figure*}\n",
    "\\begin{table}[Hq]\n\\end{table}\n",
    "\\begin{table}[^@]\n\\end{table}\n",
    "\\begin{comment}\nzz\n\\end{comment}   \n",
    "\\begin{comment}\nzz\n\\end{comment}\t\n",
    "\\begin{verbatim}\n\\pdfinfo{keep}\n% \\usepackage{inputenc}\n\\end{verbatim}\n",
    "\\verb|\\pdfcompresslevel=9|\n",
    "% comment \\pdfoutput=1 \\usepackage{inputenc}\n",
    "\\setlength{\\foo}{12px}\n",
    "\\addtolength{\\foo}{-3.5px}\n",
    "\\includegraphics[width=3.5px,height=20px]{a.pdf}\n",
    "\\includegraphics[angle=90]{a.pdf}\n",
    "\\hspace{2px}\n",
    "\\vspace*{1px}\n",
    "\\rule[2px]{3px}{4px}\n",
    "\\hsize=10px\n",
    "\\parindent 2.5px\n",
    "\\usepackage{CJKutf8}\n",
    "\\usepackage{CJK}\n",
    "\\usepackage{CJKutf8,amsmath}\n",
    "\\begin{CJK}{UTF8}{gbsn}汉\\end{CJK}\n",
    "\\begin{CJK*}{GB}{song}x\\end{CJK*}\n",
    "\\end{CJK}\n",
    "\\usefont{OT1}{ptm}{m}{n}\n",
    "\\usefont{T1}{phv}{b}{n}\n",
    "\\fontfamily{ptm}\\selectfont\n",
    "\\fontfamily{pcr}\n",
    "\\microtypesetup{tracking=true,spacing}\n",
    "\\microtypesetup{kerning=false}\n",
    "\\input{../shared/x.tex}\n",
    "\\input{../../deep/y.tex}\n",
    "\\input{sub/f.tex}\n",
    "\\include{chaps/one}\n",
    "\\openout\\w=out.dat\n",
    "\\openout\\w=|cmd\n",
    "\\openin\\r=/etc/passwd\n",
    "\\openout4=|sh\n",
    "\\includegraphics{|convert}\n",
    "\\input /abs/name\n",
    "\\input{~/home/x}\n",
    "plain words and \\emph{more}.\n",
    "café naïve façade\n",
    "汉字符号混排 αβγ\n",
    "trailing-no-newline",
    "",
    "\n",
    "%\n",
    "{{{}}}\n",
    "\\input{}\n",
    "\\includegraphics{missing}\n",
]

#: 随机 .tex 主体行池之外的脏字节段。
_TEX_DIRT = [b"caf\xe9 latin\n", b"\xd6\xd0\xce\xc4 gbk\n", _C1_BAND, b"\x80 lone\n"]


def _byte_soup(rng: random.Random) -> bytes:
    """字节载荷族：编码族 × 病态字节 × 结构截断。"""
    pool = [
        b"",
        b"plain ascii text\nsecond line\n",
        _LATIN1,
        _CP1252,
        _GBK,
        _BIG5,
        _SJIS,
        _UTF16LE,
        _UTF16BE,
        b"\xff\xfe" + _UTF16LE,
        b"\xfe\xff" + _UTF16BE,
        b"\xef\xbb\xbf" + b"bom utf-8 caf\xc3\xa9\n",
        "完整行 é中文\n".encode() + "末字截".encode()[:-2],  # 尾部半截 UTF-8
        _OVERLONG,
        _C1_BAND,
        _NUL_MIX,
        _MIXED,
        _LONE_CONT,
        _SWP54936,
        _CP936_DECL,
        b"no-eol-tail",
        b"cr only\rline\r",
        b"crlf\r\nline\r\n",
        bytes(rng.randrange(256) for _ in range(rng.randint(0, 96))),
        rng.randbytes(rng.randint(0, 64)),
    ]
    return rng.choice(pool)


def _tex_payload(rng: random.Random, *, allow_biblio: bool) -> bytes:
    """.tex 载荷：锚点 token 序列 + 偶发脏字节段 / 全字节汤。"""
    if rng.random() < _P_SOUP:
        soup = _byte_soup(rng)
        return b"\\documentclass{article}\n" + soup if rng.random() < _P_BOM else soup
    parts = [rng.choice(_TEX_ANCHORS) for _ in range(rng.randint(1, 12))]
    if allow_biblio and rng.random() < _P_BIBLIO:
        name = rng.choice(["refs", "gone", "sub/x", "refs,bib2", ""])
        parts.insert(rng.randrange(len(parts) + 1), f"\\bibliography{{{name}}}\n")
    if rng.random() < _P_CRLF:
        text = "".join(parts).replace("\n", "\r\n")
    else:
        text = "".join(parts)
    if rng.random() < _P_NUL:
        text += "\x00stray\n"
    if rng.random() < 0.15:  # noqa: PLR2004 -- 低概率脏字节段混入
        return text.encode("utf-8", errors="surrogatepass") + rng.choice(_TEX_DIRT)
    return text.encode("utf-8", errors="surrogatepass")


def _aux_payload(rng: random.Random) -> bytes:
    """中间产物载荷：完整行 × 截尾形态（8192 边界、半截多字节、无尾换行、NUL）。"""
    lines = [
        b"\\relax\n",
        b"\\newlabel{a}{{1}{1}{title}{}}\n" * rng.randint(0, 4),
        "中文标签\n".encode() * rng.randint(0, 3),
        b"% comment\xe9\n" if rng.random() < 0.2 else b"",  # noqa: PLR2004
        b"\\citation{k}\n",
    ]
    blob = b"".join(lines)
    if rng.random() < _P_NUL:
        blob += b"\x00nul\x00"
    if rng.random() < _P_TRUNC_TAIL:
        blob += rng.choice(
            [
                "半截行".encode()[:-1],  # 半截 UTF-8
                "半 gbk".encode("gbk")[:-1],
                b"no newline tail",
                b"\\newlabel{b}{{2}{3}{",
                "尾部中文字".encode()[: -rng.randint(1, 4) or 1],
            ]
        )
    elif rng.random() < _P_NO_EOL:
        blob += b"complete-no-eol"
    return blob


def _ps_payload(rng: random.Random) -> bytes:
    """PS 载荷：DSC 头 + 注释行坏字节 + 数据段 + atend/trailer 组合。"""
    if rng.random() < 0.06:  # noqa: PLR2004 -- DOS-EPS 低频
        return _DOS_EPS_MAGIC + rng.randbytes(rng.randint(0, 40))
    lines = [b"%!PS-Adobe-3.0 EPSF-3.0"]
    if rng.random() < _P_ATEND:
        lines.append(b"%%BoundingBox: (atend)")
    else:
        lines.append(b"%%BoundingBox: 0 0 100 100")
    for _ in range(rng.randint(0, 3)):
        bad = rng.choice([b"caf\xe9", b"Schr\xf6der", b"\xd7\xc0\xc3\xe6", b""])
        lines.append(
            b"%%For: " + bad if rng.random() < _P_BAD_COMMENT else b"%%Ok: fine"
        )
    lines.append(b"%%EndComments")
    if rng.random() < _P_DATA_SECTION:
        lines += [
            b"%%BeginBinary: 16",
            b"%BIN" + rng.randbytes(rng.randint(1, 12)),
            rng.randbytes(rng.randint(0, 20)),
        ]
        if rng.random() < 0.8:  # noqa: PLR2004 -- 偶发无 End 闭合
            lines.append(b"%%EndBinary")
    for _ in range(rng.randint(0, 3)):
        lines.append(b"(data\xe9) show" if rng.random() < 0.3 else b"100 200 moveto")  # noqa: PLR2004
    lines.append(b"%%Trailer")
    if rng.random() < _P_TRAILER_VAL:
        lines.append(b"%%BoundingBox: 74 87 587 383")
    lines.append(b"%%EOF")
    sep = b"\r\n" if rng.random() < _P_CRLF else b"\n"
    return sep.join(lines) + rng.choice([sep, b"", b"\n"])


# ---------------------------------------------------------------- 工程树发生器
_TEX_NAMES = [
    "main.tex",
    "a.tex",
    "sub/b.tex",
    "sub/deep.ltx",
    "sp ace.tex",
    "uni码.tex",
    "UPPER.TEX",
    ".dotfile.tex",
    "x.sty",
    "y.STY",
    "pkg.cls",
    "drv.def",
    "cfg.cfg",
    "clo.clo",
    "f.fd",
    ".git/hook.tex",
    ".svn/e.tex",
]
_AUXBIB_NAMES = ["refs.bib", "main.bbl", "x.bst", "sub/r.bib", ".git/left.bbl"]
_INTER_NAMES = [
    "main.aux",
    "main.toc",
    "main.out",
    "main.lof",
    "main.lot",
    "main.nav",
    "main.snm",
    "main.vrb",
    "main.ent",
    ".git/s.aux",
]
_PS_NAMES = ["fig.eps", "g.epsi", "h.epsf", "i.mps", "j.ps", ".git/k.eps"]
_BIN_NAMES = ["img.png", "doc.pdf", "f.tfm", "x.gz", "UPPER.PNG", "y.jbig2"]
_CATCH_NAMES = [
    "notes.txt",
    "README",
    "data.dtx",
    "x.ins",
    ".git/stuff.txt",
    ".svn/aux.dat",
    ".hiddenfile",
    "code.py",
    "weird.suffix9",
    ".config/z.dat",
]
_JUNK_NAMES = ["aipcheck.tex", "sub/aipcheck.tex", ".git/aipcheck.tex", "AIPCHECK.TEX"]


def _gen_tree(rng: random.Random) -> dict[str, object]:
    """随机工程 spec：``rel -> bytes | _DIR | _LINK``。``main.tex`` 恒在场。"""
    spec: dict[str, object] = {"main.tex": _tex_payload(rng, allow_biblio=True)}
    if rng.random() < _P_REBASE_TARGET:
        spec["shared/x.tex"] = b"% shared\n"
        spec["deep/y.tex"] = b"% deep\n"
    if rng.random() < _P_BIB_PRESENT:
        spec["refs.bib"] = b"@article{a,title={t}}\n"
        spec["bib2.bib"] = b"@book{b,title={u}}\n"
    for pool, gen in (
        (_TEX_NAMES, lambda _n: _tex_payload(rng, allow_biblio=True)),
        (
            _AUXBIB_NAMES,
            lambda n: (
                b"\\begin{thebibliography}{9}\\bibitem{k}x\\end{thebibliography}\n"
                if n == "main.bbl" and rng.random() < _P_BBL_PRESENT
                else _byte_soup(rng)
            ),
        ),
        (_INTER_NAMES, lambda _n: _aux_payload(rng)),
        (_PS_NAMES, lambda _n: _ps_payload(rng)),
        (_BIN_NAMES, lambda _n: rng.randbytes(rng.randint(0, 48))),
        (_CATCH_NAMES, lambda _n: _byte_soup(rng)),
        (_JUNK_NAMES, lambda _n: rng.choice([b"\\typein{press}\n", _byte_soup(rng)])),
    ):
        for name in pool:
            if rng.random() < 0.2:  # noqa: PLR2004 -- 每池每名额定概率
                spec[name] = gen(name)
    n_extra = rng.randint(0, 3)
    for _ in range(n_extra):
        spec[f"extra{rng.randint(0, 9)}.tex"] = _tex_payload(rng, allow_biblio=False)
    if len(spec) > _MAX_FILES:
        keep = {"main.tex"}
        spec = {
            k: v for k, v in spec.items() if k in keep or rng.random() < _P_TRIM_KEEP
        }
        spec.setdefault("main.tex", _tex_payload(rng, allow_biblio=True))
    if rng.random() < _P_DIR:
        spec["dirfile.tex"] = _DIR
    if rng.random() < _P_SYMLINK:
        spec["linked.tex"] = _LINK
        spec["linked.txt"] = _LINK
    return spec


def _materialize(root: Path, spec: Mapping[str, object], link_target: Path) -> None:
    """spec 落盘：bytes 写文件、_DIR 建目录、_LINK 建 root 外软链。"""
    for rel, payload in spec.items():
        dest = root / rel
        if payload is _DIR:
            dest.mkdir(parents=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if payload is _LINK:
            dest.symlink_to(link_target)
            continue
        assert isinstance(payload, bytes)
        dest.write_bytes(payload)


def _snapshot(root: Path) -> dict[str, bytes]:
    """全树文件字节快照（软链记链接目标标记，不写穿）。"""
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            out[rel] = b"LINK:" + p.readlink().as_posix().encode()
        elif p.is_file():
            out[rel] = p.read_bytes()
    return out


# ---------------------------------------------------------------- 校验件
def _hidden(rel: str) -> bool:
    """任一路径段 ``.`` 前缀——``_transcode_support_files`` 豁免口径。"""
    return any(part.startswith(".") for part in PurePosixPath(rel).parts)


def _nul_gated(blob: bytes) -> bool:
    """``_transcode_one`` NUL 闸 oracle：含 NUL 且非 utf-16 判定。"""
    return b"\x00" in blob and not sniff_tex_encoding(blob).encoding.startswith(
        "utf-16"
    )


def _check_stats_shape(stats: Mapping[str, object]) -> None:
    """stats 键集/JSON 可序列化/台账相对路径排序去重。"""
    assert set(stats) <= _STATS_KEYS
    json.dumps(stats)
    assert isinstance(stats["files"], int)
    assert isinstance(stats["rewritten"], int)
    shadows = stats.get("package_shadows")
    if shadows is not None:
        for entry in shadows:
            assert set(entry) == {"package", "from", "encoding", "basis"}
    for key in _MUTATING_KEYS - {"legacy_latin_files", "package_shadows"} | {
        "dos_eps_skipped"
    }:
        entries = stats.get(key)
        if entries is None:
            continue
        assert isinstance(entries, list)
        assert entries == sorted(set(entries))
        for rel in entries:
            assert isinstance(rel, str)
            assert not rel.startswith(("/", ".."))
            assert ".." not in PurePosixPath(rel).parts
    enc = stats.get("encodings")
    if enc is not None:
        assert isinstance(enc, dict)
        for entry in enc.values():
            assert set(entry) == {"encoding", "basis", "declared", "note"}


def _check_file_post(  # noqa: C901, PLR0911, PLR0912 — 后缀族分派表即规格序
    root: Path, rel: str, orig: bytes, stats: Mapping[str, object]
) -> None:
    """单件不变量：后缀族 × 隐藏位 × NUL 闸分派后的落盘形态。"""
    path = root / rel
    suffix = PurePosixPath(rel).suffix.lower()
    name = PurePosixPath(rel).name
    if name in JUNK_FILE_STUBS and path.is_file() and not path.is_symlink():
        # stub 覆写先于一切——逐名匹配不限深度/隐藏位（现行口径）；
        # 隐藏件在隐藏路径裁决后可能整体豁免——两种落盘都接受；
        # 名撞护栏：无垃圾签名的同名件按真件放行——不提前 return，
        # 放行≠豁免转码/手术，落普通 .tex 族不变量继续判别
        stub = JUNK_FILE_STUBS[name].encode("utf-8")
        markers = JUNK_FILE_MARKERS.get(name, ())
        if not markers or any(m in orig for m in markers):
            new = path.read_bytes()
            if _hidden(rel):
                assert new in (orig, stub)
            else:
                assert new == stub
            return
        # 放行件不得被垃圾覆写——未动或走正常手术均可，唯不许落 stub
        new = path.read_bytes()
        assert new == orig or new != stub
    if not path.is_file():
        assert rel in stats.get("purged_intermediates", [])
        return
    new = path.read_bytes()
    if suffix in BINARY_SUFFIXES:
        assert new == orig
        return
    if _hidden(rel):
        if suffix in TEX_SOURCE_SUFFIXES:
            # 主环现行口径连隐藏 .tex 也转码——钉「若改写则必 UTF-8」，
            # 裁决后若隐藏件整体豁免本断言仍成立
            if new != orig:
                new.decode("utf-8")
        else:
            assert new == orig  # 转码臂豁免隐藏路径
        return
    if suffix in PS_GRAPHIC_SUFFIXES:
        _check_ps_post(orig, new, rel, stats)
        return
    if suffix in INTERMEDIATE_SUFFIXES:
        if _nul_gated(orig):
            assert new == orig
            return
        assert new == b"" or new.endswith(b"\n")
        new.decode("utf-8")
        if new != orig:
            leds = stats.get("trimmed_intermediates", []) + stats.get(
                "transcoded_aux", []
            )
            assert rel in leds
        return
    if suffix in TEX_SOURCE_SUFFIXES:
        new.decode("utf-8")
        return
    if _nul_gated(orig):
        assert new == orig
        return
    new.decode("utf-8")
    if new != orig:
        aux_family = suffix in AUX_BIB_SUFFIXES
        ledger = "transcoded_aux" if aux_family else "transcoded_data"
        assert rel in stats.get(ledger, [])


_PS_DATA_BEGIN = re.compile(rb"^[ \t]*%%Begin(?:Binary|Data|Document|Preview)\b")
_PS_DATA_END = re.compile(rb"^[ \t]*%%End(?:Binary|Data|Document|Preview)\b")
_BBOX_ATEND = re.compile(rb"^[ \t]*%%BoundingBox:[ \t]*\(atend\)[ \t\r]*$")
_BBOX_VALUE = re.compile(
    rb"^[ \t]*%%BoundingBox:[ \t]*"
    rb"((?:[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[ \t]+){3}"
    rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[ \t\r]*$"
)


def _check_ps_post(  # noqa: C901, PLR0912 — DSC 头区/数据段/注释分派即规格
    orig: bytes, new: bytes, rel: str, stats: Mapping[str, object]
) -> None:
    """PS 臂 oracle：DOS 逐字节不动；行数不减；非注释/数据行逐字节保留；
    atend 占位 + 有实值 ⇒ 头行改写为末实值。"""
    if orig.startswith(_DOS_EPS_MAGIC):
        assert new == orig
        assert rel in stats.get("dos_eps_skipped", [])
        return
    assert new.count(b"\n") >= orig.count(b"\n")
    old_lines = orig.split(b"\n")
    new_counter = Counter(new.split(b"\n"))
    atend_idx: int | None = None
    in_data = False
    keep: list[bytes] = []
    # 头注释块判定与 _resolve_atend_bbox 同口径（空行不打断）
    head_open = True
    for i, raw in enumerate(old_lines):
        stripped = raw.lstrip()
        if head_open:
            if not stripped:
                pass  # 头区空行不打断
            elif stripped.startswith(b"%%EndComments") or not stripped.startswith(b"%"):
                head_open = False
            elif _BBOX_ATEND.match(raw):
                atend_idx = i
                head_open = False  # 只占位一行
        if _PS_DATA_BEGIN.match(raw):
            in_data = True
            keep.append(raw)
            continue
        if _PS_DATA_END.match(raw):
            in_data = False
            keep.append(raw)
            continue
        if i == atend_idx:
            continue  # 头行可能被改写，不入保留集
        if not in_data and raw.lstrip(b" \t").startswith(b"%"):
            continue  # 注释行可被净化改写
        keep.append(raw)
    old_counter = Counter(keep)
    for line, cnt in old_counter.items():
        assert new_counter[line] >= cnt, (rel, line)
    if atend_idx is not None:
        values = [m[1] for m in map(_BBOX_VALUE.match, old_lines) if m]
        if values:
            prefix = b"%%BoundingBox: " + values[-1]
            assert any(
                ln.startswith(prefix) and not ln[len(prefix) :].strip(b" \t\r")
                for ln in new_counter
            )
            assert rel in stats.get("resolved_atend_bbox", [])
    if new != orig:
        touched = set(stats.get("sanitized_ps_comments", [])) | set(
            stats.get("resolved_atend_bbox", [])
        )
        assert rel in touched


# ---------------------------------------------------------------- fuzz 主体
def test_fuzz_project_tree_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """随机工程树 × 全后缀族 × 病态字节：性质循环。

    关停 kpsewhich 遮蔽臂（host 依赖）——NUL 包名逃逸由独立钉覆盖。
    每树断言：无异常、stats 形态、逐件后缀族不变量；然后二跑幂等
    （字节同 + 零改写台账 + encodings 二跑只能 strict-utf8）。
    """
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    rng = fuzz_rng(20261101)
    outside = tmp_path / "_outside_target"
    outside.write_bytes(b"outside \xe9 latin\n\\pdfcompresslevel=9\n")
    for i in range(_TREE_ITERS):
        root = tmp_path / f"t{i}"
        root.mkdir()
        spec = _gen_tree(rng)
        _materialize(root, spec, outside)
        spec_bytes = {
            rel: blob for rel, blob in spec.items() if isinstance(blob, bytes)
        }
        main = rng.choice([None, "main.tex"])
        stats = normalize_project(root, "xelatex", main)
        _check_stats_shape(stats)
        assert stats["files"] == sum(
            1
            for p in root.rglob("*")
            if not p.is_symlink()
            and p.is_file()
            and p.suffix.lower() in TEX_SOURCE_SUFFIXES
        )
        for rel, orig in spec_bytes.items():
            _check_file_post(root, rel, orig, stats)
        # 软链写穿守卫：外部目标逐字节不动；目录占位存活
        assert outside.read_bytes() == b"outside \xe9 latin\n\\pdfcompresslevel=9\n"
        for rel, payload in spec.items():
            if payload is _LINK:
                assert (root / rel).is_symlink()
            elif payload is _DIR:
                assert (root / rel).is_dir()
        once = _snapshot(root)
        stats2 = normalize_project(root, "xelatex", main)
        assert _snapshot(root) == once
        assert stats2["rewritten"] == 0
        for key in _MUTATING_KEYS:
            assert key not in stats2, (key, stats2[key])
        if "dos_eps_skipped" in stats2:
            assert stats2["dos_eps_skipped"] == stats.get("dos_eps_skipped")
        for entry in stats2.get("encodings", {}).values():
            assert entry["basis"] == "strict-utf8"


def test_fuzz_engine_text_matrix() -> None:
    """``normalize_engine`` token 汤：幂等 + 行数不减 + 可见面 token 清除。"""
    rng = fuzz_rng(20261102)
    engines = ["xelatex", "tectonic", "lualatex", "pdflatex", "", "weird"]
    for _ in range(_ENGINE_ITERS):
        parts = [rng.choice(_TEX_ANCHORS) for _ in range(rng.randint(0, 14))]
        if rng.random() < 0.1:  # noqa: PLR2004 -- 浅嵌套结构噪声
            parts.append("{" * rng.randint(1, _NEST_CAP) + "}" * rng.randint(1, 8))
        text = "".join(parts)
        engine = rng.choice(engines)
        doc_source = rng.random() < 0.75  # noqa: PLR2004
        out = normalize_engine(text, engine, doc_source=doc_source)
        assert isinstance(out, str)
        assert normalize_engine(out, engine, doc_source=doc_source) == out
        assert out.count("\n") >= text.count("\n")
        vis = visible_tex(out)
        if engine in ("tectonic", "xelatex") and doc_source:
            assert not re.search(
                r"\\pdf(?:compresslevel|objcompresslevel|minorversion|"
                r"majorversion|optionpdfminorversion|gentounicode)\s*=?\s*\d",
                vis,
            )
            assert not re.search(
                r"\\input\s*(?:\{glyphtounicode|glyphtounicode\b)", vis
            )
            assert not re.search(r"\\pdfinfo\s*\{", vis)
            assert not re.search(r"\\pdfoutput\s*=?\s*1\b", vis)
        if engine in ("tectonic", "xelatex"):
            for m in re.finditer(
                r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}",
                vis,
            ):
                names = {n.strip() for n in m[1].split(",")}
                assert not names & {"inputenc", "fontenc"}
        if engine in ("tectonic", "xelatex", "lualatex"):
            assert not re.search(r"\\begin\s*\{CJK\*?\}", vis)
            assert not re.search(r"\\end\s*\{CJK\*?\}", vis)


def test_fuzz_ps_arm_line_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PS 族后缀随机件：DOS 魔数逐字节不动 + 逐行净化 oracle。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    rng = fuzz_rng(20261103)
    suffixes = [".eps", ".epsi", ".epsf", ".mps", ".ps"]
    for i in range(_PS_ITERS):
        root = tmp_path / f"p{i}"
        root.mkdir()
        (root / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
        )
        name = f"fig{i}{rng.choice(suffixes)}"
        blob = _ps_payload(rng)
        (root / name).write_bytes(blob)
        stats = normalize_project(root, "xelatex", "main.tex")
        _check_stats_shape(stats)
        new = (root / name).read_bytes()
        _check_ps_post(blob, new, name, stats)


def test_fuzz_intermediate_tail_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中间产物截尾整形：在场 ⇒ 空或 ``\\n`` 收尾 + strict-UTF-8；缺席 ⇒ purged。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    rng = fuzz_rng(20261104)
    for i in range(_AUX_ITERS):
        root = tmp_path / f"a{i}"
        root.mkdir()
        (root / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
        )
        name = f"m{i}{rng.choice(sorted(INTERMEDIATE_SUFFIXES))}"
        blob = _aux_payload(rng)
        (root / name).write_bytes(blob)
        stats = normalize_project(root, "xelatex", "main.tex")
        path = root / name
        if _nul_gated(blob):
            assert path.read_bytes() == blob
            continue
        if not path.exists():
            assert name in stats.get("purged_intermediates", [])
            continue
        new = path.read_bytes()
        assert new == b"" or new.endswith(b"\n")
        new.decode("utf-8")


def test_fuzz_bundled_bbl_matrix(tmp_path: Path) -> None:
    """``use_bundled_bibliography`` 在场矩阵 oracle：逐调用语义。

    bbl 缺/无 ``thebibliography`` → 原样；有 bbl + 有缺库 ``\\bibliography``
    → 恰好替换**首个**缺库者为 ``\\input{relpath.bbl}``；relpath 出
    ``..`` → 该命令跳过且后续同样不换（relpath 与 name 无关）。
    """
    rng = fuzz_rng(20261105)
    for i in range(_BBL_ITERS):
        proj = tmp_path / f"b{i}"
        sub = proj / rng.choice(["", "chaps"])
        sub.mkdir(parents=True, exist_ok=True)
        tex = sub / "one.tex"
        names = [rng.choice(["refs", "gone", "x"]) for _ in range(rng.randint(0, 2))]
        text = "head\n" + "".join(f"\\bibliography{{{n}}}\n" for n in names) + "tail\n"
        tex.write_text(text)
        cwd = proj if rng.random() < 0.8 else proj / "elsewhere"  # noqa: PLR2004
        (proj / "elsewhere").mkdir(exist_ok=True)
        for n in set(names):
            if rng.random() < _P_BIB_PRESENT:
                (cwd / f"{n}.bib").write_bytes(b"@x{a,t={1}}\n")
        bbl = tex.with_suffix(".bbl")
        if rng.random() < _P_BBL_PRESENT:
            bbl.write_bytes(
                b"% junk\n"
                if rng.random() < _P_BBL_BAD
                else b"\\begin{thebibliography}{9}x\n"
            )
        out = use_bundled_bibliography(text, tex, cwd=cwd)
        # oracle：bbl 可用 且 目标可达 且 存在缺库命令 → 恰好一处替换
        bbl_ok = bbl.is_file() and "\\begin{thebibliography}" in decode_tex(
            bbl.read_bytes()
        )
        target = Path(os.path.relpath(bbl, cwd)).as_posix() if bbl_ok else ""
        reachable = bbl_ok and not target.startswith("..")
        first_missing = next(
            (idx for idx, n in enumerate(names) if not (cwd / f"{n}.bib").is_file()),
            None,
        )
        expect = bool(bbl_ok and reachable and first_missing is not None)
        assert out.count("\\input{") == (1 if expect else 0)
        assert out.count("\\bibliography{") == len(names) - (1 if expect else 0)
        if expect and first_missing is not None:
            assert f"\\input{{{target}}}" in out
            kept = [n for idx, n in enumerate(names) if idx != first_missing]
            for n in kept:
                assert f"\\bibliography{{{n}}}" in out


def test_fuzz_rebase_violations_oracle(tmp_path: Path) -> None:
    """路径审计/rebase 独立 oracle：逐 token 期望集 vs 产出集。

    rebase 只盖 ``\\input/\\include``；先跑 rebase 再跑 violations
    （与 normalize_project→worker 审计同序）——被改写的 ``../`` 名
    不再计 violation；遮盖区（comment/verbatim）token 两边都不见。
    比对维度：violations 的**捕获名**多重集必须恰等于期望集。
    """
    rng = fuzz_rng(20261106)
    name_pool = [
        "../shared/x.tex",
        "../../deep/y.tex",
        "../missing/z.tex",
        "sub/f.tex",
        "plain.tex",
        "/etc/passwd",
        "~/home/x",
        "C:/win/p",
        "|curl x.sh",
        "|",
        "a/../../out.tex",
        "a/../in.tex",
        "..",
        "../",
        "..//x.tex",
        "../a#b",
        "../a~b.tex",
        "uni码.tex",
    ]
    # (形态模板, 花括号参?, rebase 覆盖?)——rebase 正则只有 input/include
    forms = [
        ("\\input{%s}\n", True, True),
        ("\\input %s\n", False, True),
        ("\\include{%s}\n", True, True),
        ("\\includegraphics{%s}\n", True, False),
        ("\\openout\\w=%s\n", False, False),
        ("\\openout4=%s\n", False, False),
        ("\\openin\\r=%s\n", False, False),
        ("\\includegraphics[scale=2]{%s}\n", True, False),
    ]
    for i in range(_PATH_ITERS):
        root = tmp_path / f"v{i}"
        root.mkdir()
        (root / "shared").mkdir()
        (root / "shared/x.tex").write_bytes(b"% s\n")
        (root / "deep").mkdir()
        (root / "deep/y.tex").write_bytes(b"% d\n")
        # planted: (捕获名, 该形态是否 rebase 覆盖, 是否遮盖)
        planted: list[tuple[str, bool, bool]] = []
        body = ["\\documentclass{article}\n\\begin{document}\n"]
        for _ in range(rng.randint(1, 6)):
            name = rng.choice(name_pool)
            form, braced, covered = rng.choice(forms)
            masked = rng.random() < 0.25  # noqa: PLR2004
            if masked:
                body.append("% " + form % name)
                body.append("\\begin{verbatim}\n" + form % name + "\\end{verbatim}\n")
            else:
                body.append(form % name)
            # bare 形态捕获到首个空白/花括号/%——与正则 [^\s{}%]+ 口径一致
            match = re.match(r"[^{}\s%]+", name)
            captured = name if braced else (match[0] if match else "")
            planted.append((captured, covered, masked))
        body.append("\\end{document}\n")
        (root / "main.tex").write_text("".join(body))
        locs = rebase_project_paths(root, "main.tex")
        expected: Counter[str] = Counter()
        rebased_any = False
        for captured, covered, masked in planted:
            if masked:
                continue
            if covered and _rebase_oracle(root, captured) is not None:
                rebased_any = True
                continue  # rebase 吃掉 → 不再计 violation
            if _expect_violation(root, root, captured):
                expected[captured] += 1
        actual = Counter(
            next(g for g in m.groups() if g is not None).strip()
            for _p, m, _msg in source_path_violations(root, "main.tex")
        )
        assert actual == expected
        assert (len(locs) > 0) == rebased_any
        for loc in locs:
            assert loc.startswith("main.tex:")


def _expect_violation(root: Path, cwd: Path, name: str) -> bool:
    """violation 独立判定：绝对 / ``..`` 越界 / 管道。"""
    if re.match(r"/|~|[A-Za-z]:", name):
        return True
    if name.startswith("|"):
        return True
    return ".." in PurePosixPath(name).parts and not (
        cwd / name
    ).resolve().is_relative_to(root)


def _rebase_oracle(root: Path, name: str) -> str | None:
    """rebase 独立判定：``../`` 剥光后包内同名文件存在 → 期望改写。"""
    if not name.startswith("../") or re.search(r"[\\#{}~]", name):
        return None
    while name.startswith("../"):
        name = name[3:]
    candidate = (root / name).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return name
    return None


def test_fuzz_junk_stub_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """junk 名单逐名 stub：命中件覆写为 stub；非名单/大小写变体不动。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    rng = fuzz_rng(20261107)
    for i in range(80):
        root = tmp_path / f"j{i}"
        root.mkdir()
        (root / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
        )
        name = rng.choice(_JUNK_NAMES)
        blob = rng.choice([b"\\typein{* go}\n", _byte_soup(rng), b""])
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        stats = normalize_project(root, "xelatex", "main.tex")
        if _hidden(name):
            # 隐藏路径整体豁免——stub 也不写，逐字节不动
            assert target.read_bytes() == blob
        elif name == "aipcheck.tex" or name.endswith("/aipcheck.tex"):
            stub = JUNK_FILE_STUBS["aipcheck.tex"].encode("utf-8")
            if any(m in blob for m in JUNK_FILE_MARKERS["aipcheck.tex"]):
                # 带垃圾签名——覆写为 stub
                assert target.read_bytes() == stub
                assert name in stats.get("junk_stubbed", []) or blob == stub
            else:
                # 无垃圾签名——撞名真件放行，不覆写为 stub；
                # 放行≠豁免转码/手术，普通 .tex 路径仍可能改写
                assert target.read_bytes() == blob or target.read_bytes() != stub
                assert name not in stats.get("junk_stubbed", [])
        else:
            # 大小写变体不 stub；按 .tex 正常转码路径
            target.read_bytes().decode("utf-8")


# ---------------------------------------------------------------- 边界钉
def test_empty_and_edge_trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空树 / 空 .tex / 仅 BOM / 单字节 / 不存在 root：零文件不炸。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    root = tmp_path / "empty"
    root.mkdir()
    assert normalize_project(root, "xelatex") == {"files": 0, "rewritten": 0}
    assert normalize_project(tmp_path / "ghost", "xelatex") == {
        "files": 0,
        "rewritten": 0,
    }
    f = tmp_path / "afile"
    f.write_bytes(b"x")
    assert normalize_project(f, "xelatex") == {"files": 0, "rewritten": 0}
    for i, blob in enumerate([b"", b"\xef\xbb\xbf", b"\n", b"%", b"\\"]):
        d = tmp_path / f"e{i}"
        d.mkdir()
        (d / "main.tex").write_bytes(blob)
        stats = normalize_project(d, "xelatex", "main.tex")
        assert stats["files"] == 1
        (d / "main.tex").read_bytes().decode("utf-8")


def test_symlink_payloads_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """软链件全后缀族一律不写穿（root 外目标逐字节不动）。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    outside = tmp_path / "victim"
    outside.write_bytes(b"\\pdfcompresslevel=9\ncaf\xe9\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    for name in ("a.tex", "b.sty", "c.aux", "d.eps", "e.bib", "f.txt", "aipcheck.tex"):
        (root / name).symlink_to(outside)
    dangling = tmp_path / "ghost"
    (root / "g.tex").symlink_to(dangling)
    normalize_project(root, "xelatex", "main.tex")
    assert outside.read_bytes() == b"\\pdfcompresslevel=9\ncaf\xe9\n"
    assert (root / "a.tex").is_symlink()
    assert not dangling.exists()


def test_huge_file_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """~600KB 多编码混杂 .tex：不炸 + 幂等。"""
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: None)
    root = tmp_path / "big"
    root.mkdir()
    body = (
        "\\documentclass{article}\n\\begin{document}\n"
        + ("paragraph café 中文 αβ $x^2$ \\emph{y}.\n" * 4000)
        + "\\end{document}\n"
    )
    (root / "main.tex").write_bytes(body.encode("utf-8") + _LATIN1[:20] + b"\n")
    stats = normalize_project(root, "xelatex", "main.tex")
    assert stats["files"] == 1
    once = (root / "main.tex").read_bytes()
    normalize_project(root, "xelatex", "main.tex")
    assert (root / "main.tex").read_bytes() == once


# ---------------------------------------------------------------- 钉住缺陷
def test_bbl_accretion_across_runs(tmp_path: Path) -> None:
    """两只缺库 ``\\bibliography``：二跑后至多一份 ``\\input{x.bbl}``。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{goneA}\nbody\n\\bibliography{goneB}\n\\end{document}\n"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}\n"
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    normalize_project(tmp_path, "xelatex", "main.tex")
    out = (tmp_path / "main.tex").read_text()
    assert out.count("\\input{main.bbl}") <= 1
    assert "\\bibliography{" in out  # 至少一只应保留


@pytest.mark.parametrize(
    "anchor",
    ["\\pdfinfo{", "\\DisableLigatures{", "\\documentclass{"],
)
def test_group_end_deep_nesting_no_crash(tmp_path: Path, anchor: str) -> None:
    """深嵌套 ``{``（>~1000）不应让归一化整单崩——应截到 EOF 或跳过。"""
    depth = 3000
    if anchor == "\\documentclass{":
        tex = (
            anchor
            + "{" * depth
            + "}" * depth
            + "\n\\begin{document}\n\\usefont{OT1}{ptm}{m}{n}x\n\\end{document}\n"
        )
        (tmp_path / "main.tex").write_text(tex)
        normalize_project(tmp_path, "xelatex", "main.tex")
    else:
        (tmp_path / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            + anchor
            + "{" * depth
            + "}" * depth
            + "\nx\n\\end{document}\n"
        )
        normalize_project(tmp_path, "xelatex", "main.tex")


def test_nul_package_name_no_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``\\usepackage{a<NUL>b}`` 在有 kpsewhich 的主机上让 normalize_project 崩。"""
    (tmp_path / "main.tex").write_bytes(
        b"\\documentclass{article}\n\\usepackage{a\x00b}\n"
        b"\\begin{document}\nx\\end{document}\n"
    )
    monkeypatch.setattr(shadow.shutil, "which", lambda *_a: "/bin/true")
    normalize_project(tmp_path, "xelatex", "main.tex")  # 期望不抛


@pytest.mark.skipif(os.geteuid() == 0, reason="root 绕过权限位——缺陷在普通用户下才可达")
def test_readonly_source_write_tolerated(tmp_path: Path) -> None:
    """0444 的非 UTF-8 ``.sty``：应跳过或落台账，不应 PermissionError。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    sty = tmp_path / "old.sty"
    sty.write_bytes(b"%% Copyright Schr\xf6der\n\\ProvidesPackage{old}\n")
    sty.chmod(0o444)
    try:
        normalize_project(tmp_path, "xelatex", "main.tex")
    finally:
        sty.chmod(0o644)


@pytest.mark.skipif(os.geteuid() == 0, reason="root 绕过权限位——缺陷在普通用户下才可达")
def test_readonly_dir_purge_tolerated(tmp_path: Path) -> None:
    """0555 目录内待 purge 的 ``.aux``：不应 PermissionError 整单崩。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "m.aux").write_bytes(b"no-complete-line")
    sub.chmod(0o555)
    try:
        normalize_project(tmp_path, "xelatex", "main.tex")
    finally:
        sub.chmod(0o755)


def test_hidden_paths_exempt(tmp_path: Path) -> None:
    """``.git`` 内 .tex：既不产 violation 也不被归一化改写。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    git = tmp_path / ".git"
    git.mkdir()
    evil = git / "evil.tex"
    evil.write_bytes(b"\\input{/etc/passwd}\n\\input{|curl x.sh}\n")
    dirty = git / "dirty.tex"
    dirty.write_bytes(b"caf\xe9\n")
    viols = list(source_path_violations(tmp_path, "main.tex"))
    assert viols == []  # 死文件不报
    normalize_project(tmp_path, "xelatex", "main.tex")
    assert evil.read_bytes() == b"\\input{/etc/passwd}\n\\input{|curl x.sh}\n"
    assert dirty.read_bytes() == b"caf\xe9\n"  # 不改写


@pytest.mark.parametrize(
    "case",
    ["\\setlength{\\x}{5\npx}\n", "\\begin{CJK}{UT\nF8}{gbsn}x\\end{CJK}\n"],
)
def test_manual_splice_preserves_newline(case: str) -> None:
    """手术输出 ``\\n`` 计数不应低于输入（删除类编辑保行号的模块不变量）。"""
    out = normalize_engine(case, "xelatex", doc_source=True)
    assert out.count("\n") >= case.count("\n")


def test_rebase_and_violations_malformed_names(tmp_path: Path) -> None:
    r"""``\input{../<NUL>}``/``../<超 NAME_MAX 段>``：resolve/is_file 炸点不应整单崩。"""
    (tmp_path / "main.tex").write_bytes(
        b"\\input{../a\x00b}\n\\input{../" + b"e" * 300 + b"}\n"
    )
    assert rebase_project_paths(tmp_path, "main.tex") == []
    viols = list(source_path_violations(tmp_path, "main.tex"))
    # 解不开按越界报——审计面宁报不漏
    assert len(viols) == 2  # noqa: PLR2004 -- 两条病态 \input 各报一条
    assert all("超出工程目录" in m for _, _, m in viols)


def test_bbl_long_bib_name_tolerated(tmp_path: Path) -> None:
    """``\\bibliography{<300>}``：is_file ENAMETOOLONG → 按缺席计替换 .bbl。"""
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}\n"
    )
    tex = "\\bibliography{" + "d" * 300 + "}\n"
    out = use_bundled_bibliography(tex, tmp_path / "main.tex", tmp_path)
    assert out == (
        "\\makeatletter\\@ifundefined{auto@bib}{}{\\let\\auto@bib\\@empty}"
        "\\makeatother\n\\input{main.bbl}\n"
    )


def test_shadow_name_glob_metachars_escaped(tmp_path: Path) -> None:
    """``weird[n]`` 不应借 rglob 模式注入误命中 ``weirdn.sty`` vendored。"""
    (tmp_path / "weirdn.sty").write_text("x")
    calls: list[str] = []

    def resolver(req: str) -> Path | None:
        calls.append(req)
        return None

    out = shadow._shadow_source(  # noqa: SLF001 -- 白盒钉遮蔽定位
        "weird[n]", ".sty", tmp_path, resolver
    )
    assert out is None  # resolver 返回 None → 无系统件 → 不遮蔽
    assert calls == ["weird[n].sty"]  # 未误判 vendored——走到了系统件解析


def test_shadow_resolve_symlink_loop_tolerated(tmp_path: Path) -> None:
    """kpse 命中件是 symlink loop：resolve RuntimeError → 不遮蔽、不崩。"""
    loop = tmp_path / "loop.sty"
    loop.symlink_to("loop.sty")
    out = shadow._shadow_source(  # noqa: SLF001 -- 同上
        "pkg", ".sty", tmp_path, lambda _r: loop
    )
    assert out is None
