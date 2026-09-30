r"""builtins._mccaret — caret_utf8_fix ``^^XX`` 字节记法解码 (C5 拆叶)。

bibtex-era ``^^XX`` UTF-8 字节记法运行段识别 (``_CARET_RUN_RE``/
``_CARET_TOK_RE`` + lead-byte 宽度界 ``_LEAD2/3/4`` + C1 缺字指纹带
``_C1_LO/HI``), ``_caret_decode_run`` 严格 UTF-8 校验逐 token 解码,
``_caret_utf8_text`` 段级回放 —— ``caret_utf8_fix`` 入口 (.bbl 消毒位)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _mc_seen, _splice
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_C1_HI",
    "_C1_LO",
    "_CARET_RUN_RE",
    "_CARET_TOK_RE",
    "_LEAD2",
    "_LEAD3",
    "_LEAD4",
    "_caret_decode_run",
    "_caret_utf8_text",
    "caret_utf8_fix",
]


# ════════════════════════════════════════════════════════════════
# caret_utf8_fix: ``^^XX`` UTF-8 字节记法 → 解码还原字面量 (F4f)
# ════════════════════════════════════════════════════════════════

#: bibtex-era ``^^XX`` 字节记法运行段 (相邻 ≥1 token; 逐 token 尝试
#: UTF-8 多字节, 不合法字节回吐原 token —— 见 _caret_decode_run)。
_CARET_RUN_RE = re.compile(r"(?:\^\^[0-9a-fA-F]{2})+")
_CARET_TOK_RE = re.compile(r"\^\^([0-9a-fA-F]{2})")

#: UTF-8 lead-byte 分类下界 (≥F5 非法 lead/续字节存在性/超长/代理区
#: 全部由 ``bytes.decode`` 严格校验兜底 —— 猜测宽只为取窗)。
_LEAD2, _LEAD3, _LEAD4 = 0xC0, 0xE0, 0xF0

#: ``^^XX`` mojibake 指纹带: C1 控制符缺字区间 —— 高位 UTF-8 字节
#: (0x80-0x9F) 落此才报缺字, Latin-1 面字节静默错印。
_C1_LO, _C1_HI = 0x80, 0x9F


def _caret_decode_run(run: str) -> tuple[str, int]:
    r"""单段 ``^^XX`` 运行 → (重放文本, 解码出的多字节字符数)。

    逐字节位置按 lead-byte 宽度 (C0-DF→2/E0-EF→3/F0-F4→4) 取窗口交
    ``bytes.decode`` 严格校验 —— 截断/超长/代理区/非续字节全部回
    吐原 ``^^XX`` token。单字节 token (``^^41``/``^^0d`` 合法 TeX
    字符记法) 恒原样保留, 只多字节序列算 mojibake 证据。
    """
    toks = _CARET_TOK_RE.findall(run)
    byts = [int(h, 16) for h in toks]
    out: list[str] = []
    n_seq = 0
    i = 0
    while i < len(byts):
        b = byts[i]
        width = 4 if b >= _LEAD4 else 3 if b >= _LEAD3 else 2 if b >= _LEAD2 else 0
        if width and i + width <= len(byts):
            try:
                out.append(bytes(byts[i : i + width]).decode("utf-8"))
                n_seq += 1
                i += width
                continue
            except UnicodeDecodeError:
                pass
        out.append(f"^^{toks[i]}")
        i += 1
    return "".join(out), n_seq


def _caret_utf8_text(t: str) -> tuple[str, int, int]:
    r"""``^^XX`` 运行段逐段解码 → (新文本, 改写段数, 解码字符数)。

    遮盖视图取 offset 回原文回放 —— verbatim/注释内记法不动; 段内
    无一合法多字节序列的段整体不动 (``^^41`` 纯 ASCII 记法段)。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    n_chars = 0
    for m in _CARET_RUN_RE.finditer(masked):
        text, n = _caret_decode_run(m[0])
        if n:
            edits.append((m.start(), m.end(), text))
            n_chars += n
    if not edits:
        return t, 0, 0
    return _splice(t, edits), len(edits), n_chars


def caret_utf8_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``^^XX`` UTF-8 字节记法 → 解码还原字面量 (F4f, .bbl 消毒位)。

    bibtex-era 工具把非 ASCII 按 UTF-8 字节写成 ``^^e2^^80^^93`` 三连,
    每 ``^^XX`` 在 xetex 下读作独立码位 U+00XX: 高位字节产 C1
    (U+0080-9F) 缺字, 低位字节产 â/¼ 等静默 mojibake (2104.00026
    master2020.bbl: ``Knizhnik^^e2^^80^^93Zamolodchikov`` = en-dash,
    ``f^^c3^^bcr`` = für)。门控 = 日志见 C1 缺字 (字节记法指纹);
    解码面 = 全文 ``^^XX`` 段中严格合法 UTF-8 多字节序列 —— 同机制
    的零缺字节对 (ü 的 C3/BC 都落 Latin-1 有槽面) 一并还原, 字节级
    seen-门会漏这类不可见 mojibake。解码产字面量, 缺字链下游
    (char_table/字体回退) 照常接管。``params.exts`` 缺省 .tex/.bbl。
    """
    del eng, payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    if not any(_C1_LO <= cp <= _C1_HI for cp in seen):
        return False, "no C1 missing chars (^^XX byte-notation fingerprint)"
    exts = tuple(params.get("exts") or (".tex", ".bbl"))
    n_runs = 0
    n_chars = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, nr, nc = _caret_utf8_text(t)
        if nr and nt != t:
            ctx.write(f, nt)
            n_runs += nr
            n_chars += nc
            n_files += 1
    if not n_runs:
        return False, "C1 misses present but no decodable ^^XX runs in source"
    return True, (
        f"^^XX UTF-8 runs decoded: {n_runs} run(s), "
        f"{n_chars} char(s) in {n_files} file(s)"
    )
