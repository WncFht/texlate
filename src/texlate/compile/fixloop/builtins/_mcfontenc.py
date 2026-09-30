r"""builtins._mcfontenc — fontenc_enc_relax 未使用 enc 摘除 (C5 拆叶)。

``missing_file|<enc>enc.def`` → ``_ENC_DEF_RE`` 提取 enc 名 → 使用探针集
``_enc_use_res`` 全文未使 → ``_strip_enc_opts`` fontenc 选项摘除 +
``_comment_enc_decl`` ``\DeclareFontEncoding`` 行注释 ——
``fontenc_enc_relax`` 入口 (fontfb-B 末位臂)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _is_live, _splice
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_ENC_DEF_RE",
    "_FONTENC_LOAD_RE",
    "_comment_enc_decl",
    "_enc_use_res",
    "_strip_enc_opts",
    "fontenc_enc_relax",
]


# ════════════════════════════════════════════════════════════════
# fontenc_enc_relax: missing_file|<enc>enc.def → 未使用 enc 从 fontenc 选项摘除
# ════════════════════════════════════════════════════════════════

#: ``<enc>enc.def`` payload → enc 名 (t2aenc.def→T2A, lgrenc.def→LGR)。
_ENC_DEF_RE = re.compile(r"^([a-zA-Z0-9]+)enc\.def$", re.IGNORECASE)

#: ``\usepackage[..,ENC,..]{fontenc}`` / ``\RequirePackage`` 选项表行。
_FONTENC_LOAD_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^\]]*)\]\s*\{\s*fontenc\s*\}"
)


def _enc_use_res(enc: str) -> list[re.Pattern[str]]:
    r"""``enc`` 被「使用」的探针集。

    ``\fontencoding{ENC}`` 选定与 ``\DeclareText{Symbol,Command,Accent,Composite}{cs}{ENC}``
    声明; ``\DeclareFontEncoding{ENC}`` 本身是装载点不归使用 (可摘)。
    """
    e = re.escape(enc)
    return [
        re.compile(rf"\\fontencoding\s*\{{\s*{e}\s*\}}"),
        re.compile(
            rf"\\DeclareText(?:Symbol|Command|Accent|Composite)"
            rf"\s*\{{[^{{}}]*\}}\s*\{{\s*{e}\s*\}}"
        ),
    ]


def _strip_enc_opts(t: str, enc: str) -> tuple[str, int]:
    """``fontenc`` 选项表摘除 ``enc`` → (新文本，摘除数); 表空则连方括号一起去。"""
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    want = enc.casefold()
    for m in _FONTENC_LOAD_RE.finditer(masked):
        if not _is_live(m, masked, t):
            continue
        toks = [k.strip() for k in m[1].split(",")]
        kept = [k for k in toks if k and k.casefold() != want]
        if len(kept) == len([k for k in toks if k]):
            continue
        if kept:
            edits.append((m.start(1), m.end(1), " " + ", ".join(kept) + " "))
        else:
            edits.append((m.start(1) - 1, m.end(1) + 1, ""))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _comment_enc_decl(t: str, enc: str) -> tuple[str, int]:
    r"""``\DeclareFontEncoding{ENC}`` 整行注释 → (新文本, 注释数)。

    decl 即 ``<enc>enc.def`` 装载点 —— 全文无 ``\fontencoding{ENC}`` 使用时
    (已由调用方前置保证) 声明是死件, 注释摘除零语义差。
    """
    rx = re.compile(
        rf"^[ \t]*\\DeclareFontEncoding\s*\{{\s*{re.escape(enc)}\s*\}}[^\n]*",
        re.MULTILINE,
    )
    masked = mask_tex(t)
    edits = [
        (m.start(), m.end(), "%" + m[0])
        for m in rx.finditer(masked)
        if _is_live(m, masked, t)
    ]
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fontenc_enc_relax(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``missing_file|<enc>enc.def`` → 未使用 enc 从 fontenc 装载点摘除 (fontfb-B)。

    install_file/vendored_fetch 全真件臂 (t2aenc/lgrenc 皆有 filemap 档 +
    vendor 真件) 之后的末位改写臂 —— 面向既无档又无 vendor 件的 enc.def。
    全文无 ``\fontencoding{ENC}``/``\DeclareText*{..}{ENC}`` 使用时:
    ``\usepackage[..,ENC,..]{fontenc}`` 选项摘 ENC (表空连方括号去,
    ``\usepackage{fontenc}`` TU 默认下无害) + 裸 ``\DeclareFontEncoding``
    行注释。ENC 在使 → decline 诚实 unfixable (T2A→OT2 换编码产 mojibake,
    无安全替代); 装载点不见 → 传递性请求 (babel ldf 内拉) 同样 decline。
    """
    del eng
    m = _ENC_DEF_RE.match(payload or "")
    if not m:
        return False, f"payload {payload!r} is not an <enc>enc.def"
    enc = m[1].upper()
    blob = mask_tex(ctx.source_blob())
    if any(rx.search(blob) for rx in _enc_use_res(enc)):
        return False, f"{enc} selected in source — strip unsafe"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    n_sites = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n1 = _strip_enc_opts(t, enc)
        nt, n2 = _comment_enc_decl(nt, enc)
        if n1 + n2 and nt != t:
            ctx.write(f, nt)
            n_sites += n1 + n2
            n_files += 1
    if not n_sites:
        return False, f"{enc} not referenced by any fontenc load — transitive"
    return True, f"stripped {enc} from {n_sites} site(s) in {n_files} file(s)"
