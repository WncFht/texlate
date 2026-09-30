"""filemap 面三件 (task #98, 2026-09-16) —— overrides 全引擎接线 /

INDEX_EXTS↔OVERLAY_EXTS 解耦 / cs glue-残骸前缀拆分 fallback。

- ``_wire_engine`` 对任意引擎实例遮蔽 ``eng.filemap`` (overrides-first):
  xelatex ``install_file`` 内部 ``self.filemap`` 调用与 fixloop advisory
  同口生效; bench 现场既有 ``eng.filemap = idx.query`` 遮蔽也照包。
- ``CtanFetcher(index=注入索引)`` 同样应用 ``overrides=`` (原只在惰性建
  索引分支套入，注入共享索引时静默丢失)。
- ``.tex``/``.rtx`` 进 tlpdb 索引 (runfiles 段限定) 但不进 OVERLAY_EXTS:
  缺名可反查真包走 usertree 安装，不做 basename 平铺遮蔽工程源。
- ``cs_targeted_fix`` 表外 fallback: glue 残骸 ``\\itemFSU`` 型自动拆
  ``head rest``; ``@`` 私有 cs / split_guard 真宏名不拆。
"""

import lzma
from pathlib import Path

from _fixloopkit import MockEngine
from test_fixloop_ctan import make_tarxz

from texlate.compile.ctan import (
    INDEX_EXTS,
    OVERLAY_EXTS,
    CtanFetcher,
    TlpdbIndex,
    ctan_fetch,
    fetch_package,
)
from texlate.compile.fixloop.engine import LoopCtx, Ruleset, _wire_engine

MIRROR = "https://m.test/tlnet"


def _rs_with_overrides(overrides: dict) -> Ruleset:
    return Ruleset({"version": 1, "filemap": {"overrides": overrides}})


# ---------------------------------------------------------------- 任务 1: overrides 全引擎
def test_wire_engine_wraps_xelatex_filemap(tmp_path: Path) -> None:
    """xelatex 引擎：filemap 遮蔽后 overrides 先答，未中委派原查询。"""
    eng = MockEngine([])
    eng.filemap_tbl["real.sty"] = ["realpkg"]
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    _wire_engine(
        eng,
        _rs_with_overrides({"binhex.tex": "kastrup", "noise.tex": None}),
        tmp_path,
        ctx,
    )
    assert eng.filemap("binhex.tex") == ["kastrup"]
    assert eng.filemap("noise.tex") == []  # 显式 null → 短路，不查原表
    assert eng.filemap("real.sty") == ["realpkg"]  # 未中 → 委派原 filemap
    assert eng.filemap("absent.sty") == []
    assert any("filemap overrides" in e for e in ctx.events)


def test_wire_engine_composes_over_idx_query_shadow(tmp_path: Path) -> None:
    """bench 现场 ``eng.filemap = idx.query`` 的既有遮蔽也被包进包装。"""
    idx = TlpdbIndex({"foo.sty": ["foopkg"]})
    eng = MockEngine([])
    eng.filemap = idx.query  # bench 既有用法
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    _wire_engine(eng, _rs_with_overrides({"epsf.tex": "epsf"}), tmp_path, ctx)
    assert eng.filemap("epsf.tex") == ["epsf"]  # overrides 先答
    assert eng.filemap("foo.sty") == ["foopkg"]  # 委派 idx.query


def test_wire_engine_overrides_idempotent(tmp_path: Path) -> None:
    """重复 _wire_engine 不叠包 (幂等标记)。"""
    eng = MockEngine([])
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    rs = _rs_with_overrides({"x.tex": "xpkg"})
    _wire_engine(eng, rs, tmp_path, ctx)
    wrapped = eng.filemap
    _wire_engine(eng, rs, tmp_path, ctx)
    assert eng.filemap is wrapped


def test_ctan_fetcher_applies_overrides_to_injected_index(tmp_path: Path) -> None:
    """注入共享索引时 overrides 不再静默丢失 (fixloop_bench 现场)。"""
    idx = TlpdbIndex({"foo.sty": ["foopkg"]})
    cf = CtanFetcher(
        tmp_path, index=idx, overrides={"mine.sty": "minepkg", "n.tex": None}
    )
    assert cf.index.query("mine.sty") == ["minepkg"]
    assert cf.index.query("n.tex") == []
    assert cf.index.query("foo.sty") == ["foopkg"]


# ---------------------------------------------------------------- 任务 2: 索引/平铺解耦
def test_tex_indexed_runfiles_only(tmp_path: Path) -> None:
    """.tex/.rtx 只从 runfiles 段收录; docfiles/srcfiles 同名不收。"""
    tlpdb = tmp_path / "texlive.tlpdb"
    tlpdb.write_text(
        """\
name kas
runfiles
  texmf-dist/tex/generic/kastrup/binhex.tex
  texmf-dist/tex/latex/revtex/aps.rtx
docfiles
  texmf-dist/doc/kas/example.tex
srcfiles
  texmf-dist/src/kas/source.tex
name doc
runfiles
  texmf-dist/tex/latex/doc/doc.sty
""",
        encoding="utf-8",
    )
    idx = TlpdbIndex.from_tlpdb(tlpdb)
    assert idx.table["binhex.tex"] == ["kas"]
    assert idx.table["aps.rtx"] == ["kas"]
    assert "example.tex" not in idx.table  # docfiles 段不收
    assert "source.tex" not in idx.table  # srcfiles 段不收


def test_tex_not_in_overlay(tmp_path: Path) -> None:
    """.tex 可索引不可平铺：fetch_package flat 不落 .tex/.pfb 成员。"""
    for ext in (".tex", ".rtx"):
        assert ext in INDEX_EXTS
        assert ext not in OVERLAY_EXTS
    body = make_tarxz(
        {
            "texmf-dist/tex/generic/kas/binhex.tex": b"tex",
            "texmf-dist/tex/latex/kas/kas.sty": b"sty",
        }
    )
    landed = fetch_package("kas", tmp_path, mirror=MIRROR, fetcher=lambda _u: body)
    assert landed == ["kas.sty"]
    assert not (tmp_path / "binhex.tex").exists()


def test_ctan_fetch_tex_advisory(tmp_path: Path) -> None:
    """tectonic 侧缺 .tex: 索引可反查但平铺拒收 → 明确 advisory。"""
    idx = TlpdbIndex({"binhex.tex": ["kastrup"]})
    res = ctan_fetch("binhex.tex", tmp_path, idx, mirror=MIRROR)
    assert not res.ok
    assert "只索引不平铺" in res.advisory
    # .pfb 旧口径不变 (物理字体域)
    res2 = ctan_fetch("x.pfb", tmp_path, idx, mirror=MIRROR)
    assert "不在 TeX 输入层" in res2.advisory


def test_ensure_rebuilds_tex_index(tmp_path: Path) -> None:
    """冷缓存 ensure: tlpdb.xz 拉取 → .tex runfiles 成员进索引。"""
    tlpdb_xz = lzma.compress(
        b"name kas\nrunfiles\n  texmf-dist/tex/generic/kas/binhex.tex\n"
    )
    idx = TlpdbIndex.ensure(tmp_path, mirror=MIRROR, fetcher=lambda _u: tlpdb_xz)
    assert idx.query("binhex.tex") == ["kas"]
