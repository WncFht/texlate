r"""fixloop aux 截断重试规则（2211.13013 闭环·引擎自产臂）。

taxonomy ``aux_scan_eof`` 接 ``File ended while scanning use of \@newl@bel``
签名 → ``aux_purge_regen`` 规则调 ``purge_corrupt_intermediates`` 删损坏
可再生中间件。shipped 侧归 transcode.INTERMEDIATE_SUFFIXES 转码，本侧管
引擎自产件的运行时截断。
"""

from pathlib import Path

from _fixloopkit import (
    MAIN_TEX,
    XETEX_CLEAN_LOG,
    MockEngine,
    params,
    rs,
    when_cond_ok,
)

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, fixloop
from texlate.compile.logparse import parse_text

_EOF_LOG = (
    "This is XeTeX\n(./main.aux\n! File ended while scanning use of \\@newl@bel.\n"
    "<inserted text>\n                \\par\nl.5 \\begin{document}\n"
)


# ---------------------------------------------------------------- taxonomy
def test_aux_eof_classifies_with_payload() -> None:
    rep = parse_text(_EOF_LOG)
    cat, pay = rs().taxonomy.classify(rep)
    assert cat == "aux_scan_eof"
    assert pay == "newl@bel"  # payload_group=1 抓到回读宏名


def test_aux_eof_beats_emergency_in_ctx8() -> None:
    """'!' 行后 ctx8 混入 Emergency stop 不抢签（条目先于 emergency 评估）。"""
    log = _EOF_LOG + "Emergency stop\n!  ==> Fatal error occurred\n"
    rep = parse_text(log)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "aux_scan_eof"


def test_generic_scan_eof_not_aux() -> None:
    """非回读宏的 EOF 扫描（如截断的 main.tex 撞上 \\section）不归本类。"""
    rep = parse_text("! File ended while scanning use of \\section.\nl.9 x\n")
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "runaway_scan"  # 2026-09-17 通用签名接管非 aux 宏 (aux 族仍专属)


# ---------------------------------------------------------------- builtin 单测
def _purge(wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return TRANSFORM_FNS["purge_corrupt_intermediates"](ctx, None, None, {})


def test_purge_deletes_only_corrupt(tmp_path: Path) -> None:
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{t\xe4\xb8")
    (tmp_path / "main.toc").write_bytes("\\contentsline{章}{一}{1}\n".encode())
    (tmp_path / "keep.aux").write_bytes(b"\\newlabel{b}{{1}{1}{ok}}\n")
    (tmp_path / "main.bib").write_bytes(b"@x{k,title={\xe9}}\n")  # 非 utf-8 但非中间件
    ok, note = _purge(tmp_path)
    assert ok
    assert "main.aux" in note
    assert not (tmp_path / "main.aux").exists()
    assert (tmp_path / "main.toc").exists()  # 完整 utf-8 + 尾换行 = 健康
    assert (tmp_path / "keep.aux").exists()
    assert (tmp_path / "main.bib").exists()


def test_purge_catches_clean_boundary_truncation(tmp_path: Path) -> None:
    """边界恰好落在字符缝：可解码但末行不完整（TeX 完整行必以 \\n 收尾）。"""
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{ok}")
    ok, _ = _purge(tmp_path)
    assert ok
    assert not (tmp_path / "main.aux").exists()


def test_purge_no_corrupt_returns_false(tmp_path: Path) -> None:
    (tmp_path / "main.aux").write_bytes(b"\\relax\n\\newlabel{a}{{1}{1}{ok}}\n")
    ok, _ = _purge(tmp_path)
    assert not ok
    assert (tmp_path / "main.aux").exists()


# ---------------------------------------------------------------- 端到端
def test_fixloop_aux_eof_roundtrip(tmp_path: Path) -> None:
    """截断 aux 由 round 前 _sweep_bad_aux 预清扫移除 —— 首轮编译即不吃毒件。

    126683d 起每轮 compile 前引擎先扫 aux 族 (无尾换行/花括号不闭) —— 比
    aux_scan_eof 签名+规则路径更早一层; 规则仍兜底「行界完整但带非法
    UTF-8」的中间件 (见下一个测试)。
    """
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{t\xe4\xb8")
    eng = MockEngine([{"log": XETEX_CLEAN_LOG, "pdf": True}], probe_cwd=False)
    cell = fixloop(tmp_path, eng, ruleset=rs())
    assert cell["verdict"] == "clean"
    assert not (tmp_path / "main.aux").exists()  # 损坏件已删, 下遍引擎重生成


def test_fixloop_aux_eof_purge_fallback(tmp_path: Path) -> None:
    """行界完整 + 花括号闭合但含非法 UTF-8 的 aux —— 预清扫放行, aux_scan_eof
    签名命中后 aux_purge_regen 规则仍是最后一道。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(
        b"\\newlabel{a}{{1}{1}{\xe4\xb8}}\n\\newlabel{b}{{2}{2}{ok}}\n"
    )
    eng = MockEngine(
        [{"log": _EOF_LOG, "pdf": False}, {"log": XETEX_CLEAN_LOG, "pdf": True}],
        probe_cwd=False,  # 原 _Eng 恒 probe→None 保真
    )
    cell = fixloop(tmp_path, eng, ruleset=rs())
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == "aux_purge_regen" for a in cell["actions"])
    assert not (tmp_path / "main.aux").exists()


def test_fixloop_aux_eof_no_corrupt_falls_through(tmp_path: Path) -> None:
    """签名命中但无损坏件 → 规则 applied=False, 不误伤健康 aux。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{ok}}\n")
    eng = MockEngine([{"log": _EOF_LOG, "pdf": False}] * 4, probe_cwd=False)
    cell = fixloop(tmp_path, eng, ruleset=rs())
    assert cell["verdict"] != "clean"
    assert (tmp_path / "main.aux").exists()
    assert all(a["rule"] != "aux_purge_regen" for a in cell["actions"])


# ════════════════════════════════════════════════════════════════
# scaneof 扩臂 (2026-09-20, m1k aux-malformed 簇 11 singles):
# 同根三签名面 —— (b) runaway_scan 读端落 aux 书写族 cs;
# (c) undefined_cs 站点直落 *.aux:N (良好字节形写端错配 →
# payload 锚定内容删, 损坏谓词整类放行这种件)。
# ════════════════════════════════════════════════════════════════

_RUNAWAY_ABX_LOG = (
    "(./root.aux\n! File ended while scanning use of \\abx@aux@cite.\n"
    "<inserted text>\n                \\par\nl.5 \\begin{document}\n"
)
_UNDEF_AUX_LOG = (
    "root.aux:67: Undefined control sequence.\nl.67 \\abx@aux@cite{0}{SAUMON20221}\n"
)


def _params() -> dict:
    """shipped ``aux_purge_regen`` params 直取——yaml 改值即测新面, 不养陈旧拷贝。"""
    return dict(params("aux_purge_regen"))


def _purge2(wdir: Path, payload: str | None) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return TRANSFORM_FNS["purge_corrupt_intermediates"](ctx, None, payload, _params())


# ---------------------------------------------------------------- 派发臂
def test_runaway_abx_arm_dispatches(tmp_path: Path) -> None:
    """(b) runaway_scan|\\abx@aux@cite —— zh 2503.10110 实签名。"""
    rep = parse_text(_RUNAWAY_ABX_LOG)
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("runaway_scan", "\\abx@aux@cite")
    head = (rep.first or "") + "\n" + (rep.ctx or "")
    assert when_cond_ok("aux_purge_regen", cat, pay, head, tmp_path)


def test_undefined_cs_aux_site_dispatches(tmp_path: Path) -> None:
    """(c) undefined_cs @ *.aux:N —— base 2503.10110 root.aux:67 实签名。"""
    rep = parse_text(_UNDEF_AUX_LOG)
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("undefined_cs", "abx@aux@cite")
    head = (rep.first or "") + "\n" + (rep.ctx or "")
    assert when_cond_ok("aux_purge_regen", cat, pay, head, tmp_path)


def test_runaway_non_aux_reader_rejected(tmp_path: Path) -> None:
    """runaway_scan|\\next 等非 aux 读端不抢 —— 让位 163.5/164 规则。"""
    rep = parse_text("! File ended while scanning use of \\next.\nl.9 x\n")
    cat, pay = rs().taxonomy.classify(rep)
    assert cat == "runaway_scan"
    head = (rep.first or "") + "\n" + (rep.ctx or "")
    assert not when_cond_ok("aux_purge_regen", cat, pay, head, tmp_path)


def test_undefined_cs_tex_site_rejected(tmp_path: Path) -> None:
    """undefined_cs @ .tex 站点不归本簇 —— cs_targeted_fix 等下游处理。"""
    head = "main.tex:5: Undefined control sequence.\nl.5 \\myfoo\n"
    assert not when_cond_ok("aux_purge_regen", "undefined_cs", "myfoo", head, tmp_path)


def test_undefined_cs_no_payload_rejected(tmp_path: Path) -> None:
    """payload_required —— 无 payload 的 undefined_cs 不进 (b)(c) 臂。"""
    head = "root.aux:67: Undefined control sequence.\nl.67 x\n"
    assert not when_cond_ok("aux_purge_regen", "undefined_cs", None, head, tmp_path)


# ---------------------------------------------------------------- payload 锚定删
def test_purge_skewed_aux_by_payload(tmp_path: Path) -> None:
    """行界齐整/括号闭合/utf-8 合法的 .aux 含错配写端 cs → 锚定删。"""
    (tmp_path / "root.aux").write_bytes(
        b"\\relax\n\\abx@aux@cite{0}{SAUMON20221}\n\\abx@aux@segm{0}{0}{x}\n"
    )
    ok, note = _purge2(tmp_path, "\\abx@aux@cite")
    assert ok
    assert "skewed" in note
    assert not (tmp_path / "root.aux").exists()


def test_purge_payload_allowlist_blocks_universal_cs(tmp_path: Path) -> None:
    """bibcite/newlabel 等通用件不入白名单 —— 健康 aux (xr 外链) 不误删。"""
    (tmp_path / "main.aux").write_bytes(b"\\bibcite{k}{{1}{2020}{A}}\n")
    ok, _ = _purge2(tmp_path, "\\bibcite")
    assert not ok
    assert (tmp_path / "main.aux").exists()


def test_purge_payload_boundary_no_prefix_match(tmp_path: Path) -> None:
    """(?![A-Za-z@]) 边界 —— \\abx@aux@citeXYZ 不算 \\abx@aux@cite 命中。"""
    (tmp_path / "root.aux").write_bytes(b"\\abx@aux@citeXYZ{0}\n")
    ok, _ = _purge2(tmp_path, "\\abx@aux@cite")
    assert not ok
    assert (tmp_path / "root.aux").exists()


def test_purge_payload_non_aux_ext_skipped(tmp_path: Path) -> None:
    """payload 臂只扫 payload_purge_exts —— .toc 含同款 cs 不删。"""
    (tmp_path / "main.toc").write_bytes(b"\\abx@aux@cite{0}{k}\n")
    ok, _ = _purge2(tmp_path, "\\abx@aux@cite")
    assert not ok
    assert (tmp_path / "main.toc").exists()


def test_purge_corrupt_still_works_with_params(tmp_path: Path) -> None:
    """原损坏谓词面在新 params 下不变 —— mid-macro 截断照删。"""
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{t\xe4\xb8")
    ok, note = _purge2(tmp_path, "abx@aux@cite")
    assert ok
    assert "corrupt" in note


# ---------------------------------------------------------------- 端到端
def test_fixloop_runaway_bibcite_corrupt_roundtrip(tmp_path: Path) -> None:
    """(b) runaway|\\bibcite + utf-8 劈断 aux (行界完整括号闭合 →
    预清扫放行) → aux_purge_regen 兜底删, 下遍重生成。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(
        b"\\bibcite{k}{{\xe4\xb8}}\n\\newlabel{a}{{1}{1}{ok}}\n"
    )
    log = "(./main.aux\n! File ended while scanning use of \\bibcite.\nl.5 x\n"
    eng = MockEngine(
        [{"log": log, "pdf": False}, {"log": XETEX_CLEAN_LOG, "pdf": True}],
        probe_cwd=False,
    )
    cell = fixloop(tmp_path, eng, ruleset=rs())
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == "aux_purge_regen" for a in cell["actions"])
    assert not (tmp_path / "main.aux").exists()


def test_fixloop_undefined_cs_skewed_aux_roundtrip(tmp_path: Path) -> None:
    """(c) undefined_cs @ root.aux:N + 良好形错配 aux → payload 锚定删。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "root.aux").write_bytes(
        b"\\relax\n\\abx@aux@cite{0}{SAUMON20221}\n\\abx@aux@segm{0}{0}{x}\n"
    )
    eng = MockEngine(
        [{"log": _UNDEF_AUX_LOG, "pdf": False}, {"log": XETEX_CLEAN_LOG, "pdf": True}],
        probe_cwd=False,
    )
    cell = fixloop(tmp_path, eng, ruleset=rs())
    assert any(a["rule"] == "aux_purge_regen" for a in cell["actions"])
    assert not (tmp_path / "root.aux").exists()
