"""F1/F2 工单 (2026-09-16 批量强化 §9) —— 退役包 shim 扩表 + cs_table 合并残骸修复。

n100-postcutover 逐签名归因产物:
- F1: shim_map 新增 ~38 条 (elsart 家族→elsarticle, sig-alternate→acmart,
  aastex6x→emulateapj, prl/apl→revtex4-2, siamltex/osa/JHEP 家族→article+polyfill
  等), 实证见 bench/results/fixloop-tickets-F1F2-2026-09-16.md。
- F2: cs_targeted_fix cs_table 新增 24 条 splice/join 合并残骸 (cs+后 token
  粘连, 如 \\itemFSU ← \\item + 首词 FSU), 全部 cs_map 拆回原形。
单测打 transform 层: stub 落盘 / needs→install 调用 / cs_map 改写及词边界。
真编译冒烟: tmp/shimtest/ (xelatex 36/36 PASS, 见证据文件)。
"""

import re
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

RS = load_ruleset()
SHIM_PARAMS = next(r for r in RS.rules if r.id == "legacy_pkg_shim").action["params"]
CS_PARAMS = next(r for r in RS.rules if r.id == "cs_targeted_fix").action["params"]
SHIM_MAP = SHIM_PARAMS["shim_map"]
CS_TABLE = CS_PARAMS["cs_table"]
_SHIM_MAP_MIN = 38  # 2026-09-16 扩表后规模哨兵 (原 3 条 + 新增 ~38)


class _Eng:
    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr"})

    def __init__(
        self,
        probe_map: dict[str, str] | None = None,
        installable: tuple[str, ...] = (),
    ) -> None:
        self.probe_map = probe_map or {}
        self.installable = set(installable)
        self.install_calls: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        return self.probe_map.get(fname)

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        return fname in self.installable

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.main_rel = "main.tex"
    return ctx


# ---------------------------------------------------------------- F1: shim_map


def test_shim_map_every_entry_fires(tmp_path: Path) -> None:
    """shim_map 全表 (含旧条目): transform 落 stub + needs 走 install_file。"""
    assert len(SHIM_MAP) >= _SHIM_MAP_MIN
    for payload, spec in SHIM_MAP.items():
        ctx, eng = _ctx(tmp_path), _Eng()
        ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, payload, SHIM_PARAMS)
        assert ok, (payload, note)
        stub = (tmp_path / payload).read_text()
        assert stub.rstrip().endswith("\\endinput"), payload
        # \Provides{Class,Package} 版本串必须 YYYY/MM/DD 日期开头
        # (\@ifl@t@r 解析 ver@*.cls, 裸文字崩 \ifnum —— 1806.06690 实证)
        if "\\Provides" in stub:
            m = re.search(
                r"\\Provides(?:Class|Package)\{[^}]*\}\[(\d{4}/\d{2}/\d{2})", stub
            )
            assert m, f"{payload}: \\ProvidesXxx 缺日期前缀"
        for dep in spec.get("needs") or []:
            assert dep in eng.install_calls, f"{payload}: need {dep} 未走 install_file"
        (tmp_path / payload).unlink()


def test_shim_map_loads_entries_are_cls_and_delegate(tmp_path: Path) -> None:
    """loads 模板只对 .cls 有效 (引擎模板发 \\LoadClassWithOptions) ——
    声明不变量: 所有 loads 条目必须是 .cls payload, 且 stub 委托到目标类。"""
    for payload, spec in SHIM_MAP.items():
        if "loads" not in spec:
            continue
        assert payload.endswith(".cls"), f"{payload}: loads 模板仅适用 .cls"
        ctx, eng = _ctx(tmp_path), _Eng()
        ok, _ = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, payload, SHIM_PARAMS)
        assert ok
        stub = (tmp_path / payload).read_text()
        target = spec["loads"]
        assert f"\\LoadClassWithOptions{{{target}}}" in stub
        assert f"\\ProvidesClass{{{payload.removesuffix('.cls')}}}" in stub
        (tmp_path / payload).unlink()


@pytest.mark.parametrize(
    "payload",
    [
        "elsart.cls",
        "elsart1p.cls",
        "elsart3p.cls",
        "elsart5p.cls",
        "elsevier.cls",
        "sig-alternate.cls",
        "sig-alternate-05-2015.cls",
        "naturemag.cls",
    ],
)
def test_shim_map_evolved_class_targets(tmp_path: Path, payload: str) -> None:
    """有确证继任类的退役 cls → loads 委托正确目标。"""
    spec = SHIM_MAP[payload]
    assert spec["loads"] in {"elsarticle", "acmart", "nature"}
    ctx, eng = _ctx(tmp_path), _Eng()
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, payload, SHIM_PARAMS)
    assert ok, note


@pytest.mark.parametrize(
    ("payload", "needs"),
    [
        ("aa.cls", ["natbib.sty"]),
        ("aastex61.cls", ["emulateapj.cls", "epsf.sty"]),
        ("aastex63.cls", ["emulateapj.cls", "epsf.sty"]),
        ("AASTeX62.cls", ["emulateapj.cls", "epsf.sty"]),
        ("prl.cls", ["revtex4-2.cls"]),
        ("apl.cls", ["revtex4-2.cls"]),
        ("revtex4.cls", ["revtex4-2.cls"]),
        ("aipproc.cls", ["keyval.sty"]),
        ("iopart10.clo", ["size10.clo"]),
        ("iopart12.clo", ["size12.clo"]),
        ("iopams.sty", ["amsbsy.sty", "amssymb.sty"]),
        ("scrpage.sty", ["scrlayer-scrpage.sty"]),
        ("scrpage2.sty", ["scrlayer-scrpage.sty"]),
        ("doublespace.sty", ["setspace.sty"]),
    ],
)
def test_shim_map_needs_drive_install(
    tmp_path: Path, payload: str, needs: list[str]
) -> None:
    """needs 依赖逐一走 eng.install_file; 装不上记 note 不炸 (下轮归因)。"""
    ctx, eng = _ctx(tmp_path), _Eng()
    ok, _ = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, payload, SHIM_PARAMS)
    assert ok
    assert eng.install_calls == needs
    # 全部装不上 → note 报缺
    ctx2, eng2 = _ctx(tmp_path), _Eng()
    (tmp_path / payload).unlink()
    ok2, note2 = TRANSFORM_FNS["legacy_pkg_shim"](ctx2, eng2, payload, SHIM_PARAMS)
    assert ok2
    assert "deps still missing" in note2


def test_shim_map_body_invariants() -> None:
    """body 条目的结构性不变量 (2026-09-16 冒烟发现的三类坑回归钉)。"""
    for payload, spec in SHIM_MAP.items():
        body = spec.get("body")
        if not body:
            continue
        # \ProvideEnvironment 在 2025-11 内核不存在 → 必须 \@ifundefined 判定
        assert "\\ProvideEnvironment" not in body, payload
        assert "\\provideenvironment" not in body, payload
        # expl3 不存在的 \int_pow:nn
        assert "\\int_pow" not in body, payload
    # revtex4-2 系 (prl/apl/revtex4): frontmatter 机器推迟到 \begin{document}
    # 才武装, revtex3 老稿导言区 \author 会炸 \collaboration@sw/\CO@grp
    # —— shim 提前武装 + 冻结防 begin-doc 重跑清数据
    for payload in ("prl.cls", "apl.cls", "revtex4.cls"):
        body = SHIM_MAP[payload]["body"]
        assert "\\frontmatter@init" in body, payload
    # binhex.tex 兜底: newtxtext 需可展开 \nhex{w}{n} 高位补零大写 hex
    assert "\\int_to_Base:nn" in SHIM_MAP["binhex.tex"]["body"]


def test_shim_map_unknown_payload_noop(tmp_path: Path) -> None:
    ctx, eng = _ctx(tmp_path), _Eng()
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, "noshim123.cls", SHIM_PARAMS)
    assert not ok
    assert "no legacy shim" in note


def test_filemap_overrides_binhex() -> None:
    """binhex.tex 真身在 kastrup (INDEX_EXTS 无 .tex → 索引缺席) → overrides 手工映射。"""
    assert RS.filemap_cfg["overrides"]["binhex.tex"] == "kastrup"


# ---------------------------------------------------------------- F2: cs_table

# _CS_CASES 行序: payload · 粘连前文 · 期望改写后
_CS_CASES = [
    ("itemFSU", "\\itemFSU Foo", "\\item FSU Foo"),
    ("itemNGA", "\\itemNGA Bar", "\\item NGA Bar"),
    ("itemCM", "\\itemCM Baz", "\\item CM Baz"),
    ("itemBalakrishnan", "\\itemBalakrishnan X", "\\item Balakrishnan X"),
    ("itemSPELL", "\\itemSPELL Y", "\\item SPELL Y"),
    ("itemFlop", "\\itemFlop Z", "\\item Flop Z"),
    ("pari", "\\pari) text", "\\par i) text"),
    ("parii", "\\parii) text", "\\par ii) text"),
    ("itop", "{\\itop.cit.}", "{\\it op.cit.}"),
    ("hlineCd", "\\hlineCd~\\textsc{i}", "\\hline Cd~\\textsc{i}"),
    ("linebreakGF", "\\linebreakGF(2)", "\\linebreak GF(2)"),
    ("ddr", "$\\ddr$", "$\\dd r$"),
    ("ddf", "$\\ddf$", "$\\dd f$"),
    ("ddt", "$\\ddt$", "$\\dd t$"),
    ("ddR", "$\\ddR$", "$\\dd R$"),
    ("ddF", "$\\ddF$", "$\\dd F$"),
    ("frack", "$\\frack{2}$", "$\\frac k{2}$"),
    ("fracr", "$\\fracr{2}$", "$\\frac r{2}$"),
    ("Deltau", "$\\Deltau$", "$\\Delta u$"),
    ("nablau", "$\\nablau$", "$\\nabla u$"),
    ("bfr", "$\\bfr$", "$\\bf r$"),
    ("bfv", "$\\bfv$", "$\\bf v$"),
    ("bfk", "$\\bfk$", "$\\bf k$"),
    ("inV", "$x\\inV$", "$x\\in V$"),
    ("itUhuru", "{\\itUhuru}\\xspace", "{\\it Uhuru}\\xspace"),
    ("itEinstein", "{\\itEinstein}", "{\\it Einstein}"),
    ("itChandra", "{\\itChandra}", "{\\it Chandra}"),
    ("itXMM", "{\\itXMM}", "{\\it XMM}"),
    ("rmROSAT", "{\\rmROSAT}", "{\\rm ROSAT}"),
    ("rmSRG", "{\\rmSRG}", "{\\rm SRG}"),
    ("rmand", "{\\rmand} N. Paver", "{\\rm and} N. Paver"),
]


@pytest.mark.parametrize(("payload", "src", "want"), _CS_CASES)
def test_cs_table_merge_artifact_rewrite(
    tmp_path: Path, payload: str, src: str, want: str
) -> None:
    """cs_table 每条: \\old → \\new 拆回原形 (n100 splice/join 合并残骸)。"""
    assert payload in CS_TABLE, f"{payload} 不在 cs_table"
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{src}\n\\end{{document}}\n"
    )
    ctx, eng = _ctx(tmp_path), _Eng()
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, payload, CS_PARAMS)
    assert ok, note
    assert want in (tmp_path / "main.tex").read_text()


def test_cs_table_word_boundary_protects_longer_cs(tmp_path: Path) -> None:
    """\\old\\b 词边界: \\itemFSUx / \\parindent 等更长 cs 不得被误改。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\itemFSUbar keep\n\\parindent=10pt\n\\paria safe\n\\end{document}\n"
    )
    ctx, eng = _ctx(tmp_path), _Eng()
    # 零替换 → "applied nothing" False —— 关键断言是更长 cs 未被误改
    TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "itemFSU", CS_PARAMS)
    t = (tmp_path / "main.tex").read_text()
    assert "\\itemFSUbar" in t
    TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "pari", CS_PARAMS)
    t = (tmp_path / "main.tex").read_text()
    assert "\\parindent=10pt" in t
    assert "\\paria" in t


def test_cs_table_rewrite_leaves_sty(tmp_path: Path) -> None:
    """cs_map 改写面含 .sty (fixloop 产物可能粘进注入的 sty 片段)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "local.sty").write_text("\\def\\x{\\ddt}\n")
    ctx, eng = _ctx(tmp_path), _Eng()
    ok, _ = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "ddt", CS_PARAMS)
    assert ok
    assert "\\dd t" in (tmp_path / "local.sty").read_text()


def test_cs_table_usepackage_inject(tmp_path: Path) -> None:
    """citep→natbib: 缺包签名走 \\usepackage 注入 + install_file (非 cs_map)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\citep{x}\n\\end{document}\n"
    )
    ctx, eng = _ctx(tmp_path), _Eng(installable=("natbib.sty",))
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "citep", CS_PARAMS)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{natbib}" in t
    assert "natbib.sty" in eng.install_calls
    assert "\\citep{x}" in t  # cs 本身不改写


def test_cs_table_all_entries_cs_map_only() -> None:
    """本批 24 条全部是纯 cs_map (无装包/剥包副作用) —— 合并残骸语义锁。"""
    for payload in [c[0] for c in _CS_CASES]:
        spec = CS_TABLE[payload]
        assert set(spec) == {"cs_map"}, payload
        assert payload in spec["cs_map"], payload
