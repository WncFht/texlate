r"""pfa 车道 (2026-09-19): ``pfa_to_pfb`` ASCII Type1 → usertree .pfb 规则钉。

(原居 ``test_fixloop_pdfsanitize.py`` 第二泳道——同为 xdvipdfmx stdout_tail
fatal 族但修面无涉, 拆出独立成文。)

1907.03923 (stagerun-loop3) 实证: ``\usepackage{pigpen}`` 引用在用的
dist 侧 ASCII Type1 字体 (\pigpenfont 邻接符, xymatrix 内 ~6 处) →
``pigpen.map`` 行 ``pigpen <pigpen.pfa`` 折进 pdftex.map → xdvipdfmx
按扩展名硬拒 .pfa (fatal 落 stdout_tail, ``other`` 类目同族派发)。
修复 = 纯 python t1binary 等价物 (eexec 密文 hex 解码原样进 PFB 段二,
不解密) + 三层 usertree 遮蔽: type1 产物 / TEXMFVAR 位 pdftex.map /
源 <pkg>.map dvips 面 (updmap 再生保险)。
"""

from pathlib import Path

from _fixloopkit import EngStub, mk_ctx, rule

from texlate.compile.fixloop import actions, builtins
from texlate.compile.fixloop.builtins import pfa_to_pfb
from texlate.compile.fixloop.builtins.assetfix import _pfa_to_pfb_bytes


class _PfaEng:
    """pfa_to_pfb 路径引擎替身：texmfhome usertree + 具名 probe 表。"""

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
    """假系统树：wdir/sysroot/usertree 三兄弟 → (wdir, texmfhome, probe 表)。

    sysroot 必须在 wdir 之外 —— 遮蔽臂靠 ``map 在工程内？`` 二分 (系统树件
    落 TEXMFVAR 副本，工程内件就地改写)。
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


def _pfa_cond(tmp_path: Path, err_head: str = _PFA_ERR_HEAD) -> tuple[bool, str]:
    """``actions._cond_ok`` 直驱——SLF001 豁免一处收口。"""
    r = rule("pfa_to_pfb")
    return actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path, err_head=err_head), EngStub(), None
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
    r = rule("pfa_to_pfb")
    assert r.action["kind"] == "builtin_transform"
    assert r.action["function"] == "pfa_to_pfb"
    assert r.raw["engines"]["tectonic"]["mode"] == "unsupported"
    assert builtins.TRANSFORM_FNS["pfa_to_pfb"] is pfa_to_pfb


def test_pfatopfb_cond_fires_on_signature(tmp_path: Path) -> None:
    """pfa-fatal 标记 err_head → 闸放行。"""
    ok, why = _pfa_cond(tmp_path)
    assert ok, why


def test_pfatopfb_cond_declines_unrelated(tmp_path: Path) -> None:
    """无关 other 类目错 → ctx_suggests 拒。"""
    ok, _why = _pfa_cond(tmp_path, "! xdvipdfmx:fatal: pdf_link_obj(): bad")
    assert not ok


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_pfatopfb_writes_usertree(tmp_path: Path) -> None:
    """三层遮蔽齐落：type1 .pfb / TEXMFVAR pdftex.map / dvips 源 .map; 宿主原件不动。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(texmf, files), None, {})
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
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(None, files), None, {})
    assert not ok
    assert "texmfhome" in note


def test_pfatopfb_declines_no_pfa_refs(tmp_path: Path) -> None:
    """pdftex.map 无 .pfa 引用 → False (标记命中但无可修面)。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pdftex.map"].write_text("cmr10 CMR10 <cmr10.pfb\n", encoding="utf-8")
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no .pfa refs" in note


def test_pfatopfb_declines_unresolvable_font(tmp_path: Path) -> None:
    """map 引用了 probe 不到的 .pfa → False (不凭空产物)。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pdftex.map"].write_text("ghost <ghost.pfa\n", encoding="utf-8")
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no convertible" in note


def test_pfatopfb_declines_non_eexec_pfa(tmp_path: Path) -> None:
    """.pfa 可解但非 eexec 形 → 转换器 None → False。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    files["pigpen.pfa"].write_bytes(b"%!PS-AdobeFont\nplain ascii font\n")
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert not ok
    assert "no convertible" in note


def test_pfatopfb_in_wdir_map_patched_in_place(tmp_path: Path) -> None:
    """pdftex.map 在工程内 (cwd 首位遮蔽一切) → 就地改写，不落 TEXMFVAR。"""
    wdir, texmf, files = _pfa_fixture(tmp_path)
    wmap = wdir / "pdftex.map"
    wmap.write_text(_PDFTEX_MAP, encoding="utf-8")
    ok, note = pfa_to_pfb(mk_ctx(wdir), _PfaEng(texmf, files), None, {})
    assert ok, note
    assert "<pigpen.pfb" in wmap.read_text()
    assert not (texmf / "var/fonts/map/pdftex/updmap/pdftex.map").exists()
