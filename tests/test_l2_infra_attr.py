"""L2 归因的基建类豁免——资源缺失/工具链错配签名永不归译文块。

``t_f74894ebc691aaf4`` 实证：``File `algpseudocodex.sty' not found``（file
级、无行号）走文件级兜底把 main.tex 全部块拖去重译/回退——包没装重编
必败，块全灭 ``fallback_orig`` 定 partial。此类修归 fixloop
install/filemap/toolchain 面，不归 L2 重译。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conftest import DOC, scan_doc

from texlate.compile.engine import CompRes
from texlate.repair_l2 import TreeRun, _l2_localize

if TYPE_CHECKING:
    from pathlib import Path

_BODY = (
    "This is a longer paragraph of English text that should definitely be\n"
    "segmented into at least one chunk for translation purposes.\n"
)


def _localize(
    tmp_path: Path, log: str
) -> tuple[dict[str, dict[str, object]], int, list[int]]:
    """单文件工程 + 假 CompRes → （归因表， 错误总数， 全部 chunk.id）。"""
    tex = DOC % _BODY
    main = tmp_path / "main.tex"
    main.write_text(tex, encoding="utf-8")
    scan = scan_doc(_BODY)
    run = TreeRun(
        scans=[(main, scan)],
        trans={},
        chunk_ins={},
        pipe=None,  # localize 不触 pipe——重译臂才用
    )
    res = CompRes(engine="fake", ok=False, workdir=tmp_path, log_text=log)
    hits, n_err = _l2_localize(tmp_path, run, res)
    return hits, n_err, [c.id for c in scan.chunks]


def test_missing_sty_not_attributed(tmp_path: Path) -> None:
    """``File `x.sty' not found`` file 级无行号 → 0 归因（旧行为：全块兜底）。"""
    hits, n_err, _cids = _localize(
        tmp_path, "(./main.tex\n! LaTeX Error: File `algpseudocodex.sty' not found.\n"
    )
    assert hits == {}
    assert n_err == 1


def test_cant_find_file_not_attributed(tmp_path: Path) -> None:
    """``I can't find file `x'``（\\input/openin 系）同样豁免。"""
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! I can't find file `missing.tex'.\nl.5 \\input{missing}\n",
    )
    assert hits == {}


def test_wrapped_signature_still_exempt(tmp_path: Path) -> None:
    """79 列折行把 ``not found`` 切进 ctx 行——head+ctx 窗仍豁免。"""
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: File `algpseudocodex.sty' not\nfound.\n",
    )
    assert hits == {}


def test_missing_tfm_and_graphic_exempt(tmp_path: Path) -> None:
    """TFM 字体缺失与图片加载失败同族豁免。"""
    hits, _n, _c = _localize(
        tmp_path, "(./main.tex\n! Font \\foo=cmr10 at 12.0pt not loadable.\n"
    )
    assert hits == {}
    hits, _n, _c = _localize(
        tmp_path, "(./main.tex\n! Unable to load picture or PDF file 'fig1.eps'.\n"
    )
    assert hits == {}


def test_biber_toolchain_skew_exempt(tmp_path: Path) -> None:
    """biber/biblatex 版本错配——工具链错不归块。"""
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\nmain.bcf:1: biblatex control file version 3.8, expected version 3.11\n",
    )
    assert hits == {}


def test_preamble_machinery_exempt(tmp_path: Path) -> None:
    """装载期/preamble 机关批量豁免——选项表/装载序/包自检译文造不出。

    此类签名常无 ``l.N`` 行号（babel AtBeginDocument 钩、hyperref 驱动
    处理），旧文件级兜底会全块扫射。
    """
    for log in (
        "! Package inputenc Error: inputenc is not designed for xetex or luatex.\n",
        "! Package babel Error: Unknown option 'latin'.\n",
        "! Package babel Error: You haven't defined the language 'ngerman' yet.\n",
        "! Package hyperref Error: Wrong driver option 'dvips'.\n",
        "! LaTeX Error: Option clash for package geometry.\n",
        "! Package cleveref Error: cleveref must be loaded after hyperref.\n",
        "! Package float Error: Unknown float option 'q'.\n",
        "! The key 'acro/list-format' is unknown and is being ignored.\n",
        "! Package `amstex' is obsolete.\n",
        "! Package array Error: Illegal pream-token (\\pt@format): 'c' used.\n",
        "! Illegal unit of measure (pt inserted).\n",
        "! Not a letter.\n",
    ):
        hits, _n, _c = _localize(tmp_path, "(./main.tex\n" + log)
        assert hits == {}, log


def test_latex209_and_pdftex_prim_exempt(tmp_path: Path) -> None:
    """undefined_cs 头被 ctx 顶行改写语义：``\\documentstyle``（源代际）与
    ``\\pdf*`` 原语（xelatex 能力墙）都豁免；普通 ``\\badcs`` 对照仍归。"""
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! Undefined control sequence.\nl.1 \\documentstyle[12pt]{article}\n",
    )
    assert hits == {}
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! Undefined control sequence.\nl.4 \\pdfprimitive\\undefined\n",
    )
    assert hits == {}
    hits, _n, cids = _localize(
        tmp_path, "(./main.tex\n! Undefined control sequence.\nl.4 \\badcs\n"
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}


def test_toolchain_backend_aux_exempt(tmp_path: Path) -> None:
    """版本闸/后端/aux 劈断/收束签名——报错行可落块内也不归因。"""
    for log in (
        "! Critical Package nicematrix Error: Your LaTeX release is too old.\n",
        "! Backend request inconsistent with engine.\n",
        "! Package minted Error: Cannot highlight code.\n",
        "! File ended while scanning use of \\@newl@bel.\n",
        "! Emergency stop.\n",
        "! Fatal error occurred, no output PDF file produced!\n",
    ):
        hits, _n, _c = _localize(tmp_path, "(./main.tex\n" + log)
        assert hits == {}, log


def test_invalid_in_math_in_chunk_still_exempt(tmp_path: Path) -> None:
    """「tex_line 落块内也不归因」实证类：natbib ``\\@citex`` 未定义引用
    标记的报错位在 thebibliography 正文块内（gr-qc/9901082），肇因是
    源级引用机关——重译修不了，归了只会烧块。"""
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: Command \\cite invalid in math mode.\nl.4 \\cite{xx}\n",
    )
    assert hits == {}


def test_struct_signature_strict_attribution(tmp_path: Path) -> None:
    """env_undefined/already_def：报错行严格含块内才归——最近块兜底位
    （结构行）与无行号文件级兜底都不许（revtex4-2 abstract 机关实证）。

    ``l.5`` = ``\\end{document}`` 行：块外但紧贴块尾（gap=0），旧
    nearest 兜底会错归；``l.3``/``l.4`` 在块内。
    """
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: Environment fakeenv undefined.\nl.5 \\begin{fakeenv}\n",
    )
    assert hits == {}, "结构位 env_undefined 不该吃最近块兜底"
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: Environment fakeenv undefined.\n",
    )
    assert hits == {}, "无行号结构签名不吃文件级兜底"
    hits, _n, cids = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: Environment fakeenv undefined.\nl.3 \\begin{fakeenv}\n",
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}, "块内字面 env 幻觉照常归"
    hits, _n, cids = _localize(
        tmp_path,
        "(./main.tex\n! LaTeX Error: Command \\foo already defined.\nl.4 \\newcommand{\\foo}{x}\n",
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}
    # 对照：同结构位 undefined_cs → 最近块兜底照常
    hits, _n, cids = _localize(
        tmp_path, "(./main.tex\n! Undefined control sequence.\nl.5 \\badcs\n"
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}


def test_filelevel_fallback_whitelist(tmp_path: Path) -> None:
    """无行号错误改白名单制：capacity/scanning 族归全块，其他类不归。

    旧行为对一切无行号错全块兜底——algpseudocodex 同型扫射毒化面。
    """
    hits, _n, cids = _localize(
        tmp_path, "(./main.tex\n! TeX capacity exceeded, sorry [input stack].\n"
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}
    hits, _n, _c = _localize(
        tmp_path, "(./main.tex\n! Paragraph ended before \\foo was complete.\n"
    )
    assert set(hits) == {f"0:{cid}" for cid in cids}
    hits, _n, _c = _localize(
        tmp_path,
        "(./main.tex\n! Illegal parameter number in definition of \\foo.\n",
    )
    assert hits == {}


def test_non_infra_error_still_attributed(tmp_path: Path) -> None:
    """对照组：同形态非基建错（无行号 file 级）仍走兜底归全块。"""
    hits, n_err, cids = _localize(
        tmp_path, "(./main.tex\n! Undefined control sequence.\n"
    )
    assert n_err == 1
    assert set(hits) == {f"0:{cid}" for cid in cids}
