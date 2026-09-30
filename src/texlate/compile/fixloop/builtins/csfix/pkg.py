r"""builtins.csfix.pkg — already_def 包装载点前置臂 (csfix 拆分)。

file:line 形错误行抽肇事包茎 (``_pkg_err_stems``), 其每个用户件
``\usepackage``/``\RequirePackage`` 装载点前 ``\let\X\@undefined``
—— 报错包恒为后定义者, 装载点前清位序恒正确。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.common import (
    _LOAD_SITE_RE,
    _live_matches,
    _load_elems,
    _undefine_cs,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.ctx import LoopCtx


__all__ = [
    "_LOAD_SITE_RE",
    "_PKG_ERR_FILE_RE",
    "_load_elems",
    "_pkg_err_stems",
    "_undefine_pkg_sites",
]


#: file:line 形 already_def 错误的肇事包定位 —— ``path/<pkg>.sty:N:
#: LaTeX Error: Command `\X' already defined`` 同时给出肇事包茎与撞名。
#: 报错包在执行序上恒为后定义者 (先定义者无论在哪都已跑完), 故其
#: 每个用户件装载点前清位序恒正确 —— 与 docclass 块互补：缝位在
#: preamble 先定义者 (``\usepackage{newtxmath}`` 类) 尚未执行时
#: ``\let`` 是纯 no-op (bbkresid 4 格同型实证), 装载点前清位才
#: 落在先/后定义者之间。``.cls`` 不收：类文件无 usepackage 装载点
#: 可锚 (其内互撞归站点臂/abstain)。
_PKG_ERR_FILE_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\.sty:\d+:\s*LaTeX Error:"
    r"\s*Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?\s+already\s+defined",
    re.MULTILINE,
)


def _pkg_err_stems(log: str) -> dict[str, set[str]]:
    r"""file:line 形 already_def 行扫 → ``{撞名: {肇事包 sty 茎 (小写)}}``。"""
    out: dict[str, set[str]] = {}
    for m in _PKG_ERR_FILE_RE.finditer(log):
        out.setdefault(m.group(2), set()).add(m.group(1).lower())
    return out


def _undefine_pkg_sites(
    ctx: LoopCtx, cs_stems: dict[str, set[str]]
) -> tuple[int, set[str]]:
    r"""肇事包茎的用户件装载点前 ``\let\X\@undefined`` → (前置站数, 覆盖撞名集)。

    肇事包恒为后定义者 → 其每个 live 装载点 (opts/逗号列元素匹配茎名,
    dup 站全收) 前清位序恒正确; 遮盖复核剔注释/verbatim 死站, 上轮
    已前置的 cs 按 256 字前缀窗幂等跳过 (新 csname 形与旧
    ``\let\X\@undefined`` 形双查)。csname 形零字面 ``@`` —— 全文件类
    统一裸前置, 不再按 ``.tex``/``.sty`` 分 ``\makeatletter`` 对。
    肇事茎无用户件装载点 (cls 内传递装载) 的撞名不进返回集 → 调用方以
    docclass 块兜底。
    """
    want = set().union(*cs_stems.values()) if cs_stems else set()
    covered: set[str] = set()
    n_sites = 0
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if not t:
            continue
        out: list[str] = []
        prev = 0
        for m in _live_matches(_LOAD_SITE_RE, t):  # 注释/verbatim 内死站不锚
            elems = _load_elems(m)
            if not (elems & want):
                continue
            window = t[max(0, m.start() - 256) : m.start()]
            names = sorted(
                cs
                for cs, stems in cs_stems.items()
                if stems & elems
                and f"\\let\\{cs}\\@undefined" not in window
                and f"\\csname {cs}\\endcsname" not in window
            )
            if not names:
                continue
            ins = "".join(_undefine_cs(n) for n in names)
            out.append(t[prev : m.start()])
            out.append(ins + "\n")
            prev = m.start()
            covered.update(names)
            n_sites += 1
        if out:
            out.append(t[prev:])
            ctx.write(f, "".join(out))
    return n_sites, covered
