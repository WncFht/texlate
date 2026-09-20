"""shimfix-a 批 (task #180, #171 cluster-A 实装) —— cs_table 三臂 + aastex6x 补面。

arm 1 ``sortlist`` (×5: 1907.03923/1706.00220/1706.00324/1706.02744/
1803.03145): ``backend=bibtex`` 稿的 bundled .bbl 是 2.8/2.9 格式, TL
biblatex 3.21 不载旧读者 → ``.bbl`` 顶层 ``\\sortlist`` ``undefined_cs``。
``_CS_FIX_TABLE`` 收 ``_SORTLIST_BBL_POLYFILL`` —— svjour cls bbl arm
的零裸 ``@`` 移植: ``begindocument/before`` 钩 defer (preamble provide
会抢占 biblatex 装载期 ``\\newcommand`` 名, 1706.00221 already_def
级联实证; 普通 ``\\AtBeginDocument`` top-level 标被 lthooks 排钩尾,
biblatex 标块先读 .bbl → live 实证必须先注册到 before 钩),
``tlsv*`` 纯字母内名, ``\\csname`` 形 ``define@key``/``endsortlist``,
``\\verb{fld}``+``\\verb 内容\\endverb`` verbatim 域对 ``\\futurelet``
分流 gobble, ``\\ifx\\csname`` 守卫一律 ``\\expandafter`` 先行
(``\\ifx`` 不展开操作数, 裸写恒假=死码)。

arm 2 ``current@color`` (×6: 1306.6219/1803.00132/1803.08873/1907.00279/
2111.00020 .tex 面 + 2308.04222 .bbl 内): PoS.cls ``begindocument`` 钩序
bug —— PoS 块 ``\\auto@maketitle`` → output routine ``\\normalcolor`` →
``\\let\\current@color\\default@color`` 先于 color 块快照 → 毒化。
``begindocument/before`` 钩先于一切 ``begindocument`` 块 → 双名兜底
``gray 0``。yaml cs_table 条目 —— 测试经 ``load_ruleset()`` 取真
params 过 builtin, 顺带校验 yaml 键形。

arm 3 ``url``/``nolinkurl`` (×3+1: 1306.0187/1404.6110/0806.0347 +
2104.00028): ``url`` → 真包装位 (hyperref 被稿注释/类不提供 ``\\url``);
``nolinkurl`` 是 hyperref-only (url.sty 亦无) → ``detokenize``+``\\texttt``
同形兜底, 不装真 url.sty (aastex shim 面下会夺回 detokenize 版 ``\\url``
致参内冻结 catcode 炸面回归); ``aastex6x_body`` 补 ``\\nolinkurl`` 委托行。
"""

import re
from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]

_MAIN = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
#: 注入件零裸 ``@`` 门 —— ``\\X@`` 形 cs 在 doc 面 @=12 下必炸;
#: ``\\csname X@Y\\endcsname`` 内 ``@`` 是字符非 cs 成分, 天然豁免。
_RAW_AT_RE = re.compile(r"\\[A-Za-z]+@")


class _Eng:
    """probe/install 记录替身 —— 恒可用支路。"""

    def __init__(self) -> None:
        self.probed: list[str] = []
        self.installed: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        self.probed.append(fname)
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.installed.append(fname)
        return True


def _ctx(tmp_path: Path) -> LoopCtx:
    (tmp_path / "main.tex").write_text(_MAIN, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _read(tmp_path: Path) -> str:
    return (tmp_path / "main.tex").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _cs_params() -> dict:
    """``cs_targeted_fix`` 规则真 params —— yaml cs_table 叠默认表, 同 builtin 合并语义。"""
    return next(r for r in _rs().rules if r.id == "cs_targeted_fix").action["params"]


# ═══════════════════════ arm 1: sortlist bbl-2.8 读者 ═══════════════════════


def test_sortlist_polyfill_lands_after_docclass(tmp_path: Path) -> None:
    """``begindocument/before`` 钩块注入 docclass 缝后 —— 须先于 biblatex
    的 biblatex-标 begindocument 块 (lthooks 把 top-level 标排钩尾,
    live 实证 ``\\AtBeginDocument`` 跑在 ``\\blx@bblinput`` 之后)。"""
    ctx = _ctx(tmp_path)
    ok, note = _TARGETED(ctx, _Eng(), "sortlist", {})
    assert ok, note
    text = _read(tmp_path)
    assert "\\AddToHook{begindocument/before}" in text
    assert "\\AtBeginDocument" not in text
    assert "\\providecommand{\\sortlist}[2][]" in text
    assert "\\csname endsortlist\\endcsname" in text
    assert text.index("\\documentclass") < text.index("\\AddToHook")


def test_sortlist_polyfill_zero_raw_at(tmp_path: Path) -> None:
    """doc 面 @=12 → 注入件不得含 ``\\X@`` 形裸 cs (csname 形豁免)。"""
    ctx = _ctx(tmp_path)
    ok, _ = _TARGETED(ctx, _Eng(), "sortlist", {})
    assert ok
    block = _read(tmp_path).split("\\AddToHook", 1)[1]
    assert not _RAW_AT_RE.search(block)


def test_sortlist_polyfill_bbl_surface(tmp_path: Path) -> None:
    """bbl-2.8 面全收: sortlist/entry/name/list/field/strng/endentry/
    verb/endverb/endsortlist + keyval 名解族 + blx@bbl@data scratch 指针
    (真 ``\\entry`` 不设时 ``\\true``/``\\false`` ``\\csgappto`` 写经)。"""
    ctx = _ctx(tmp_path)
    ok, _ = _TARGETED(ctx, _Eng(), "sortlist", {})
    assert ok
    text = _read(tmp_path)
    for frag in (
        "\\def\\entry",
        "\\def\\list",
        "\\def\\keyw",
        "\\def\\name",
        "\\def\\field",
        "\\def\\strng",
        "\\def\\endentry",
        "\\def\\verb",
        "\\def\\endverb",
        "\\csname define@key\\endcsname",
        "\\csname blx@bbl@data\\endcsname{blx@data@tlsv}",
        "\\csname blx@data@tlsv\\endcsname{}",
        "\\tlsvverbdecide",
        "\\tlsvverbread",
        "\\tlsvnwalk",
    ):
        assert frag in text, frag


def test_sortlist_idempotent_second_call(tmp_path: Path) -> None:
    """snippet-in-text 幂等 —— 第二轮 applied nothing。"""
    ctx = _ctx(tmp_path)
    assert _TARGETED(ctx, _Eng(), "sortlist", {})[0]
    ok, note = _TARGETED(ctx, _Eng(), "sortlist", {})
    assert not ok
    assert "applied nothing" in note


def test_sortlist_no_split_fallback(tmp_path: Path) -> None:
    """payload 在表 → 不落 glue-拆分兜底 (sortlist 非粘连残骸)。"""
    ctx = _ctx(tmp_path)
    ok, note = _TARGETED(ctx, _Eng(), "sortlist", {})
    assert ok, note
    assert "polyfill" in note


# ═══════════════ arm 2: current@color begindocument/before 守卫 ═══════════════


def test_currentcolor_guard_early_hook(tmp_path: Path) -> None:
    """``begindocument/before`` 钩注入 —— 先于一切 begindocument 块执行。"""
    ctx = _ctx(tmp_path)
    ok, note = _TARGETED(ctx, _Eng(), "current@color", _cs_params())
    assert ok, note
    text = _read(tmp_path)
    assert "\\AddToHook{begindocument/before}" in text
    assert "\\csname default@color\\endcsname" in text
    assert "\\csname current@color\\endcsname" in text
    assert "gray 0" in text
    assert not _RAW_AT_RE.search(text)


def test_currentcolor_idempotent(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert _TARGETED(ctx, _Eng(), "current@color", _cs_params())[0]
    ok, _ = _TARGETED(ctx, _Eng(), "current@color", _cs_params())
    assert not ok


# ═══════════════════════ arm 3: url / nolinkurl ═══════════════════════


def test_url_usepackage_and_probe(tmp_path: Path) -> None:
    """``\\RequirePackage{url}`` 注入 + url.sty 探装。"""
    eng = _Eng()
    ctx = _ctx(tmp_path)
    ok, note = _TARGETED(ctx, eng, "url", _cs_params())
    assert ok, note
    assert "\\RequirePackage{url}" in _read(tmp_path)
    assert "url.sty" in eng.probed


def test_nolinkurl_polyfill_detokenize(tmp_path: Path) -> None:
    """``detokenize``+``\\texttt`` 同形 —— 不注 ``\\usepackage{url}``
    (aastex shim 面下真 url.sty 夺回 ``\\url`` 定义风险)。"""
    eng = _Eng()
    ctx = _ctx(tmp_path)
    ok, note = _TARGETED(ctx, eng, "nolinkurl", _cs_params())
    assert ok, note
    text = _read(tmp_path)
    assert "\\providecommand{\\nolinkurl}[1]{\\texttt{\\detokenize{#1}}}" in text
    assert "\\usepackage{url}" not in text
    assert "url.sty" not in eng.probed


# ═══════════════════════ aastex6x shim 补面 (2104.00028) ═══════════════════════


def test_aastex6x_body_nolinkurl_delegate() -> None:
    """``aastex6x_body`` 锚共享 —— 存活锚条目同获 ``\\nolinkurl``
    (routeclean: aastex62.cls 槽删→vendor/files 真件; clsbridge:
    AASTeX62.cls 混合大写死键删 —— shim_map 键大小写敏感永不可达)。"""
    shim_map = next(r for r in _rs().rules if r.id == "legacy_pkg_shim").action[
        "params"
    ]["shim_map"]
    body = shim_map["aastex61.cls"]["body"]
    assert "\\providecommand{\\nolinkurl}[1]{\\url{#1}}" in body
    for cls in ("aastex63.cls", "aastex631.cls"):
        assert "\\nolinkurl" in shim_map[cls]["body"]
