r"""``\input`` 尾参操作数排除 + pending.py COND 镜像钉版（inputtail 车道）。

两簇实格泄漏（kvdig ae685ff 后的两个 handoff）：

- ``\input`` 计数尾参操作数（2403.00100:886 实格）：``\clubpenalty=5000
  \input{file}``——``\input`` 被 ``_OPERAND_BASE`` 的 cs 备择吃成 factor
  base 并入 ``[[CMD]]``，``{file}`` 组孤儿化裸落 surface 被译。TeX 数/胶
  扫遇不可展开 ``\input`` 即止（xetex 实证 ``\count0=5000\input{f}`` 数
  =5000、``\input`` 照常执行）——``INPUT_SCAN_CMDS`` 全族（``\include``/
  ``\import``/``\subfile``/``\@input`` 同带文件参）+ ``\endinput`` 永不
  是数/胶成分，``_OPERAND_CS`` 前瞻排除。
- pending.py COND 镜像缺口：``_handle_cond`` 的 ``_COND_GROUP_ARGS``
  白名单吸收（args.py kvdig 设计）在组面从未有对价——组内 ``\iftoggle``
  只盖 cs 本体 ``{tag}`` 名槽裸落；``_pend_spec_of`` 对 COND_RX 名返
  ``(None,"")``，宏尾 ``\x{\iftoggle}`` + ``\x{tg}`` 调用点参吸不回组。

机制：``_pend_spec_of`` 白名单名返 ``["m"]*n`` 槽 → 组尾 ``\iftoggle``
  未绑名槽成 pending → ``_absorb_pending`` 把调用点 ``{tg}`` 拉进组；
``_grp_scan`` COND 行再吃 ``{..}`` 名槽并入 ``[[COND]]`` 覆盖。两臂都
不动 ``{T}{F}`` 支（散文照译）与表外 ``\if*`` 旗标（``{`` 是分支内容）。

每条过公共不变式（``reconstruct == tex`` + 校验零告警 + 无缝平铺）。
"""

from _segkit import ph_bodies, scan_prose
from _segkit import (
    scan_art as scan,
)
from conftest import blob

# ----------------------------------------------------------- ``\input`` 操作数排除


def test_input_after_count_assign_not_operand() -> None:
    r"""``\clubpenalty=5000\input{f}`` 实格形——``\input`` 不进 ``[[CMD]]``
    操作数，``{file}`` 组随 input 路绑定不裸译。"""
    res = scan_prose(
        "\\begin{sloppypar}\\hyphenpenalty=5000\\widowpenalty=500"
        "\\clubpenalty=5000\\input{EXO-22-011-public-authorlist.tex}"
        "\\end{sloppypar}"
    )
    assert "EXO-22-011-public-authorlist" not in blob(res)
    assert not any("clubpenalty=5000\\input" in b for b in ph_bodies(res))
    assert any(b.rstrip().endswith("\\clubpenalty=5000") for b in ph_bodies(res))
    assert ("EXO-22-011-public-authorlist.tex" in {n for _, n in res.inputs}) or any(
        "\\input{EXO-22-011-public-authorlist.tex}" in p.text for p in res.pieces
    )


def test_include_after_assign_not_operand() -> None:
    r"""``\\tolerance=500\\include{ch1}``——``\\include`` 同族排除。"""
    res = scan_prose("\\tolerance=500\\include{chapter-one}")
    assert "chapter-one" not in blob(res)
    assert not any("tolerance=500\\include" in b for b in ph_bodies(res))


def test_import_two_arg_after_assign() -> None:
    r"""``\\count0=5\\import{dir}{file}`` 双参形——两 ``{..}`` 都不裸译。"""
    res = scan_prose("\\count0=5\\import{subdir}{the-file}")
    assert "subdir" not in blob(res)
    assert "the-file" not in blob(res)
    assert not any("count0=5\\import" in b for b in ph_bodies(res))


def test_endinput_not_operand() -> None:
    r"""``\\count0=5\\endinput``——换源哨兵不被操作数吞，其后内容截停。"""
    res = scan(
        "Prose before keeps the run alive and gives context here.\n"
        "\\count0=5\\endinput\n"
        "afterendinput prose that must never be scanned."
    )
    assert "afterendinput" not in blob(res)
    assert not any("count0=5\\endinput" in b for b in ph_bodies(res))


def test_register_cs_operand_still_eaten() -> None:
    r"""回归闸：合法 cs 操作数照收——``\\hskip0.5\\baselineskip`` 全尾连进
    一个 literal 覆盖段（寄存器是 ``<dimen>`` 真因子，不在排除表；skip 类
    尾不出 ``[[CMD]]`` ph 而整段落 literal piece）。"""
    res = scan_prose("\\hskip0.5\\baselineskip plus 1pt")
    assert "baselineskip" not in blob(res)
    assert "plus" not in blob(res)
    assert "\\hskip0.5\\baselineskip plus 1pt" in res.protected_tex


def test_chained_operand_still_eaten() -> None:
    r"""回归闸：因子×基链照收——``\\multiply\\count0 by -4\\count1``。"""
    res = scan_prose("\\multiply\\count0 by -4\\count1")
    assert "count1" not in blob(res)
    assert any("by -4\\count1" in b for b in ph_bodies(res))


def test_dimen_plus_relax_tail_still_eaten() -> None:
    r"""回归闸：``\\vskip 3pt plus 1pt\\relax`` 全尾连进一个 literal 覆盖段
    （``\\relax`` 终止符同被吸收，``plus`` 胶续不泄 surface）。"""
    res = scan_prose("\\vskip 3pt plus 1pt\\relax")
    assert "3pt" not in blob(res)
    assert "\\vskip 3pt plus 1pt\\relax" in res.protected_tex


# ----------------------------------------------------------- pending.py COND 镜像


def test_grp_scan_iftoggle_name_absorbed() -> None:
    r"""组内 ``\\iftoggle{tg}``——``{tg}`` 名槽并入 ``[[COND]]``，``{T}{F}``
    支留 surface 照译（``_grp_scan`` COND 行 ``_COND_GROUP_ARGS`` 对价）。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\iftoggle{tg}{true-branch words}{false-branch} post}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here \\vv and the "
        "sentence continues with more English words afterwards for sure."
    )
    assert "tg" not in blob(res).split()
    assert any("\\iftoggle{tg}" in b for b in ph_bodies(res, "COND"))
    assert "true-branch words" in blob(res)


def test_grp_scan_ifstrequal_two_slots() -> None:
    r"""组内 ``\\ifstrequal{ka}{kb}`` 双名槽同收。"""
    res = scan(
        "\\newcommand{\\vv}{\\ifstrequal{ka}{kb}{true-branch words}{false}}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here \\vv and the "
        "sentence continues with more English words afterwards for sure."
    )
    assert "ka" not in blob(res).split()
    assert "kb" not in blob(res).split()
    assert any("\\ifstrequal{ka}{kb}" in b for b in ph_bodies(res, "COND"))
    assert "true-branch words" in blob(res)


def test_pend_iftoggle_call_arg_absorbed() -> None:
    r"""跨界待绑：``\\x{\\iftoggle}`` 宏尾 + ``\\x{tg}{T}{F}`` 调用点参——
    ``{tg}`` 吸回组并入 ``[[COND]]`` 覆盖，``{T}{F}`` 支留 surface。"""
    res = scan(
        "\\newcommand{\\x}{\\iftoggle}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here "
        "\\x{tg}{true-branch words}{false-branch} and the sentence continues "
        "with more English words afterwards for sure."
    )
    assert "tg" not in blob(res).split()
    assert any("\\iftoggle{tg}" in b for b in ph_bodies(res, "COND"))
    assert "true-branch words" in blob(res)


def test_pend_ifstrequal_call_args_absorbed() -> None:
    r"""跨界双名槽：``\\x{\\ifstrequal}`` + ``\\x{ka}{kb}{T}{F}``——``{ka}``
    ``{kb}`` 吸回并入 ``[[COND]]``。"""
    res = scan(
        "\\newcommand{\\x}{\\ifstrequal}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here "
        "\\x{ka}{kb}{true-branch words}{false} and the sentence continues "
        "with more English words afterwards for sure."
    )
    assert "ka" not in blob(res).split()
    assert "kb" not in blob(res).split()
    assert any("\\ifstrequal{ka}{kb}" in b for b in ph_bodies(res, "COND"))
    assert "true-branch words" in blob(res)


def test_grp_scan_unlisted_if_brace_stays() -> None:
    r"""负例：表外 ``\\iffoo{..}``——``{`` 是分支散文非名槽，组内照常可挖。"""
    res = scan(
        "\\newcommand{\\vv}{\\iffoo{branch prose words}}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here \\vv and the "
        "sentence continues with more English words afterwards for sure."
    )
    assert "branch prose words" in blob(res)
    assert any(b.rstrip() == "\\iffoo" for b in ph_bodies(res, "COND"))


def test_pend_unlisted_if_no_absorb() -> None:
    r"""负例：表外 ``\\x{\\iffoo}`` + ``\\x{branch}``——``{branch}`` 不吸回，
    散文组照常进 chunk。"""
    res = scan(
        "\\newcommand{\\x}{\\iffoo}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here \\x{branch "
        "prose words} and the sentence continues afterwards for sure."
    )
    assert "branch prose words" in blob(res)
    assert any(b.rstrip() == "\\iffoo" for b in ph_bodies(res, "COND"))
