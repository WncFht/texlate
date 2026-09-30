"""批三 (fbucket-scout F-stub/F-font, 2026-09-17): 救援物自身缺陷两钩 +
CJK 缺字路由钉。

- astro-ph/0307062·0501187·0501259: 旧 aa.dem 单参 ``\\abstract{...}``
  (内含 ``\\keywords``) 撞上 shim 原 ``[5]`` 形 → ``\\par/\\maketitle/
  \\section`` 被吞成参数, ``\\@sect`` 组内 ``\\@@par`` 落进 expl3 hook 名
  csname → ``Missing \\endcsname`` ×100 风暴。修: ``[1]`` + ``\\aa@absorb``
  peek 续组并入 (新五段形仍全收)。
- nucl-ex/0408018: ``\\input{graphicx}`` 命中 TL ``tex/plain/graphics/``
  的 miniltx 包装 ``graphicx.tex`` → xelatex 下 ``\\zap@space`` 递归爆
  input stack。修: ``filemap.overrides`` 钉 ``null`` 断 install 通路 +
  ``shim_map`` 桥 ``\\RequirePackage{graphicx}``。
- F-font 路由钉: CJK 码位落 spec 字体 (``[lmroman*]:mapping=`` 形) →
  ``cjk_glyph`` → ``cjk_warmup`` (绑定预热通路); char_table 无 install
  动作 —— 缺字族不走装包。
"""

import re
from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import (
    _MC_TABLE,
    TRANSFORM_FNS,
    _mc_hit,
    _mc_plan,
)
from texlate.compile.fixloop.engine import LoopCtx, _wire_filemap_overrides


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO。"""
    return load_ruleset()


def _shim_params() -> dict:
    return next(r for r in _rs().rules if r.id == "legacy_pkg_shim").action["params"]


class _Eng:
    name = "xelatex"

    def __init__(self, filemap_hit: dict[str, list[str]] | None = None) -> None:
        self.filemap_hit = filemap_hit or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd, fname
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def filemap(self, fname: str) -> list[str]:
        return self.filemap_hit.get(fname, [])


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


# ------------------------------------------------------- aa.cls \abstract


_AA_STUB = (
    Path(__file__).resolve().parent.parent
    / "src/texlate/compile/fixloop/vendor/stubs/aa.cls"
)


def test_aa_shim_abstract_single_arg_with_absorb() -> None:
    """``\\abstract`` 必须 [1]+absorb —— [5] 在旧稿上吞结构 cs 炸 endcsname。
    routeclean 2026-09-20: shim_map aa.cls 槽删 → vendored stub 实件钉。"""
    body = _AA_STUB.read_text(encoding="utf-8")
    assert re.search(r"\\renewcommand\{\\abstract\}\[1\]", body)
    assert "\\aa@absorb" in body  # 续组并入 peek 机制在场
    assert "[5]" not in re.search(r"\\renewcommand\{\\abstract\}[^\n]*", body).group(0)


def test_aa_shim_stub_writes(tmp_path: Path) -> None:
    """vendored_fetch 落盘面: 替身 stub 经真动作物化 wdir + absorb 机制随件。"""
    root = tmp_path / "vendor"
    (root / "stubs").mkdir(parents=True)
    (root / "stubs" / "aa.cls").write_text(
        _AA_STUB.read_text(encoding="utf-8"), encoding="utf-8"
    )
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "aa.cls", {"dir": str(root)})
    assert ok, note
    stub = (ctx.wdir / "aa.cls").read_text()
    assert "\\aa@absorb" in stub
    assert "\\LoadClass{article}" in stub


# ------------------------------------------------------- graphicx.tex 桥


def test_graphicx_tex_override_null_and_shim() -> None:
    """install 通路被 overrides null 断开, shim_map 有桥 stub。"""
    overrides = _rs().filemap_cfg["overrides"]
    assert "graphicx.tex" in overrides
    assert overrides["graphicx.tex"] is None
    spec = _shim_params()["shim_map"]["graphicx.tex"]
    assert spec["needs"] == ["graphicx.sty"]
    assert "\\RequirePackage{graphicx}" in spec["body"]
    # \\input 装载的件不能用 @-cs (@ 非 letter)
    assert not re.search(r"\\[a-zA-Z]*@[a-zA-Z]", spec["body"])


def test_graphicx_tex_override_short_circuits(tmp_path: Path) -> None:
    """eng.filemap 遮蔽后 graphicx.tex 恒 [] —— 真包候选被钉死。"""
    eng = _Eng(filemap_hit={"graphicx.tex": ["graphics-pln"], "x.sty": ["x"]})
    _wire_filemap_overrides(eng, {"graphicx.tex": None}, _ctx(tmp_path))
    assert eng.filemap("graphicx.tex") == []
    assert eng.filemap("x.sty") == ["x"]  # 未钉的照走原查询


def test_graphicx_tex_shim_fires(tmp_path: Path) -> None:
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](
        _ctx(tmp_path), _Eng(), "graphicx.tex", _shim_params()
    )
    assert ok, note
    stub = (tmp_path / "graphicx.tex").read_text()
    assert "\\RequirePackage{graphicx}" in stub
    assert stub.rstrip().endswith("\\endinput")


# ------------------------------------------------------- psfig.tex 桥


def test_psfig_tex_shim_gin_rdim_aliases() -> None:
    r"""hep-lat/0501006 实证: epsfig ``\psfig`` 仿真把整 kv 串灌
    ``\setkeys{Gin}`` —— psfig 专有 ``rheight``/``rwidth`` (reserved box
    dims) Gin 无键 → ``Package keyval Error: rheight undefined``;
    shim body 补 Gin 别名到 ``\Gin@eheight``/``\Gin@ewidth`` (graphicx
    ``height``/``width`` 同宏, 与真身 r*→w/h 回落同语义)。``\input``
    装载 @=12 → @-cs 段 ``\catcode 64`` save/restore 裹 (geom.sty
    体同款惯例)。"""
    body = _shim_params()["shim_map"]["psfig.tex"]["body"]
    assert "\\define@key{Gin}{rheight}{\\def\\Gin@eheight{#1}}" in body
    assert "\\define@key{Gin}{rwidth}{\\def\\Gin@ewidth{#1}}" in body
    assert "\\catcode 64" in body  # @-cs 段 catcode save/restore


def test_psfig_tex_shim_fires(tmp_path: Path) -> None:
    """payload ``psfig.tex`` → 落 shim 件含 epsfig 桥 + Gin r* 别名。"""
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](
        _ctx(tmp_path), _Eng(), "psfig.tex", _shim_params()
    )
    assert ok, note
    stub = (tmp_path / "psfig.tex").read_text()
    assert "\\RequirePackage{epsfig}" in stub
    assert "\\define@key{Gin}{rheight}" in stub
    assert stub.rstrip().endswith("\\endinput")


# ------------------------------------------------------- CJK 缺字路由钉


_SPEC_FONT = "[lmroman10]:mapping=tex-text"  # 2410.00046/2410.18001 实证字体形


def test_cjk_spec_font_routes_to_warmup() -> None:
    """CJK 落 spec 字体 → cjk_glyph → cjk_warmup —— 绑定预热通路非 install。"""
    cjk = next(e for e in _MC_TABLE if e["id"] == "cjk_glyph")
    assert _mc_hit(cjk, 0x8FD9, _SPEC_FONT)  # 这 U+8FD9
    assert _mc_hit(cjk, 0x4E2D, _SPEC_FONT)  # 中 U+4E2D
    assert cjk["action"] == "cjk_warmup"


def test_cjk_tfm_and_cjkfont_not_warmup() -> None:
    """tfm 字体缺 CJK = 数学面 (inject \\Umathcode 兜底) —— warmup 不接;
    已是 CJK 字体名 → font_not 拒 (绑定已正确, 缺字另有因)。"""
    cjk = next(e for e in _MC_TABLE if e["id"] == "cjk_glyph")
    assert not _mc_hit(cjk, 0x8FD9, "cmr10")
    assert not _mc_hit(cjk, 0x8FD9, "[FandolSong-Regular.otf]")


def test_mc_plan_cjk_warm_no_install() -> None:
    """plan 层: spec 字体 CJK → warm=True; char_table 全表无 install 动作。"""
    warm, repl, unmatched = _mc_plan(
        {0x8FD9: ("这", _SPEC_FONT)},
        {e["id"]: e for e in _MC_TABLE},
    )
    assert warm
    assert not repl
    assert unmatched == 0
    for e in _MC_TABLE:
        assert "install" not in str(e.get("action") or e.get("replace") or "")
