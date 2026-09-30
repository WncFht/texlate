r"""lamsarrow lamsN TFM vendored-drop 规则单测 (asset 车道 #165, failmine3 3 格)。

实证背景 (0806.3683/1511.06948/1706.00345, stagerun-loop3):
pb-diagram/lamsarrow.sty:89-93 ``\font\lamsfont@i=lams1``…``@v=lams5``
—— LamS 箭头字体 texlive 全不收录 (CTAN pb-diagram 只装 .sty 不装字
体); 设计尺寸加载无 "at Npt"、消息无字面 .tfm → 旧 taxrow 两模式
全不中落 other (修复后 taxonomy missing_tfm 臂扩展收此签, 今
classify→(missing_tfm, lams1); 规则 when.any 双收 {other, missing_tfm}
两态皆派), install_tfm(20) tlmgr 无件。修复面 = vendor
lams{1..5}.{tfm,mf} 字节平铺 wdir: .tfm 让 ``\font`` 载入过, .mf 供
mktexpk shipout 期生 Type 3 字形 (probe2 端到端实证出真箭头 PDF;
tfm-only 撞 xdvipdfmx "Cannot proceed without .vf" 致命)。
"""

from collections.abc import Callable
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import parse_text

_RULE_ID = "lamsarrow_lams_fonts_drop"
_VENDOR_FILES = (
    Path(__file__).resolve().parents[2] / "src/texlate/compile/fixloop/vendor/files"
)
_LAMS = [f"lams{i}.{ext}" for i in range(1, 6) for ext in ("tfm", "mf")]

# 0806.3683 实证首错 (file-line-error 形，系统件站点)
_ERR_LINE = (
    "/usr/share/texmf-dist/tex/latex/pb-diagram/lamsarrow.sty:89: "
    "Font \\lamsfont@i=lams1 not loadable: Metric (TFM) file or "
    "installed font not found."
)
_ERR_CTX = """<to be read again>
                   \\font
l.89 \\font
          \\lamsfont@ii=lams2"""


def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == _RULE_ID)


def _ctx(wdir: Path) -> LoopCtx:
    return LoopCtx(wdir=wdir, engine_name="xelatex", main_rel="main.tex")


def _fn() -> Callable[..., tuple[bool, str]]:
    return TRANSFORM_FNS["vendored_fetch_multi"]


def _params() -> dict:
    return {"files": list(_LAMS)}


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_signature_missing_tfm() -> None:
    """设计尺寸 font 加载错：taxonomy 臂后扩——`Font \\X=lamsN not loadable`
    今归 missing_tfm (payload=lams1), 规则 when.any 双收 {other, missing_tfm}。"""
    rep = parse_text(_ERR_LINE + "\n" + _ERR_CTX)
    cat, _ = _rs().taxonomy.classify(rep)
    assert cat == "missing_tfm"


# ---------------------------------------------------------------- vendor 资产
def test_vendor_files_all_present() -> None:
    """vendor/files/ 十件全在仓 (5 tfm + 5 mf)。"""
    for name in _LAMS:
        assert (_VENDOR_FILES / name).is_file(), name


def test_vendor_tfm_is_binary_verbatim() -> None:
    """tfm 是二进制件 —— 非空且首两字节为 TFM 头 (lf 长度字段)。"""
    blob = (_VENDOR_FILES / "lams1.tfm").read_bytes()
    assert len(blob) > 12  # noqa: PLR2004 - TFM 头 12 半字
    assert int.from_bytes(blob[:2], "big") > 0  # lf


# ---------------------------------------------------------------- 规则接线
def test_rule_wired() -> None:
    """挂 loop 相 order 11.97 → builtin_transform vendored_fetch_multi。"""
    rule = _rule()
    assert rule.order == 11.97  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rule.when["any"]}
    assert {"other", "missing_tfm"} <= cats
    assert "lamsarrow" in rule.condition["ctx_suggests"]
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "vendored_fetch_multi"
    files = rule.action["params"]["files"]
    assert sorted(files) == sorted(_LAMS)


def test_rule_order_after_retire_family() -> None:
    """order 自洽：amsmath_saveprimitive_retire < 本规则 < legacy_pkg_shim。"""
    orders = {r.id: r.order for r in _rs().phase("loop")}
    assert orders["amsmath_saveprimitive_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_pass_signature(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.err_head = _ERR_LINE + "\n" + _ERR_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_skip_unrelated_other(tmp_path: Path) -> None:
    """别的 other 错 (非 lams) → 闸拒。"""
    ctx = _ctx(tmp_path)
    ctx.err_head = "./main.tex:5: LaTeX Error: Unknown option.\nl.5 x\n"
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


# ---------------------------------------------------------------- 动作直驱
def test_drop_all_ten_byte_identical(tmp_path: Path) -> None:
    """十件全落 wdir, 与 vendor 源字节一致 (tfm 二进制不毁)。"""
    ok, note = _fn()(_ctx(tmp_path), None, None, _params())
    assert ok, note
    for name in _LAMS:
        dst = tmp_path / name
        assert dst.is_file(), name
        assert dst.read_bytes() == (_VENDOR_FILES / name).read_bytes()


def test_drop_skips_existing(tmp_path: Path) -> None:
    """在场件跳过不覆 (稿自带/前轮已投) —— 幂等。"""
    (tmp_path / "lams1.tfm").write_bytes(b"foreign-tfm")
    ok, note = _fn()(_ctx(tmp_path), None, None, _params())
    assert ok, note
    assert (tmp_path / "lams1.tfm").read_bytes() == b"foreign-tfm"
    assert "present" in note
    assert (tmp_path / "lams2.tfm").is_file()


def test_drop_idempotent_second_call(tmp_path: Path) -> None:
    """二轮全 present → False (无新落地)。"""
    ctx = _ctx(tmp_path)
    ok1, _ = _fn()(ctx, None, None, _params())
    assert ok1
    ok2, _ = _fn()(ctx, None, None, _params())
    assert not ok2


def test_drop_missing_vendor_source(tmp_path: Path) -> None:
    """vendor 查无件 → skip 记 note; 全落空 → False。"""
    ok, note = _fn()(_ctx(tmp_path), None, None, {"files": ["nosuch.tfm"]})
    assert not ok
    assert "not vendored" in note
    ok2, note2 = _fn()(
        _ctx(tmp_path), None, None, {"files": ["nosuch.tfm", "lams1.tfm"]}
    )
    assert ok2, note2
    assert (tmp_path / "lams1.tfm").is_file()
