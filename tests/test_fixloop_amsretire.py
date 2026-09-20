r"""amsmath \\@@leqno ship-retire 规则单测 (assetlane #165, failmine3 3 格)。

实证背景 (0806.0246/0806.4130/1306.0294, stagerun-loop3): e-print 捆绑
pre-2019 amsmath*.sty v2.13 (2000/07/18) —— ``\@saveprimitive\leqno\
\@@leqno`` (:2573) 要求 ``\leqno`` 仍是 primitive; 2019-10 kernel 起
``\leqno``/``\eqno`` 改 ``\protected`` 宏 → ``LaTeX Error: Unable to
properly define \@@leqno; primitive \leqno no longer primitive`` (other)。
修复面: 指纹件 mv .fixloop-iso (本名系统/bundle 同名递补; 改名件
amsmath2.sty 写同名 delegate stub 接 ``\RequirePackage{amsmath}``) +
ams* 伴船 ld<sd 确证同道退役 (2003/2025 混栈是现代件新未定义面;
probe3 三臂实证 cohort 退役最优 —— 整片快照退役会混 pst 半栈退步)。
"""

from collections.abc import Callable
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import parse_text

_RULE_ID = "amsmath_saveprimitive_retire"

# 0806.4130 实证首错 (file-line-error 形): 稿自带 amsmath.sty:2573
_ERR_LINE = (
    "/work/0806.4130/splice/amsmath.sty:2573: LaTeX Error: "
    "Unable to properly define \\@@leqno; primitive \\leqno "
    "no longer primitive."
)
_ERR_CTX = """<to be read again>
                   \\leqno
l.2573 \\@saveprimitive\\leqno\\@@leqno"""

# 0806.0246 改名件变体 (amsmath2.sty 同名签名)
_ERR_RENAMED = (
    "/work/0806.0246/splice/amsmath2.sty:2573: LaTeX Error: "
    "Unable to properly define \\@@leqno; primitive \\leqno "
    "no longer primitive.\n" + _ERR_CTX
)

# pre-2019 amsmath v2.13 指纹体 (\\@saveprimitive 对 leqno/eqno 调用面)
_STALE_AMSMATH = (
    "\\ProvidesPackage{amsmath}[2000/07/18 v2.13 AMS math features]\n"
    "\\@saveprimitive\\leqno\\@@leqno\n"
    "\\@saveprimitive\\eqno\\@@eqno\n"
)
_STALE_AMSMATH2 = _STALE_AMSMATH.replace("amsmath}", "amsmath2}")
# 现代 amsmath v2.17z: \\let 直绑无 \\@saveprimitive 调用 → 非指纹
_NEW_AMSMATH = (
    "\\ProvidesPackage{amsmath}[2025/07/09 v2.17z AMS math features]\n"
    "\\let\\@@eqno\\eqno\n\\let\\@@leqno\\leqno\n"
)
_STALE_AMSGEN = "\\ProvidesPackage{amsgen}[2000/07/18 v2.0 AMS]\n"
_NEW_AMSGEN = "\\ProvidesPackage{amsgen}[2024/11/30 v2.1 AMS]\n"


class _ShadowEng:
    """probe_file → ``texmf`` 目录直查 (pstshadow 测试同款微缩)。"""

    name = "xelatex"

    def __init__(self, texmf: Path) -> None:
        self.texmf = texmf

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == _RULE_ID)


def _ctx(wdir: Path) -> LoopCtx:
    return LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex")


def _fn() -> Callable[..., tuple[bool, str]]:
    return TRANSFORM_FNS["amsmath_family_retire"]


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_signature_is_other() -> None:
    """实证签名 file-line LaTeX Error → other (taxonomy 无专类)。"""
    rep = parse_text(_ERR_LINE + "\n" + _ERR_CTX)
    cat, _ = _rs().taxonomy.classify(rep)
    assert cat == "other"


def test_taxonomy_renamed_copy_same() -> None:
    """改名件 amsmath2.sty 同款签名同归 other。"""
    rep = parse_text(_ERR_RENAMED)
    cat, _ = _rs().taxonomy.classify(rep)
    assert cat == "other"


# ---------------------------------------------------------------- 规则接线
def test_rule_wired() -> None:
    """挂 loop 相 order 11.96 → builtin_transform amsmath_family_retire。"""
    rule = _rule()
    assert rule.order == 11.96  # noqa: PLR2004 - schema 断言值
    assert rule.when["category"] == "other"
    assert "no longer primitive" in rule.condition["ctx_suggests"]
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "amsmath_family_retire"


def test_rule_order_in_retire_family() -> None:
    """order 自洽: abstract_edef_capture_neutralize < 本规则 < legacy_pkg_shim。"""
    orders = {r.id: r.order for r in _rs().phase("loop")}
    assert orders["abstract_edef_capture_neutralize"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_unrelated_other(tmp_path: Path) -> None:
    """err_head 无签名 (别的 other 错) → ctx_suggests 闸拒。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = "./main.tex:10: LaTeX Error: Something else.\nl.10 x\n"
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_pass_signature(tmp_path: Path) -> None:
    """err_head 带 no longer primitive → 闸过。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = _ERR_LINE + "\n" + _ERR_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


# ---------------------------------------------------------------- pass 1 指纹退役
def _proj_texmf(tmp_path: Path) -> tuple[Path, Path]:
    """wdir=proj/ 与 texmf=兄弟目录 (probe 命中 wdir 内会被判工程自件跳过)。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    return proj, texmf


def test_stale_amsmath_renamed_no_delegate(tmp_path: Path) -> None:
    """本名 amsmath.sty 退役 → 无 delegate (自指 \\RequirePackage 即空包)。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (wdir / "amsmath.sty").write_text(_STALE_AMSMATH, encoding="utf-8")
    ok, note = _fn()(_ctx(wdir), _ShadowEng(texmf), None, {})
    assert ok, note
    assert (wdir / "amsmath.sty.fixloop-iso").is_file()
    assert not (wdir / "amsmath.sty").exists()  # 不写 delegate


def test_renamed_copy_gets_delegate(tmp_path: Path) -> None:
    """amsmath2.sty (改名 v2.13) → 退役 + 同名 delegate 接 amsmath。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (wdir / "amsmath2.sty").write_text(_STALE_AMSMATH2, encoding="utf-8")
    ok, note = _fn()(_ctx(wdir), _ShadowEng(texmf), None, {})
    assert ok, note
    assert (wdir / "amsmath2.sty.fixloop-iso").is_file()
    body = (wdir / "amsmath2.sty").read_text(encoding="utf-8")
    assert body.startswith("% texlate-fixloop-injected:")
    assert "\\ProvidesPackage{amsmath2}" in body
    assert "\\RequirePackage{amsmath}" in body
    assert "\\DeclareOption*" in body
    # iopart 类 equation* 预占清位 (\\csname 形, 裸 \\let\\X* 会把 RHS 当 *)
    assert "\\csname equation*\\endcsname" in body
    assert "\\csname endequation*\\endcsname" in body


def test_modern_amsmath_untouched(tmp_path: Path) -> None:
    """现代 amsmath (\\let 直绑) 无指纹 → 不动。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (wdir / "amsmath.sty").write_text(_NEW_AMSMATH, encoding="utf-8")
    ok, _ = _fn()(_ctx(wdir), _ShadowEng(texmf), None, {})
    assert not ok
    assert (wdir / "amsmath.sty").is_file()


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二轮直驱: delegate 无指纹 + 伴船已退役 → False 幂等。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (wdir / "amsmath2.sty").write_text(_STALE_AMSMATH2, encoding="utf-8")
    ctx = _ctx(wdir)
    eng = _ShadowEng(texmf)
    ok1, _ = _fn()(ctx, eng, None, {})
    assert ok1
    ok2, _ = _fn()(ctx, eng, None, {})
    assert not ok2


# ---------------------------------------------------------------- pass 2 伴船退役
def test_ams_cohort_retired_ld_lt_sd(tmp_path: Path) -> None:
    """amsgen.sty 伴船: 稿自带 2000 < 系统 2024 → 同道退役。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (texmf / "amsgen.sty").write_text(_NEW_AMSGEN, encoding="utf-8")
    (wdir / "amsmath.sty").write_text(_STALE_AMSMATH, encoding="utf-8")
    (wdir / "amsgen.sty").write_text(_STALE_AMSGEN, encoding="utf-8")
    ok, note = _fn()(_ctx(wdir), _ShadowEng(texmf), None, {})
    assert ok, note
    assert (wdir / "amsgen.sty.fixloop-iso").is_file()
    assert "cohort" in note


def test_non_ams_cohort_untouched(tmp_path: Path) -> None:
    """非 ams* 旧件 (graphicx 等) 不动 —— 族外归 vendored_sty_shadow 等规则。"""
    wdir, texmf = _proj_texmf(tmp_path)
    (texmf / "graphicx.sty").write_text(
        "\\ProvidesPackage{graphicx}[2024/01/01 new]\n", encoding="utf-8"
    )
    (wdir / "amsmath.sty").write_text(_STALE_AMSMATH, encoding="utf-8")
    (wdir / "graphicx.sty").write_text(
        "\\ProvidesPackage{graphicx}[2000/01/01 old]\n", encoding="utf-8"
    )
    ok, _ = _fn()(_ctx(wdir), _ShadowEng(texmf), None, {})
    assert ok
    assert (wdir / "graphicx.sty").is_file()  # 族外不碰
