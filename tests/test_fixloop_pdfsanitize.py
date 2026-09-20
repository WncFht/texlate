r"""pdfsanitize lane (2026-09-19): ``pdf_asset_sanitize`` 内嵌 pdf 重序列化规则。

xlinkobj lane 5 格普查 (1404.5668/1206.0148/1907.00277/2403.05523/2412.19437):
工程船货 .pdf 对象结构残缺 → xdvipdfmx ``pdf:image`` import 回 NULL →
``xdvipdfmx:fatal: pdf_link_obj(): passed invalid object`` → xelatex SIGPIPE。
签名只走 stderr→stdout_tail (.log 干净) —— ``_report_of`` 把 ``\w+:fatal:``
行归一成 '!' 行使签名对 ctx_suggests 可见, 轮内归 ``other`` 类。修复 =
全量内嵌 .pdf ``gs -sDEVICE=pdfwrite`` 重序列化 (内容不动只改对象布局,
原件留 ``.fixloop-rd`` 备份兼幂等标记)。
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from texlate.compile.fixloop import actions, builtins, load_ruleset
from texlate.compile.fixloop._builtins_misc import _pfa_to_pfb_bytes
from texlate.compile.fixloop.builtins import pdf_asset_sanitize, pfa_to_pfb
from texlate.compile.fixloop.engine import LoopCtx, Rule, _report_of
from texlate.compile.logparse import ErrReport


class _Eng:
    """builtin_transform/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_FATAL = "xdvipdfmx:fatal: pdf_link_obj(): passed invalid object."
_ERR_HEAD = f"! {_FATAL}\n\nNo output PDF file written."


def _ctx(tmp_path: Path, err_head: str = _ERR_HEAD, runner: object = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        runner=runner,
        err_head=err_head,
    )


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "pdf_asset_sanitize")


def _apply(tmp_path: Path, runner: object = None) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path, runner=runner), _Eng(), None, ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _ERR_HEAD) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


def _which_gs(name: str) -> str | None:
    return "/usr/bin/gs" if name == "gs" else None


def _which_none(_name: str) -> None:
    return None


def _gs_ok(argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    """假 gs pdfwrite: ``-o`` 目标写重序列化伪 pdf, rc=0。"""
    Path(argv[argv.index("-o") + 1]).write_bytes(b"%PDF-1.7 reserialized\n%%EOF\n")
    return 0, "", 0.05, False


def _gs_fail(_argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    return 1, "gs died", 0.05, False


# ─────────────────────── _report_of 签名可见性 plumbing ───────────────────────


def _res(tmp_path: Path, log_text: str, stdout_tail: str) -> SimpleNamespace:
    log = tmp_path / "main.log"
    log.write_text(log_text, encoding="utf-8")
    return SimpleNamespace(
        log_path=log, log_text="", stdout_tail=stdout_tail, timed_out=False
    )


def test_report_of_surfaces_driver_fatal(tmp_path: Path) -> None:
    """干净 .log + stdout_tail ``*:fatal:`` → 归一成 '!' 行使签名可见。"""
    res = _res(
        tmp_path,
        "This is XeTeX\nOutput written on main.xdv\n",
        f'xdvipdfmx:warning: Didn\'t find "endobj".\n{_FATAL}\n\nNo output PDF file written.\n',
    )
    rep = _report_of(res, [])
    assert rep.n_bang == 1
    assert "pdf_link_obj" in (rep.first or "")
    cat, _pay = load_ruleset().taxonomy.classify(rep, timed_out=False)
    assert cat == "other"  # 签名无专属类目 → other 兜底, 规则 when 面


def test_report_of_plain_stdout_keeps_log_report(tmp_path: Path) -> None:
    """stdout_tail 无 error/fatal 行 → .log 报告保留 (归一不无事生非)。"""
    res = _res(
        tmp_path,
        "This is XeTeX\nOutput written on main.pdf (1 page).\n",
        "some benign console noise\n",
    )
    rep = _report_of(res, [])
    assert rep.first is None
    assert rep.raw.startswith("This is XeTeX")


def test_report_of_log_errors_win_over_fatal(tmp_path: Path) -> None:
    """.log 有 '!' 错 → 不查 stdout_tail (先修 TeX 错, fatal 下轮再见)。"""
    res = _res(
        tmp_path,
        "! Undefined control sequence.\nl.5 \\foo\n",
        f"{_FATAL}\n",
    )
    rep = _report_of(res, [])
    assert rep.first == "! Undefined control sequence."


def test_report_of_empty_log_falls_back_anyway(tmp_path: Path) -> None:
    """.log 空 → stdout_tail 兜底照旧 (rep.raw==\"\" 臂不依赖 fatal)。"""
    res = _res(tmp_path, "", "plain output, no errors\n")
    rep = _report_of(res, [])
    assert rep.raw == "plain output, no errors\n"


# ─────────────────────────── rule 注册 / 闸 ───────────────────────────


def test_pdfsanitize_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 18.5  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "pdf_asset_sanitize"
    assert builtins.TRANSFORM_FNS["pdf_asset_sanitize"] is pdf_asset_sanitize


def test_pdfsanitize_cond_fires_on_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pdf_link_obj invalid-object 签名 err_head → 闸放行。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    ok, why = _cond(tmp_path)
    assert ok, why


def test_pdfsanitize_cond_declines_unrelated_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无关 other 类目错 → ctx_suggests 拒。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    ok, _why = _cond(tmp_path, "LaTeX Error: Something else entirely")
    assert not ok


def test_pdfsanitize_cond_declines_no_gs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gs 缺席 → tool_available 拒。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    ok, why = _cond(tmp_path)
    assert not ok
    assert "gs" in why


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_pdfsanitize_rewrites_pdf_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内嵌 .pdf 全量重写: 内容替换 + 原件留 .fixloop-rd 备份。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "img").mkdir()
    (tmp_path / "img/bad.pdf").write_bytes(b"%PDF-1.4 malformed-no-endobj")
    (tmp_path / "fig2.pdf").write_bytes(b"%PDF-1.4 token-per-line")
    (tmp_path / "main.tex").write_text("\\includegraphics{img/bad.pdf}\n")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert ok, note
    assert "2/2" in note
    assert (tmp_path / "img/bad.pdf").read_bytes() == b"%PDF-1.7 reserialized\n%%EOF\n"
    # 原件备份在 marker, 兼「已 sanitize」幂等标记
    assert (tmp_path / "img/bad.pdf.fixloop-rd").read_bytes() == (
        b"%PDF-1.4 malformed-no-endobj"
    )
    assert (tmp_path / "fig2.pdf.fixloop-rd").is_file()


def test_pdfsanitize_skips_main_and_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主输出 pdf / 隐藏快照 / _texmf 封装树非内嵌图件 —— 不动。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "main.pdf").write_bytes(b"%PDF main output")
    (tmp_path / ".fixloop-entry.pdf").write_bytes(b"%PDF floor snap")
    (tmp_path / "_texmf/pkg").mkdir(parents=True)
    (tmp_path / "_texmf/pkg/doc.pdf").write_bytes(b"%PDF vendored")
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert ok, note
    assert "1/1" in note
    assert (tmp_path / "main.pdf").read_bytes() == b"%PDF main output"
    assert (tmp_path / ".fixloop-entry.pdf").read_bytes() == b"%PDF floor snap"
    assert (tmp_path / "_texmf/pkg/doc.pdf").read_bytes() == b"%PDF vendored"


def test_pdfsanitize_idempotent_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """marker 在场 = 已 sanitize → 跳过; 全 skipped → False 让位。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    (tmp_path / "fig.pdf.fixloop-rd").write_bytes(b"%PDF original")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert not ok
    assert "already sanitized" in note
    assert (tmp_path / "fig.pdf").read_bytes() == b"%PDF figure"


def test_pdfsanitize_no_pdf_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程零内嵌 .pdf → False (签名命中但无可修面)。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "main.tex").write_text("\\includegraphics{img.png}\n")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert not ok
    assert "no pdf assets" in note


def test_pdfsanitize_gs_failure_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gs 全败 → False 不谎报, 原件不动 (失败残留清掉)。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"%PDF figure")
    ok, note = _apply(tmp_path, runner=_gs_fail)
    assert not ok
    assert "0/1 sanitized" in note
    assert src.read_bytes() == b"%PDF figure"
    assert not (tmp_path / "fig.pdf.fixloop-tmp").exists()


def test_pdfsanitize_no_gs_builtin_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """builtin 直调 (绕闸): gs 缺席 → False (condition 之外再保险)。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    ok, note = pdf_asset_sanitize(_ctx(tmp_path), _Eng(), None, {})
    assert not ok
    assert "no gs" in note


@pytest.mark.skipif(shutil.which("gs") is None, reason="gs not on PATH")
def test_pdfsanitize_real_gs_repairs_malformed(tmp_path: Path) -> None:
    """真 gs 端到端: 剥 endobj 的残缺 pdf → 重序列化非空产出 + 原件备份。"""
    good = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
        b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
        b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\n"
        b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    )
    i = good.rfind(b"endobj\n")
    src = tmp_path / "fig.pdf"
    src.write_bytes(good[:i] + good[i + len(b"endobj\n") :])
    ok, note = pdf_asset_sanitize(_ctx(tmp_path), _Eng(), None, {})
    assert ok, note
    out = src.read_bytes()
    assert out.startswith(b"%PDF-")
    assert len(out) > 200  # noqa: PLR2004 - 重序列化产物量断言
    assert (tmp_path / "fig.pdf.fixloop-rd").is_file()


def test_pdfsanitize_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 114  # noqa: PLR2004 - 库规模断言


# ════════════════════════════════════════════════════════════════
# pfa lane (2026-09-19): ``pfa_to_pfb`` ASCII Type1 → usertree .pfb 规则
# ════════════════════════════════════════════════════════════════
#
# 1907.03923 (stagerun-loop3) 实证: ``\usepackage{pigpen}`` 引用在用的
# dist 侧 ASCII Type1 字体 (\pigpenfont 邻接符, xymatrix 内 ~6 处) →
# ``pigpen.map`` 行 ``pigpen <pigpen.pfa`` 折进 pdftex.map → xdvipdfmx
# 按扩展名硬拒 .pfa (fatal 落 stdout_tail, ``other`` 类目同族派发)。
# 修复 = 纯 python t1binary 等价物 (eexec 密文 hex 解码原样进 PFB 段二,
# 不解密) + 三层 usertree 遮蔽: type1 产物 / TEXMFVAR 位 pdftex.map /
# 源 <pkg>.map dvips 面 (updmap 再生保险)。


class _PfaEng:
    """pfa_to_pfb 路径引擎替身: texmfhome usertree + 具名 probe 表。"""

    name = "xelatex"

    def __init__(self, texmfhome: Path | None, files: dict[str, Path]) -> None:
        self.texmfhome = texmfhome
        self._files = files

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (cand := cwd / fname).is_file():
            return str(cand)
        hit = self._files.get(fname)
        return str(hit) if hit is not None else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_PFA_FATAL = "xdvipdfmx:fatal: Sorry, pfa format not supported; please convert the font to pfb, e.g., with t1binary."
_PFA_ERR_HEAD = f"! {_PFA_FATAL}\n\nNo output PDF file written."

#: 真件形合成 .pfa —— header + ``currentfile eexec`` + hex 密文行 +
#: 连 ``0`` 填充 + ``cleartomark``/``{restore}if`` 尾 (pigpen.pfa 同构)。
_PFA_BYTES = (
    b"%!PS-AdobeFont-1.0: fakefont 001.000\n"
    b"%%Title: fakefont\n"
    b"11 dict begin\n"
    b"/FontInfo 4 dict dup begin\nend readonly def\n"
    b"/FontName /fakefont def\n"
    b"currentfile eexec\n"
    + b"AB" * 32
    + b"\n"
    + b"CD" * 32
    + b"\n"
    + b"0" * 512
    + b"\ncleartomark\n{restore}if\n"
)

_PDFTEX_MAP = (
    "cmr10 CMR10 <cmr10.pfb\n"
    "% pigpen.map\n"
    "pigpen <pigpen.pfa\n"
    "% rsfs.map\n"
    "rsfs10 rsfs10 <rsfs10.pfb\n"
)


_PFB_MAGIC = 0x80
_PFB_EOF = 3


def _pfb_segments(pfb: bytes) -> list[tuple[int, bytes]]:
    """PFB 帧回放 → ``[(tag, payload)]`` (tag 3 = EOF, 无长度域)。"""
    segs: list[tuple[int, bytes]] = []
    i = 0
    while i < len(pfb):
        assert pfb[i] == _PFB_MAGIC
        tag = pfb[i + 1]
        if tag == _PFB_EOF:
            segs.append((_PFB_EOF, b""))
            break
        n = int.from_bytes(pfb[i + 2 : i + 6], "little")
        segs.append((tag, pfb[i + 6 : i + 6 + n]))
        i += 6 + n
    return segs


def _pfa_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    """假系统树: wdir/sysroot/usertree 三兄弟 → (wdir, texmfhome, probe 表)。

    sysroot 必须在 wdir 之外 —— 遮蔽臂靠 ``map 在工程内?`` 二分 (系统树件
    落 TEXMFVAR 副本, 工程内件就地改写)。
    """
    wdir = tmp_path / "wdir"
    wdir.mkdir()
    texmf = tmp_path / "usertree"
    sysd = tmp_path / "sysroot"
    pfa = sysd / "fonts/type1/public/pigpen/pigpen.pfa"
    pfa.parent.mkdir(parents=True)
    pfa.write_bytes(_PFA_BYTES)
    srcmap = sysd / "fonts/map/dvips/pigpen/pigpen.map"
    srcmap.parent.mkdir(parents=True)
    srcmap.write_text("pigpen <pigpen.pfa\n", encoding="utf-8")
    pdftex = sysd / "fonts/map/pdftex/updmap/pdftex.map"
    pdftex.parent.mkdir(parents=True)
    pdftex.write_text(_PDFTEX_MAP, encoding="utf-8")
    files = {"pdftex.map": pdftex, "pigpen.pfa": pfa, "pigpen.map": srcmap}
    return wdir, texmf, files


def _pfa_rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "pfa_to_pfb")


def _pfa_cond(tmp_path: Path, err_head: str = _PFA_ERR_HEAD) -> tuple[bool, str]:
    rule = _pfa_rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


# ─────────────────────── _pfa_to_pfb_bytes 单元 ───────────────────────


def test_pfa_bytes_roundtrip() -> None:
    """真件形 pfa → 三段 PFB: ASCII 头 / hex 解码密文 / ``0``-填充 ASCII 尾。"""
    pfb = _pfa_to_pfb_bytes(_PFA_BYTES)
    assert pfb is not None
    segs = _pfb_segments(pfb)
    assert [t for t, _ in segs] == [1, 2, 1, 3]
    assert segs[0][1].endswith(b"currentfile eexec\n")
    assert segs[0][1].startswith(b"%!PS-AdobeFont")
    assert segs[1][1] == b"\xab" * 32 + b"\xcd" * 32  # hex 解码不解密
    assert segs[2][1] == b"\n" + b"0" * 512 + b"\ncleartomark\n{restore}if\n"


def test_pfa_bytes_declines_non_eexec() -> None:
    """无 ``currentfile eexec`` / 无 ``cleartomark`` → None (非转换面)。"""
    assert _pfa_to_pfb_bytes(b"%!PS-AdobeFont\n/FontName /x def\n") is None
    assert (
        _pfa_to_pfb_bytes(b"currentfile eexec\n" + b"AB" * 16 + b"\nno trailer\n")
        is None
    )


# ─────────────────────────── rule 注册 / 闸 ───────────────────────────


def test_pfatopfb_rule_registered() -> None:
    rule = _pfa_rule()
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "pfa_to_pfb"
    assert rule.raw["engines"]["tectonic"]["mode"] == "unsupported"
    assert builtins.TRANSFORM_FNS["pfa_to_pfb"] is pfa_to_pfb


def test_pfatopfb_cond_fires_on_signature(tmp_path: Path) -> None:
    """pfa-fatal 签名 err_head → 闸放行。"""
    ok, why = _pfa_cond(tmp_path)
    assert ok, why


def test_pfatopfb_cond_declines_unrelated(tmp_path: Path) -> None:
    """无关 other 类目错 → ctx_suggests 拒。"""
    ok, _why = _pfa_cond(tmp_path, "! xdvipdfmx:fatal: pdf_link_obj(): bad")
    assert not ok


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_pfatopfb_writes_usertree(tmp_path: Path) -> None:
    """三层遮蔽齐落: type1 .pfb / TEXMFVAR pdftex.map / dvips 源 .map; 宿主原件不动。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert ok, note
    pfb = texmf / "home/fonts/type1/pigpen.pfb"
    assert [t for t, _ in _pfb_segments(pfb.read_bytes())] == [1, 2, 1, 3]
    shadow = (texmf / "var/fonts/map/pdftex/updmap/pdftex.map").read_text()
    assert "<pigpen.pfb" in shadow
    assert "<pigpen.pfa" not in shadow
    assert "<rsfs10.pfb" in shadow  # 无关条目原样保留
    smap = (texmf / "home/fonts/map/dvips/pigpen/pigpen.map").read_text()
    assert "<pigpen.pfb" in smap
    assert "<pigpen.pfa" in files["pdftex.map"].read_text()  # 宿主原件不动


def test_pfatopfb_declines_no_texmfhome(tmp_path: Path) -> None:
    """texmfhome 缺席 → False (无遮蔽落点)。"""
    wdir, _texmf, files = _pfa_fixture(tmp_path)
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(None, files), None, {})
    assert not ok
    assert "texmfhome" in note


def test_pfatopfb_declines_no_pfa_refs(tmp_path: Path) -> None:
    """pdftex.map 无 .pfa 引用 → False (签名命中但无可修面)。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pdftex.map"].write_text("cmr10 CMR10 <cmr10.pfb\n", encoding="utf-8")
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no .pfa refs" in note


def test_pfatopfb_declines_unresolvable_font(tmp_path: Path) -> None:
    """map 引用了 probe 不到的 .pfa → False (不凭空产物)。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pdftex.map"].write_text("ghost <ghost.pfa\n", encoding="utf-8")
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no convertible" in note


def test_pfatopfb_declines_non_eexec_pfa(tmp_path: Path) -> None:
    """.pfa 可解但非 eexec 形 → 转换器 None → False。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pigpen.pfa"].write_bytes(b"%!PS-AdobeFont\nplain ascii font\n")
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no convertible" in note


def test_pfatopfb_in_wdir_map_patched_in_place(tmp_path: Path) -> None:
    """pdftex.map 在工程内 (cwd 首位遮蔽一切) → 就地改写, 不落 TEXMFVAR。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    wmap = wdir / "pdftex.map"
    wmap.write_text(_PDFTEX_MAP, encoding="utf-8")
    ok, note = pfa_to_pfb(_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert ok, note
    assert "<pigpen.pfb" in wmap.read_text()
    assert not (texmf / "var/fonts/map/pdftex/updmap/pdftex.map").exists()
