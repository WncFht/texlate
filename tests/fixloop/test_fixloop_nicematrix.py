"""nicematrix 版本自检炸修复链单测 (pkg_version_skew 分类 + vendored 钉版替换)。

实证背景 (e2ereal 2308.12712): tlmgr --usermode 装进的 nicematrix v7.11c
要求 ``\\IfFormatAtLeastTF{2026-06-01}``, runtime LaTeX2e 2025-11-01 →
``nicematrix.sty:39: Critical Package nicematrix Error: Your LaTeX release
is too old`` → 包拒载，下游 NiceTabular/NiceMatrix undefined 级联。
修复面：vendor/files/nicematrix.sty 钉 v7.11a (floor format 2025-06-01,
array 2025/09/25 —— 本机 toolchain 恰好全过), 新 taxonomy 标记抓 file-line
basename → vendored_fetch 平铺 wdir 遮蔽 texmfhome 过新件。
"""

from pathlib import Path

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import parse_text

_VENDOR_STY = (
    Path(__file__).resolve().parents[2]
    / "src/texlate/compile/fixloop/vendor/files/nicematrix.sty"
)

# 2308.12712 main.log 实证首错行 (file-line-error 形态，expl3 msg_critical)
_CRIT_LINE = (
    "/home/texmf/home/tex/latex/nicematrix/nicematrix.sty:39: "
    "Critical Package nicematrix Error: Your LaTeX release is too old."
)
_CRIT_CTX = """(nicematrix)                         You need at least the version of
(nicematrix)                         2026-06-01.
(nicematrix)                         If you use Overleaf, you need at least
(nicematrix)                         "TeXLive 2026".
(nicematrix)                         The package 'nicematrix' won't be
(nicematrix)                         loaded.

l.39 ...ical:nn { nicematrix } { latex-too-old } }"""


def _rs() -> Ruleset:
    return load_ruleset()


def _classify(head_text: str) -> tuple[str | None, str | None]:
    rep = parse_text(head_text + "\n")
    return _rs().taxonomy.classify(rep)


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_real_critical_line() -> None:
    """实证标记：file-line Critical Error + too old → pkg_version_skew + basename。"""
    cat, pay = _classify(_CRIT_LINE + "\n" + _CRIT_CTX)
    assert cat == "pkg_version_skew"
    assert pay == "nicematrix.sty"


def test_taxonomy_wrapped_too_old_in_ctx() -> None:
    """``too old`` 被折行推离错误行 (长路径前缀) → ctx8 内 {0,600} 窗仍命中。"""
    head = (
        "./pkg/sty/foo.sty:12: Critical Package foo Error: Your LaTeX release\n"
        "(foo)  is way too old.\n"
        "l.12 \\msg_critical:nn { foo } { latex-too-old }"
    )
    cat, pay = _classify(head)
    assert cat == "pkg_version_skew"
    assert pay == "foo.sty"


def test_taxonomy_class_error_variant() -> None:
    """Class 级 + 非 Critical 级 msg_error 同标记; payload 仍是 basename。"""
    head = (
        "bar.cls:7: Package bar Error: This class needs a kernel that is not too old\n"
        "l.7 \\@@end"
    )
    cat, pay = _classify(head)
    assert cat == "pkg_version_skew"
    assert pay == "bar.cls"


def test_taxonomy_other_critical_not_matched() -> None:
    """非版本闸的 critical 错不落本类 (版本语义限定词缺席) → 归 other。"""
    head = (
        "./nicematrix.sty:39: Critical Package nicematrix Error: You must load 'tikz' first.\n"
        "l.39 \\msg_critical:nn { nicematrix } { tikz-required }"
    )
    cat, pay = _classify(head)
    assert cat == "other"
    assert pay is None


# ---------------------------------------------------------------- 钉版面
def test_vendored_nicematrix_pinned_floor() -> None:
    """vendor 钉版 v7.11a: 版本戳 + 双侧 floor 均不破本机 toolchain。"""
    text = _VENDOR_STY.read_text(encoding="utf-8")
    assert "\\def\\myfileversion{7.11a}" in text
    assert "\\def\\myfiledate{2026/07/22}" in text
    # floor format 2025-06-01 ≤ runtime LaTeX2e 2025-11-01 (v7.11b+ 要 2026-06-01 会炸)
    assert "\\IfFormatAtLeastTF { 2025-06-01 }" in text
    assert "2026-06-01" not in text.split("\\IfFormatAtLeastTF { 2025-06-01 }")[0]
    # array floor 2025/09/25 == 本机 array 版 (恰界可过)
    assert "\\IfPackageAtLeastF { array }\n  { 2025/09/25 }" in text


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """pkg_version_skew_vendored 挂 loop 相 → vendored_fetch builtin。"""
    rules = {r.id: r for r in _rs().phase("loop")}
    r = rules["pkg_version_skew_vendored"]
    assert r.when.get("category") == "pkg_version_skew"
    assert r.when.get("payload_required") is True
    assert r.action["function"] == "vendored_fetch"


def test_vendored_fetch_substitutes_default_root(tmp_path: Path) -> None:
    """缺省 vendor 根 (params={}) 落 wdir 钉版件 → 指纹行头 + v7.11a 版本戳。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "nicematrix.sty", {})
    assert ok, note
    dropped = ctx.wdir / "nicematrix.sty"
    text = dropped.read_text(encoding="utf-8")
    assert text.startswith("% texlate-fixloop-injected:")
    assert "\\def\\myfileversion{7.11a}" in text


def test_vendored_fetch_foreign_not_overwritten(tmp_path: Path) -> None:
    """稿自带过新 nicematrix 在场 → 指纹闸拒覆 (foreign) → 规则 decline。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    (ctx.wdir / "nicematrix.sty").write_text(
        "\\def\\myfileversion{7.11c}\n", encoding="utf-8"
    )
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "nicematrix.sty", {})
    assert not ok
    assert "foreign" in note
    assert "\\def\\myfileversion{7.11c}" in (ctx.wdir / "nicematrix.sty").read_text(
        encoding="utf-8"
    )
