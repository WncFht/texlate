r"""providesdate 车道 (2026-09-19): ``_provides_date`` expl3 日期面补齐。

texmf 实测面 (/usr/share/texmf-dist):

- ``\ProvidesExplX{n}{YYYY-MM-DD}{v}`` brace 第二槽字面日期 —— 237 处
  (csvsimple-l3.sty ``{2024/09/27}{2.7.0}``); bracket 面 Expl 变体 0 处。
- ``\ProvidesExplX{n}{\cs}{v}`` brace 槽间址 —— 52 处 (``\ExplFileDate``
  12 / ``\ltlab*date`` 22 / ``\g@*@date@tl`` 8 / ``\abx@date`` 2 …), 赋值
  面全为 ``\def`` 族 (含 ``\def \cs    {d}`` 疏松排版) 或 ``\GetIdInfo``。
- ``\GetIdInfo $Id: name.ext ver YYYY-MM-DD ...$`` → ``\ExplFileDate``
  (ctex.sty:31 实证; expl3-code.tex auxii/auxiii 语义: ver==-1 →
  ``0000/00/00`` 不可用, 不取)。
- ``\ProvidesFile{n}[date]`` 1853 处 + ``[\cs]`` 间址 256 处 (212 为
  ``[\filedate]``) —— ``_DATE_RE``/``_DATE_INDIRECT_RE`` 纳入 ``File``。
- plain ``\ProvidesX{n}{date}`` 二花括号形 —— 0 处, 不抽。

保守口径: 间址查无字面赋值 / GetIdInfo ver==-1 / 无日期面 → ``None``,
绝不猜 (错日期静默毒化 ``find_vendored_shadows`` 的 ld<sd 比对)。
"""

from pathlib import Path

from texlate.compile.fixloop.builtins import (
    _provides_date,
    vendored_shadow_isolate,
)
from texlate.compile.fixloop.engine import LoopCtx


class _ShadowEng:
    """probe_file → ``texmf`` 目录直查 (模拟系统副本在场)。"""

    name = "xelatex"

    def __init__(self, texmf: Path, extra: dict[str, Path] | None = None) -> None:
        self.texmf = texmf
        self.extra = extra or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        if fname in self.extra:
            return str(self.extra[fname])
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


_ISOLATE_PARAMS = {"exts": (".sty", ".cls"), "suffix": ".fixloop-iso"}


def _proj_pair(tmp_path: Path, name: str, local: str, sys: str) -> Path:
    """wdir 放 local 旧件, texmf 放 sys 新件 → 返回 wdir。"""
    wdir = tmp_path / "proj"
    wdir.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    (texmf / name).write_text(sys, encoding="utf-8")
    (wdir / name).write_text(local, encoding="utf-8")
    return wdir


# ------------------------------------------------------- expl3 brace 字面日期


def test_braced_literal_all_expl_variants() -> None:
    """ExplPackage/ExplClass/ExplFile 三变体 brace 第二槽日期全覆盖。"""
    assert _provides_date(
        "\\ProvidesExplPackage{csvsimple-l3}{2021/09/09}{2.2.0}\n"
    ) == (2021, 9, 9)
    assert _provides_date("\\ProvidesExplClass{mycls}{2023-02-10}{1.0}{desc}\n") == (
        2023,
        2,
        10,
    )
    assert _provides_date(
        "\\ProvidesExplFile {tagpdf-ns-latex.def} {2026-01-29}\n"
    ) == (2026, 1, 29)


def test_braced_literal_separator_variants() -> None:
    """日期分隔符 ``/`` ``-`` ``.`` 全收 (csvsimple 用 ``/``, ltxlab 用 ``-``)。"""
    assert _provides_date("\\ProvidesExplPackage{a}{2024.09.27}{v}\n") == (
        2024,
        9,
        27,
    )
    # 槽位前导空白收
    assert _provides_date("\\ProvidesExplPackage{a} { 2024-09-27 }{v}\n") == (
        2024,
        9,
        27,
    )


def test_braced_date_slot_must_be_date() -> None:
    """第二槽非日期 (版本/描述字面) → 不识破 → None。"""
    assert _provides_date("\\ProvidesExplPackage{a}{v2.2.0}{x}\n") is None
    assert _provides_date("\\ProvidesExplPackage{a}\n") is None


def test_plain_provides_braced_second_arg_not_taken() -> None:
    """``\\ProvidesPackage{n}{date}`` texmf 0 实证 —— 不抽, 保守 None。"""
    assert _provides_date("\\ProvidesPackage{a}{2020-01-01}\n") is None


# ------------------------------------------------------- brace 槽宏间址


def test_braced_indirect_def_resolution() -> None:
    """``{n}{\\cs}{v}`` → 同文件 ``\\def\\cs{date}`` 取回 (ltlab 实证面)。"""
    t = (
        "\\def\\ltlabtocdate{2026-01-16}\n"
        "\\ProvidesExplPackage{ltlabtoc}{\\ltlabtocdate}{v1.0}{desc}\n"
    )
    assert _provides_date(t) == (2026, 1, 16)


def test_braced_indirect_def_spaced_forms() -> None:
    """疏松排版 ``\\def \\cs    {date}`` / ``\\gdef`` / ``\\edef`` 同收。"""
    t = (
        "\\def \\whatsnote@date    {2025-11-12}\n"
        "\\ProvidesExplPackage{whatsnote}{\\whatsnote@date}{v}\n"
    )
    assert _provides_date(t) == (2025, 11, 12)
    t2 = (
        "\\gdef\\g@pbs@date@tl{2024/09/16}\n"
        "\\ProvidesExplPackage{pbs}{\\g@pbs@date@tl}{v}\n"
    )
    assert _provides_date(t2) == (2024, 9, 16)


def test_braced_indirect_tl_assignment() -> None:
    """expl3 ``\\tl_(const|set|gset):Nn \\c_*_date_tl {d}`` 赋值面 (acro 族实证)。"""
    for assign in ("\\tl_const:Nn", "\\tl_set:Nn", "\\tl_gset:Nn"):
        t = (
            f"{assign} \\c_acro_date_tl {{2022/04/01}}\n"
            "\\ProvidesExplPackage\n"
            "  {\\c_acro_package_name_tl}\n"
            "  {\\c_acro_date_tl}\n"
            "  {\\c_acro_version_tl}\n"
        )
        assert _provides_date(t) == (2022, 4, 1), assign


def test_braced_indirect_newcommand_def() -> None:
    """``\\*command`` LaTeX2e 赋值面 (pgfmath-xfp 实证, texmf 11 处)。"""
    for assign in (
        "\\newcommand*\\pgfmxfpDate",  # 实证形
        "\\newcommand\\pgfmxfpDate",
        "\\renewcommand*\\pgfmxfpDate",
        "\\renewcommand\\pgfmxfpDate",
        "\\providecommand{\\pgfmxfpDate}",
        "\\newcommand{\\pgfmxfpDate}",  # 花括号 csname 形
    ):
        t = (
            f"{assign}{{2025-01-11}}\n"
            "\\ProvidesExplPackage\n"
            "  {pgfmath-xfp}     {\\pgfmxfpDate}\n"
            "  {\\pgfmxfpVersion} {d}\n"
        )
        assert _provides_date(t) == (2025, 1, 11), assign


def test_arg_separator_comment_text() -> None:
    """docstrip 注释变元间隔 ``{n} %^^A name\\n{d}`` (clistmap/lambdax 实证)。"""
    t = (
        "\\ProvidesExplPackage\n"
        " {clistmap}                                  %^^A Package name\n"
        " {2022-01-29}                                %^^A Release date\n"
        " {1.2}                                       %^^A Release version\n"
    )
    assert _provides_date(t) == (2022, 1, 29)


def test_braced_indirect_getidinfo_ctex_form() -> None:
    r"""ctex.sty 实证: ``\GetIdInfo $Id: …$`` → ``{\ExplFileDate}`` 解出。"""
    t = (
        "\\GetIdInfo$Id: ctex.dtx 13a2256 2022-07-14 18:54:09 +0800 Qing Lee$\n"
        "  {Chinese adapter in LaTeX (CTEX)}\n"
        "\\ProvidesExplPackage{\\ExplFileName}\n"
        "  {\\ExplFileDate}{2.5.10}{\\ExplFileDescription}\n"
    )
    assert _provides_date(t) == (2022, 7, 14)


def test_getidinfo_slash_date_field() -> None:
    """Id 日期槽 ``/`` 分隔亦收 (cdcmd.sty 2021/10/12 实证)。"""
    t = (
        "\\GetIdInfo$Id: cdcmd.dtx 1.0 2021/10/12 00:00:00 +0000 x$\n"
        "\\ProvidesExplPackage{cdcmd}{\\ExplFileDate}{1.0}{d}\n"
    )
    assert _provides_date(t) == (2021, 10, 12)


def test_getidinfo_minus1_version_not_taken() -> None:
    """ver==-1 → expl3 置 ``0000/00/00`` 伪日期 —— 不取, None。"""
    t = (
        "\\GetIdInfo$Id: x.dtx -1 2024-01-01 00:00:00 +0000 x$\n"
        "\\ProvidesExplPackage{x}{\\ExplFileDate}{v}{d}\n"
    )
    assert _provides_date(t) is None


def test_explfiledate_direct_def() -> None:
    """ltxlab 面: ``\\def\\ExplFileDate`` 字面赋值先于 GetIdInfo 解出。"""
    t = (
        "\\def\\ExplFileDate{2026-02-18}%\n"
        "\\ProvidesExplFile{l3debug.def}{\\ExplFileDate}{1.0}\n"
    )
    assert _provides_date(t) == (2026, 2, 18)


# ------------------------------------------------------- 保守 None 面


def test_indirect_unresolvable_is_none() -> None:
    """间址 cs 无字面赋值 → None (猜错即静默毒化 ld<sd 比对)。"""
    t = "\\ProvidesExplPackage{a}{\\never@defined@date}{v}\n"
    assert _provides_date(t) is None


def test_indirect_def_non_date_value_is_none() -> None:
    """cs 有 ``\\def`` 但值非日期 (``\\ExplFileName``=包名) → None；
    且非 ``ExplFileDate`` 的间址不查 ``\\GetIdInfo`` 兜底。"""
    t = (
        "\\def\\ExplFileName{ctex}\n"
        "\\GetIdInfo$Id: ctex.dtx 1.0 2022-07-14 00:00:00 +0000 x$\n"
        "\\ProvidesExplPackage{ctex}{\\ExplFileName}{v}{d}\n"
    )
    assert _provides_date(t) is None


# ------------------------------------------------------- 既有口径回归


def test_bracketed_forms_unchanged() -> None:
    """bracket 字面 + bracket cs 间址 (biblatex v3.12) 口径不动。"""
    assert _provides_date("\\ProvidesPackage{b}[2025/01/01 v3.21 x]\n") == (
        2025,
        1,
        1,
    )
    t = (
        "\\def\\abx@date{2018/11/02}\n"
        "\\ProvidesPackage{biblatex}[\\abx@date\\space v3.12]\n"
    )
    assert _provides_date(t) == (2018, 11, 2)
    assert _provides_date("\\ProvidesPackage{x}[v1.0 notes]\n") is None


def test_providesfile_literal_and_indirect() -> None:
    """``\\ProvidesFile`` 纳入: 字面 1853 / ``[\\filedate]`` 间址 212 实证。"""
    assert _provides_date("\\ProvidesFile{core.tex}[2006/12/22 v1.15]\n") == (
        2006,
        12,
        22,
    )
    t = "\\def\\filedate{2020-05-01}\n\\ProvidesFile{x.def}[\\filedate\\space v2]\n"
    assert _provides_date(t) == (2020, 5, 1)


def test_bracket_comment_continuation_indirect() -> None:
    """``[%`` 注释续行形: expl3.sty ``[%\\n \\ExplFileDate`` —— texmf 61 处。"""
    t = (
        "\\def\\ExplFileDate{2026-01-19}%\n"
        "\\let\\ExplLoaderFileDate\\ExplFileDate\n"
        "\\ProvidesPackage{expl3}\n"
        "  [%\n"
        "    \\ExplFileDate\\space\n"
        "    L3 programming layer (loader)\n"
        "  ]%\n"
    )
    assert _provides_date(t) == (2026, 1, 19)


def test_literal_beats_later_indirect() -> None:
    """口径保持: 字面日期面 (任一字面命中) 先于间址兜底解出。"""
    t = (
        "\\def\\cs@date{1999-01-01}\n"
        "\\ProvidesPackage{a}[\\cs@date\\space v]\n"
        "\\ProvidesPackage{b}[2020-01-01 literal]\n"
    )
    assert _provides_date(t) == (2020, 1, 1)


def test_dual_indirect_first_in_text_wins() -> None:
    """bracket/brace 两间址形同文: 谁文本在前解谁——首间址无解即 ``None``,
    不回退到后出现的可解间址。"""
    t = (
        "\\GetIdInfo$Id: b.dtx 1.0 2022-07-14 00:00:00 +0000 x$\n"
        "\\ProvidesPackage{a}[\\boguscs\\space v]\n"
        "\\ProvidesExplPackage{b}{\\ExplFileDate}{v}{d}\n"
    )
    # 在前的 bracket 间址 ``\boguscs`` 无解 → None (不落到可解的 ``\ExplFileDate``)
    assert _provides_date(t) is None
    t2 = (
        "\\def\\cs@date{2021-03-04}\n"
        "\\ProvidesPackage{a}[\\cs@date\\space v]\n"
        "\\ProvidesExplPackage{b}{\\neverdefined}{v}{d}\n"
    )
    assert _provides_date(t2) == (2021, 3, 4)
    # 反序同口径——brace 间址在前且无解时, 后出现的可解 bracket 间址不兜底
    t3 = (
        "\\def\\cs@date{2021-03-04}\n"
        "\\ProvidesExplPackage{b}{\\neverdefined}{v}{d}\n"
        "\\ProvidesPackage{a}[\\cs@date\\space v]\n"
    )
    assert _provides_date(t3) is None


# ------------------------------------------------------- 遮蔽比对 e2e


def test_e2e_braced_expl3_shadow_compare(tmp_path: Path) -> None:
    """csvsimple 饿门实证面: brace 日期面现在喂得进 ld<sd 闸 → 确证隔离。"""
    wdir = _proj_pair(
        tmp_path,
        "csvsimple-l3.sty",
        "\\ProvidesExplPackage{csvsimple-l3}{2021/09/09}{2.2.0}\n",
        "\\ProvidesExplPackage{csvsimple-l3}{2024/09/27}{2.7.0}\n",
    )
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(tmp_path / "texmf"), None, dict(_ISOLATE_PARAMS)
    )
    assert ok, note
    assert (wdir / "csvsimple-l3.sty.fixloop-iso").is_file()
    assert "2021, 9, 9" in note
    assert "2024, 9, 27" in note


def test_e2e_getidinfo_shadow_compare(tmp_path: Path) -> None:
    """ctex 形: ``{\\ExplFileDate}`` 间址经 ``\\GetIdInfo`` 解出 → 确证隔离。"""
    local = (
        "\\GetIdInfo$Id: ctex.dtx aaaaaaa 2020-01-01 00:00:00 +0000 x$\n"
        "\\ProvidesExplPackage{\\ExplFileName}{\\ExplFileDate}{2.4.0}{d}\n"
    )
    newer = (
        "\\GetIdInfo$Id: ctex.dtx bbbbbbb 2022-07-14 00:00:00 +0000 x$\n"
        "\\ProvidesExplPackage{\\ExplFileName}{\\ExplFileDate}{2.5.10}{d}\n"
    )
    wdir = _proj_pair(tmp_path, "ctex.sty", local, newer)
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(tmp_path / "texmf"), None, dict(_ISOLATE_PARAMS)
    )
    assert ok, note
    assert (wdir / "ctex.sty.fixloop-iso").is_file()


def test_e2e_braced_local_newer_stays(tmp_path: Path) -> None:
    """本地 brace 日期面更新 → ld<sd 不成立, 保留 (不降级)。"""
    wdir = _proj_pair(
        tmp_path,
        "csvsimple-l3.sty",
        "\\ProvidesExplPackage{csvsimple-l3}{2024/09/27}{2.7.0}\n",
        "\\ProvidesExplPackage{csvsimple-l3}{2021/09/09}{2.2.0}\n",
    )
    ok, _note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(tmp_path / "texmf"), None, dict(_ISOLATE_PARAMS)
    )
    assert not ok
    assert (wdir / "csvsimple-l3.sty").is_file()
