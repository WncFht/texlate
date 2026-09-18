r"""双分派表镜像钉 —— ``_dispatch`` ↔ ``_group_surface``/``_pend_spec_of``。

三面分派表历史上的 (族 tag → 判据) 绑定曾逐表复写、单侧漂移静默；今
``_common._FAM_BIND`` 单源携带绑定，三面行序投影
``_DISPATCH_FAMS``/``_GRP_SURFACE_FAMS``/``_PEND_SPEC_FAMS``（行 =
``(族 tag, 名集 | 谓词 | None 动态行)``）经 ``_fams`` 派生：

- 投影纯度：三面每行判据即 ``_FAM_BIND[tag]`` 本体、tag 在表内唯一——
  绕过 ``_fams`` 手写发散绑定在此爆炸；
- 名级族等值：全集每个命令名在三臂各解析一个族 tag，B/pend 臂须命中
  ``_expected_*`` 规则——规则表即审计裁定的分歧清单，新分歧在此爆炸；
- 行序：对每个名取两臂静态命中行 tag 列，公共 tag 相对序须一致
  （行序漂移只在名集相交时有语义——今天真空，专门防未来交叉集漂移）；
- 行为签名：枚举全集在两臂的真实输出签名（cs 名落点 + 参数可见性），
  除 ``_SIG_DIFFS`` 已录分歧外逐项相等——投影≈行为的证据层。

签名 = ``(covers, arg)``：covers ⊆ {piece, chunk, PH_TYPE} 记 ``\N``
落点（字面 piece / chunk 可译文面 / 某 ph 体），arg ∈ {vis,hid,-} 记
探针参 ``zzq`` 族归宿（chunk 可译 / ph·piece 内隐藏 / 不见）。
"""

import re
import string

from conftest import DOC

from texlate.latex import parse_tex
from texlate.latex.model import PieceKind
from texlate.latex.segmenter._common import _FAM_BIND
from texlate.latex.segmenter.mainloop import _DISPATCH_FAMS
from texlate.latex.segmenter.pending import _GRP_SURFACE_FAMS, _PEND_SPEC_FAMS
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    BOX_TAIL_NAMES,
    CHUNK_ARG_NAMES,
    CITE_NAMES,
    DIMEN_TAIL_KIND,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_SCAN_CMDS,
    PAIR_BLOCK_ALL,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    REF_NAMES,
    TRANSPARENT_HEAD_SPEC,
    TRANSPARENT_NAMES,
)

_UNIVERSE = frozenset(
    PROTECT_NAMES
    | INPUT_SCAN_CMDS
    | CHUNK_ARG_NAMES
    | PROTECT_BLOCK_NAMES
    | set(TRANSPARENT_HEAD_SPEC)
    | BOX_TAIL_NAMES
    | TRANSPARENT_NAMES
    | BOUNDARY_NAMES
    | INLINE_LITERAL_CMDS
    | FONT_SWITCHES
    | ACCENT_CHARS
    | CITE_NAMES
    | REF_NAMES
    | PAIR_BLOCK_ALL
    | set(DIMEN_TAIL_KIND)
    | {
        "verb",
        "verb*",
        "lstinline",
        "begin",
        "end",
        "href",
        "hyperref",
        "endinput",
        "[",
        "(",
        "]",
        ")",
        "\\",
        "ifx",
        "ifhmode",
        "iffoo",
        "else",
        "fi",
        "or",
        "ifnum",
        "citeZZZ",
        "zzref",
        "labelref",
        "citexyz",
        "tikz",
        "foo",
        "parbox",
        "footrue",
        "tablecaption",
        "keywords",
        "date",
        "title",
        "documentclass",
        "footnotemark",
        "@input",
    }
    | {c for c in string.printable if not c.isspace()}
)


def _match(m: object, name: str) -> bool:
    """行匹配器判定：str=单名等值、callable=谓词、其余=名集成员。"""
    if isinstance(m, str):
        return name == m
    if callable(m):
        return bool(m(name))
    return name in m  # tuple/frozenset/dict 名集


def _resolve(rows: tuple[tuple[str, object], ...], name: str) -> str:
    """首个静态命中行的 tag；全静态行未中 → 末个动态行 tag（终态处理器）。"""
    last = "?"
    for tag, m in rows:
        if m is None:
            last = tag
            continue
        if _match(m, name):
            return tag
    return last


def _matched_seq(rows: tuple[tuple[str, object], ...], name: str) -> list[str]:
    """按行序返回全部静态命中 tag（查行序漂移用）。"""
    return [tag for tag, m in rows if m is not None and _match(m, name)]


# ----------------------------------------------------------------- 名级钉

#: A 臂 tag → B 臂同 tag（B 有同判据行）。不在列的 A 族 = B 无对应行，
#: 名字一律落 ``probe``（argspec/探针/逐字终端）——唯一例外见下。
_B_EQUIV = {
    "verb",
    "env",
    "cite-ref",
    "protect",
    "href",
    "input-scan",
    "chunk-arg",
    "protect-block",
    "boundary",
    "cond",
    "math-open",
    "bsbs",
    "transparent-head",
    "accent",
    "inline-literal",
    "pair-block",
}


def _expected_b(a_tag: str, name: str) -> str:
    """审计裁定的 B 臂期望族——已知分工差异全在此表：

    - ``hyperref``：B 有显式行（argspec ``m m`` key,text 的组内对价——
      组内行无条件保 text 参留 surface），A 走 argspec chunk-arg
      （key 位留字面、text 出独立 chunk）→ ``hyperref``；
    - ``math-close``：B 无收界专用行——``]``/``)`` 单字符非字母落
      inline-literal 行 → ``inline-literal``；
    - ``unknown`` ∧ ``DIMEN_TAIL_KIND``：A 折在 row19 unknown 内部
      尾参扫，B 是 accent/argspec 前的显式行 → ``tail``；
    - ``unknown`` 其余 → ``probe``（终态同名不同面）；
    - ``transparent``/``box-tail``/``endinput``：B 无对应行，
      经 argspec/探针/逐字兜收 → ``probe``。
    """
    if name == "hyperref":
        return "hyperref"
    if a_tag in _B_EQUIV:
        return a_tag
    if a_tag == "math-close":
        return "inline-literal"
    if a_tag == "unknown" and name in DIMEN_TAIL_KIND:
        return "tail"
    return "probe"


_PEND_EQUIV = _B_EQUIV | {"env-macro"}


def _expected_pend(a_tag: str, name: str) -> str:
    """``_pend_spec_of`` 期望族（同表第三镜像——跨界待绑参槽形分派）：

    - 四个数学定界 cs 在 pend 合一行（返回无槽形）→ ``math-delim``；
    - ``hyperref`` 有显式槽行 → ``hyperref``；
    - pend 无 ``tail`` 行（尾参在组内扫描已消费，跨界槽不含 dimen
      形）→ ``unknown``∧``DIMEN_TAIL`` 落 ``probe``；
    - 其余与 ``_expected_b`` 同构。
    """
    if name in ("[", "(", "]", ")"):
        return "math-delim"
    if name == "hyperref":
        return "hyperref"
    if a_tag in _PEND_EQUIV:
        return a_tag
    return "probe"


def test_fam_bind_identity() -> None:
    """三面每行判据必须是 ``_FAM_BIND[tag]`` 本体且 tag 表内唯一——
    绕过 ``_fams`` 手写的发散绑定（同名异判据行）在此爆炸。"""
    for rows in (_DISPATCH_FAMS, _GRP_SURFACE_FAMS, _PEND_SPEC_FAMS):
        tags = [tag for tag, _ in rows]
        assert len(tags) == len(set(tags)), f"tag 重复: {tags}"
        for tag, m in rows:
            assert tag in _FAM_BIND, f"未登记 tag: {tag}"
            assert m is _FAM_BIND[tag], f"{tag} 绑定发散: {m!r} vs {_FAM_BIND[tag]!r}"


def test_name_family_mirror() -> None:
    """全集逐名：``_resolve`` 出的 (A族, B族, pend族) 必须等于裁定对。"""
    bad: dict[str, tuple[str, str, str]] = {}
    for name in sorted(_UNIVERSE):
        a = _resolve(_DISPATCH_FAMS, name)
        b = _resolve(_GRP_SURFACE_FAMS, name)
        p = _resolve(_PEND_SPEC_FAMS, name)
        if b != _expected_b(a, name) or p != _expected_pend(a, name):
            bad[name] = (a, b, p)
    assert not bad, f"名级族分歧超裁定表: {bad}"


def test_shared_row_order() -> None:
    """同名在双臂命中的公共行 tag 相对序必须一致。

    今天全集零违规（静态交集都按同一相对序）——漂移例：若某名同落
    ``transparent-head`` 与 ``boundary`` 两集，A 序 thead<boundary
    而 B 序 boundary<thead，此处爆炸。
    """
    bad: dict[str, tuple[list[str], list[str]]] = {}
    for name in sorted(_UNIVERSE):
        a_seq = _matched_seq(_DISPATCH_FAMS, name)
        b_seq = _matched_seq(_GRP_SURFACE_FAMS, name)
        common_a = [t for t in a_seq if t in b_seq]
        common_b = [t for t in b_seq if t in a_seq]
        if common_a != common_b:
            bad[name] = (a_seq, b_seq)
    assert not bad, f"共享行序漂移: {bad}"


# ----------------------------------------------------------------- 行为钉

_PH_RX = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")
_ARG_TOKENS = ("zzq", "zzu", "zzd", "zzb")

#: 足长上下文——run 清洗后字符数须压过 ``CHUNK_MIN``，否则整组回落
#: ``[[EXPAND]]`` 字面段、组内签名蒸发（阈值假象不是分类差异）。
_PRE = (
    "This is a longer paragraph of English prose that certainly should be "
    "segmented into a chunk for translation purposes here "
)
_POST = (
    " and the sentence continues with more English words afterwards so the "
    "run stays well above the threshold for sure."
)

_SPECIAL_FORMS: dict[str, tuple[str, ...]] = {
    "verb": ("|zzq|", "{zzq}"),
    "verb*": ("|zzq|",),
    "lstinline": ("|zzq|", "{zzq}"),
    "begin": ("{zzq} zzb \\end{zzq}",),
    "end": ("{zzq} zzb \\end{zzq}",),
    "href": ("{zzu}{zzq}",),
    "hyperref": ("[zzu]{zzq}", "{zzq}"),
    "\\": ("[3pt]", " zzq"),
    "import": ("{zzd}{zzq}", "{zzq}"),
    "subimport": ("{zzd}{zzq}", "{zzq}"),
}


def _forms(name: str) -> tuple[str, ...]:
    """每名的探针形态列（附加在 ``\\name`` 后的实参形）。"""
    if name in _SPECIAL_FORMS:
        return _SPECIAL_FORMS[name]
    forms = ["{zzq}", ""]
    if name in DIMEN_TAIL_KIND:
        forms += ["3pt", "=3pt"]
    return tuple(forms)


def _needle(name: str) -> re.Pattern[str]:
    """``\\name`` 的边界感知匹配——名尾字母/``@`` 须排续名字符（``\\v``
    不得命中 ``\\vv``、``\\b`` 不得命中 ``\\begin``）；控制符号不续名。"""
    tail = r"(?![a-zA-Z@])" if name[-1].isalpha() or name[-1] == "@" else ""
    return re.compile(re.escape("\\" + name) + tail)


_MAX_PH_DEPTH = 8


def _expand(body: str, ph_map: dict[str, str], depth: int = 0) -> str:
    """ph 体递归展开（体可内嵌 ``[[X_n]]`` 标记）。"""
    if depth > _MAX_PH_DEPTH:
        return body
    return _PH_RX.sub(
        lambda m: _expand(ph_map.get(m.group(0), m.group(0)), ph_map, depth + 1),
        body,
    )


def _sig(res: object, name: str) -> tuple[frozenset[str], str]:
    """签名：``\\name`` 的落点集 + 探针参可见性。"""
    pat = _needle(name)
    ph_map = res.ph_map  # type: ignore[attr-defined]
    covers: set[str] = set()
    for p in res.pieces:  # type: ignore[attr-defined]
        if (
            p.kind is PieceKind.LITERAL
            and "newcommand" not in p.text
            and pat.search(p.text)
        ):
            covers.add("piece")
    for marker, body in ph_map.items():
        if pat.search(_expand(body, ph_map)):
            covers.add(marker[2:-2].rsplit("_", 1)[0])
    for c in res.chunks:  # type: ignore[attr-defined]
        if pat.search(c.content):
            covers.add("chunk")
    arg = "-"
    if any(
        any(t in c.content for t in _ARG_TOKENS)
        for c in res.chunks  # type: ignore[attr-defined]
    ):
        arg = "vis"
    elif any(
        any(t in _expand(b, ph_map) for t in _ARG_TOKENS) for b in ph_map.values()
    ) or any(
        p.kind is PieceKind.LITERAL
        and "newcommand" not in p.text
        and any(t in p.text for t in _ARG_TOKENS)
        for p in res.pieces  # type: ignore[attr-defined]
    ):
        arg = "hid"
    return (frozenset(covers), arg)


#: 已录签名分歧（2026-09-18 全集枚举裁定）——key=(name, form)，
#: value=(A covers, A arg, B covers, B arg)。等价类（落点不同但
#: 参数可见性一致、两侧都不暴露译文面）与真分歧分列注释。
_SIG_DIFFS: dict[tuple[str, str], tuple[frozenset[str], str, frozenset[str], str]] = {
    # ---- 等价：boundary/结构命令主流断 run 出字面段，组内无法断 piece
    # 只能嵌 [[CMD]] 占位——同隐同参可见性，仅承载不同 ----
    ("InputIfFileExists", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("RequirePackage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("addtocounter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("addtolength", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("appendix", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("backmatter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("balance", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("bigskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("bottomrule", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("centering", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("centerline", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("cleardoublepage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("clearpage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("cline", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("cmidrule", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("columnbreak", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("documentstyle", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("frontmatter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hfill", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hline", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hskip", "3pt"): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hskip", "=3pt"): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("hspace", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("include", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("includestandalone", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("indent", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("input", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("item", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("linebreak", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("listoffigures", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("listoftables", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("mainmatter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("makeatletter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("makeatother", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("maketitle", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("medskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("midrule", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newbox", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newcount", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newcounter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newdimen", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newfam", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newhelp", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newinsert", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newlanguage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newline", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newmuskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newpage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newread", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newtheorem", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newtoks", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("newwrite", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("nopagebreak", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("onecolumn", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("pagebreak", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("pagenumbering", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("pagestyle", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("setcounter", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("setlength", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("setstretch", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("settodepth", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("settoheight", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("settowidth", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("smallskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("subfile", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("tableofcontents", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("thispagestyle", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("toprule", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("twocolumn", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("usepackage", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("vfill", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("vskip", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("vskip", "3pt"): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("vskip", "=3pt"): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    ("vspace", ""): (frozenset({"piece"}), "-", frozenset({"CMD"}), "-"),
    # ---- 等价：chunk-arg 族 ``{zzq}``——主流 ``\section[opt]{`` 前缀出字面
    # piece + 参进独立 chunk；组内名+头参进 ``[[CMD]]``、``{arg}`` 组
    # token 留 surface 续扫（B 臂无独立 chunk piece——参留主流即同可见） ----
    ("abst", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("caption", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("chapter", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("footnote", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("footnotetext", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("keywords", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("paragraph", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("part", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("pinlabel", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("sect", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("section", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("subcaption", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("subparagraph", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("subsect", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("subsection", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("subsubsection", "{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("subtitle", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("tablecaption", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("tablecomments", "{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("thanks", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("title", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    # ---- 等价：同上 carrier 差——``{zzq}`` 未被消费 → 两侧参都裸进可译文本 ----
    ("appendix", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("backmatter", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("balance", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("bigskip", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("bottomrule", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("centering", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("centerline", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("cleardoublepage", "{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("clearpage", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("columnbreak", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("frontmatter", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("hfill", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("hline", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("hskip", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("indent", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("item", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("linebreak", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("listoffigures", "{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("listoftables", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("mainmatter", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("makeatletter", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("makeatother", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("maketitle", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("medskip", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("midrule", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("newline", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("newpage", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("newtheorem", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("nopagebreak", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("onecolumn", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("pagebreak", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("smallskip", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("tableofcontents", "{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("toprule", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("twocolumn", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("vfill", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    ("vskip", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"CMD"}), "vis"),
    # ---- 等价：同上，参被吃（input 族/尾参/setter 族）——piece↔CMD 同 hid ----
    ("InputIfFileExists", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("RequirePackage", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("addtocounter", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("addtolength", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("cline", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("cmidrule", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("documentstyle", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("hspace", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("import", "{zzd}{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("import", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("include", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("includestandalone", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("input", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newbox", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newcount", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newcounter", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newdimen", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newfam", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newhelp", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newinsert", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newlanguage", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newmuskip", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newread", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newskip", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newtoks", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("newwrite", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("pagenumbering", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("pagestyle", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("setcounter", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("setlength", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("setstretch", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("settodepth", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("settoheight", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("settowidth", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("subfile", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("subimport", "{zzd}{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("subimport", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("thispagestyle", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD"}),
        "hid",
    ),
    ("usepackage", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    ("vspace", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"CMD"}), "hid"),
    # ---- 等价：cond 族主流走 _handle_cond 字面档，组内嵌 [[COND]] ----
    ("else", ""): (frozenset({"piece"}), "-", frozenset({"COND"}), "-"),
    ("else", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"COND"}), "vis"),
    ("fi", ""): (frozenset({"piece"}), "-", frozenset({"COND"}), "-"),
    ("fi", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"COND"}), "vis"),
    ("iffoo", ""): (frozenset({"piece"}), "-", frozenset({"COND"}), "-"),
    ("iffoo", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"COND"}), "vis"),
    ("ifnum", ""): (frozenset({"piece"}), "-", frozenset({"COND"}), "-"),
    ("or", ""): (frozenset({"piece"}), "-", frozenset({"COND"}), "-"),
    ("or", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({"COND"}), "vis"),
    # ---- 等价：组内消费/段界——名不落任何面，两侧皆不可见或同参可见 ----
    ("endinput", ""): (frozenset({"piece"}), "-", frozenset({}), "-"),
    ("ifhmode", ""): (frozenset({"piece"}), "-", frozenset({}), "-"),
    ("ifhmode", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({}), "vis"),
    ("ifx", ""): (frozenset({"piece"}), "-", frozenset({}), "-"),
    ("par", ""): (frozenset({"piece"}), "-", frozenset({}), "-"),
    ("par", "{zzq}"): (frozenset({"piece"}), "vis", frozenset({}), "vis"),
    # ---- 等价：documentclass——pkg 登记主流整段字面，组内 CMD+piece ----
    ("documentclass", ""): (
        frozenset({"piece"}),
        "-",
        frozenset({"CMD", "piece"}),
        "-",
    ),
    ("documentclass", "{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"CMD", "piece"}),
        "hid",
    ),
    # ---- 分歧留档（semantic-diff 非缺陷——审计裁决不动） ----
    ("@", ""): (frozenset({"chunk"}), "-", frozenset({}), "-"),
    ("@", "{zzq}"): (frozenset({"chunk"}), "vis", frozenset({}), "-"),
    ("@input", ""): (frozenset({"chunk"}), "-", frozenset({}), "-"),
    ("@input", "{zzq}"): (frozenset({"chunk"}), "vis", frozenset({}), "-"),
    ("begin", "{zzq} zzb \\end{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"ENVTAG", "piece"}),
        "vis",
    ),
    ("end", "{zzq} zzb \\end{zzq}"): (
        frozenset({"piece"}),
        "hid",
        frozenset({"ENVTAG", "piece"}),
        "vis",
    ),
    ("endinput", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({}), "-"),
    ("footnotemark", ""): (frozenset({"chunk"}), "-", frozenset({"CMD"}), "-"),
    ("footnotemark", "{zzq}"): (frozenset({"chunk"}), "vis", frozenset({"CMD"}), "vis"),
    ("hyperref", "[zzu]{zzq}"): (
        frozenset({"piece"}),
        "vis",
        frozenset({"CMD"}),
        "vis",
    ),
    ("ifnum", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({"COND"}), "-"),
    ("ifx", "{zzq}"): (frozenset({"piece"}), "hid", frozenset({}), "-"),
}


def test_behavioral_mirror() -> None:
    """全集逐名逐形态：两臂签名须相等或命中 ``_SIG_DIFFS`` 已录分歧。

    A 臂 = 主流 ``_dispatch``（``PRE \\name<form> POST``）；B 臂 = 组内
    ``_group_surface``（``\\newcommand{\\vv}{pre \\name<form> post}`` 的
    展开回放）。已录分歧即分工差异清单——新漂移/修复都会爆在此处，
    修复后删条目收紧表。
    """
    unexpected: list[tuple[str, str, object, object]] = []
    for name in sorted(_UNIVERSE):
        for form in _forms(name):
            call = "\\" + name + form
            sa = _sig(parse_tex(DOC % (_PRE + call + _POST)), name)
            sb = _sig(
                parse_tex(
                    DOC
                    % (
                        "\\newcommand{\\vv}{pre "
                        + call
                        + " post}\n"
                        + _PRE
                        + "\\vv"
                        + _POST
                    )
                ),
                name,
            )
            want = _SIG_DIFFS.get((name, form))
            if want is not None:
                got = (sa[0], sa[1], sb[0], sb[1])
                if got != want:
                    unexpected.append((name, form, got, want))
            elif sa != sb:
                unexpected.append((name, form, sa, sb))
    assert not unexpected, f"签名分歧超已录表: {unexpected}"
