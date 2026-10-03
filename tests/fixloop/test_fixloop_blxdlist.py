"""blx_dlist_polyfill 单测 (blxdlist 车道，task #239)。

机理 (1502.02341 实证，blxbbl 车道普查): 稿捆绑 biblatex
v2.3 时代 .bbl —— ``\\entry`` 记录裸排顶层，无 ``\\datalist`` 包裹;
backend=bibtex → 不产 .bcf → bbl_regen(158) 的 has_ext:.bcf 门恒拒。
TL biblatex 3.21 中 ``\\blx@dlist@type``/``\\blx@dlist@name`` 的唯一
定义者是 ``\\datalist``→``\\blx@bbl@dlist`` (biblatex.sty:9280-83);
``\\blx@bbl@entry`` 的 ``\\edef\\blx@bbl@data`` (:8687) 与
``\\blx@bbl@endentry`` 双 ``\\ifstrequal`` (:8707/:8720) 全踩未定义名
→ 164 错 (54×dlist@name + 108×dlist@type + ``\\lossort``/``\\endlossort``
v2.3 排序尾标对)。本臂以 begindocument/before 钩 ifx-guarded 补名
(``\\blx@dlist@name`` 懒展开落真 refcontext 串，``\\printbibliography``
按 ``blx@dlist@entry@<sec>@<ctx>`` 读表同名命中) + lossort 对 no-op。

``\\endlossort`` 不走 ``\\providecommand`` —— ``\\@ifdefinable``
(latex.ltx:1296 ``\\@carcube`` 前三字符比 ``\\qend``) 拒一切 ``end*``
名，"Or name \\end... illegal" 实炸，只能 ifx-guarded csname ``\\def``
(xelatex 本地 repro 实证)。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _fixloopkit import biber_ok

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule, RunFn
from texlate.compile.logparse import ErrReport

_RULE_ID = "blx_dlist_polyfill"

_MAIN = (
    "\\documentclass{article}\n"
    "\\usepackage[backend=bibtex]{biblatex}\n"
    "\\bibliography{main}\n"
    "\\begin{document}\n"
    "Cite \\cite{abray1975feminism}.\n"
    "\\printbibliography\n"
    "\\end{document}\n"
)

#: biblatex v2.3 .bbl —— 裸 \\entry 无 \\datalist, \\lossort 尾标对。
_BBL = (
    "% $ biblatex auxiliary file $\n"
    "% $ biblatex version 2.3 $\n"
    "\\begingroup\\makeatletter\n"
    "\\@ifundefined{ver@biblatex.sty}{}{}\n"
    "\\endgroup\n"
    "\\entry{abray1975feminism}{article}{}\n"
    "  \\name{author}{1}{}{{Abray}{A.}{Jane}{J.}{}{}{}}\n"
    "  \\field{title}{Feminism and {Wikipedia}}\n"
    "  \\field{year}{1975}\n"
    "\\endentry\n"
    "\\lossort\n\\endlossort\n"
    "\\endinput\n"
)


#: 规则库只读共享（dedup 态在 ctx.applied 而非 ruleset 上）——一次装载。
_RS = load_ruleset()


def _rule(rid: str = _RULE_ID) -> Rule:
    return next(r for r in _RS.rules if r.id == rid)


def _params(rid: str = _RULE_ID) -> dict:
    return _rule(rid).action.get("params") or {}


def _ctx(
    tmp_path: Path,
    main: str = _MAIN,
    *,
    bbl: bool = False,
    runner: RunFn | None = None,
) -> LoopCtx:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    if bbl:
        (tmp_path / "main.bbl").write_text(_BBL, encoding="utf-8")
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _match(
    ctx: LoopCtx, pay: str | None, cat: str = "undefined_cs"
) -> tuple[Rule | None, str]:
    rep = ErrReport(file_stack=["./main.tex"])
    return actions._match_apply(_RS, ctx, None, cat, pay, rep)  # noqa: SLF001


# ----------------------------------------------------------------- 表形
def test_table_keys_exact_four() -> None:
    """cs_table 恰四键，锚点共享同一 polyfill 体。"""
    table = _params()["cs_table"]
    assert set(table) == {
        "blx@dlist@name",
        "blx@dlist@type",
        "lossort",
        "endlossort",
    }
    bodies = {table[k].get("polyfill") for k in table}
    assert len(bodies) == 1  # yaml 锚点：四键同块，任一键先中整块落


def test_polyfill_guard_forms() -> None:
    """polyfill 体：三处 ifx-csname 守卫 + lossort provide; end* 不走 provide。"""
    bodies = {v["polyfill"] for v in _params()["cs_table"].values()}
    assert len(bodies) == 1  # yaml 锚点：四键同块
    body = bodies.pop()
    assert "\\AddToHook{begindocument/before}" in body
    for cs in ("blx@dlist@type", "blx@dlist@name", "endlossort"):
        assert f"\\expandafter\\ifx\\csname {cs}\\endcsname\\relax" in body, cs
        assert f"\\expandafter\\def\\csname {cs}\\endcsname" in body, cs
    assert "\\providecommand\\lossort{}" in body
    # \@ifdefinable 恒拒 end* 名 —— provide 形实炸，禁形钉死。
    assert "\\providecommand\\endlossort" not in body
    assert "\\providecommand{\\endlossort}" not in body
    # 懒展开 refcontext: edef 期落真串，与 printbibliography 读表同名。
    assert "\\csname blx@refcontext@context\\endcsname" in body


# ----------------------------------------------------------------- 路由层
def test_fires_on_dlist_name_payload(tmp_path: Path) -> None:
    """undefined_cs|blx@dlist@name → 本臂中，polyfill 落 docclass 行后。"""
    ctx = _ctx(tmp_path)
    rule, note = _match(ctx, "blx@dlist@name")
    assert rule is not None
    assert rule.id == _RULE_ID
    assert "polyfill injected" in note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\AddToHook{begindocument/before}" in out
    assert out.index("\\AddToHook") > out.index("\\documentclass")
    # .bcf 缺席 → bbl_regen(158) 先评先拒，顺位证据。
    assert any(d.startswith("bbl_regen: cond skip") for d in ctx.declined)


def test_fires_on_all_four_payloads(tmp_path: Path) -> None:
    """@name/@type/lossort/endlossort 四个独立 payload 各自派本臂。"""
    for pay in ("blx@dlist@name", "blx@dlist@type", "lossort", "endlossort"):
        sub = tmp_path / pay.replace("@", "_")
        sub.mkdir()
        ctx = _ctx(sub)
        rule, _note = _match(ctx, pay)
        assert rule is not None, pay
        assert rule.id == _RULE_ID, pay


def test_abstains_on_b3_payload(tmp_path: Path) -> None:
    """B3 族单发 (blx@citeargs@iii 等) 无表键 → builtin 自拒，不越界。"""
    ctx = _ctx(tmp_path)
    fix = TRANSFORM_FNS["cs_targeted_fix"]
    for pay in ("blx@citeargs@iii", "blx@lbx", "blx@bbxfile"):
        ok, note = fix(ctx, None, pay, _params())
        assert not ok, pay
        assert "not in cs-fix table" in note, pay
    rule, _note = _match(ctx, "blx@citeargs@iii")
    assert rule is None or rule.id != _RULE_ID


def test_abstains_wrong_category(tmp_path: Path) -> None:
    """非 undefined_cs 类 payload → when 闸拒，不吃别类饭。"""
    ctx = _ctx(tmp_path)
    rule, _note = _match(ctx, "blx@dlist@name", cat="already_def")
    assert rule is None or rule.id != _RULE_ID


def test_abstains_no_payload(tmp_path: Path) -> None:
    """payload_required: 无 payload 的 undefined_cs 不派。"""
    ctx = _ctx(tmp_path)
    rule, _note = _match(ctx, None)
    assert rule is None or rule.id != _RULE_ID


def test_refire_idempotent(tmp_path: Path) -> None:
    """同 payload 二轮 dedup 跳过; 异 payload 续派 snippet 幂等让位。"""
    ctx = _ctx(tmp_path)
    rule1, _ = _match(ctx, "blx@dlist@name")
    assert rule1 is not None
    assert rule1.id == _RULE_ID
    rule2, _ = _match(ctx, "blx@dlist@name")
    assert rule2 is None or rule2.id != _RULE_ID
    rule3, _ = _match(ctx, "blx@dlist@type")
    assert rule3 is None or rule3.id != _RULE_ID
    assert any("applied nothing" in d for d in ctx.declined)
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert out.count("\\csname blx@dlist@type\\endcsname\\relax") == 1


# ----------------------------------------------------------------- 排序闸
def test_order_after_bbl_regen() -> None:
    """order 序位：bbl_regen(158) < 本臂 (166.5), loop 相内同序。"""
    loop = _RS.phase("loop")
    by_id = {r.id: r for r in loop}
    regen, mine = by_id["bbl_regen"], by_id[_RULE_ID]
    assert regen.order < mine.order
    ordered = sorted(loop, key=lambda r: r.order)
    assert ordered.index(regen) < ordered.index(mine)


@pytest.mark.skipif(shutil.which("biber") is None, reason="biber not installed")
def test_bbl_regen_wins_when_bcf_present(tmp_path: Path) -> None:
    """.bcf 在场 (biber 通路) → bbl_regen 先中，polyfill 不抢 —— 1502.06277 形。

    注入 rc=0 biber runner (真 biber 对伪 .bcf 会截空 .bbl 致 fmt 检
    None → failed —— 该形已在 test_fixloop_bbl_regen 覆盖; 本钉只证
    门过时的派发序位)。
    """
    ctx = _ctx(tmp_path, runner=biber_ok)
    # ``_bcf_intact`` 门：≥200B + ``</bcf:controlfile>`` 尾标
    (tmp_path / "main.bcf").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<bcf:controlfile>\n'
        + "x" * 220
        + "\n</bcf:controlfile>\n",
        encoding="utf-8",
    )
    rule, _note = _match(ctx, "blx@dlist@name")
    assert rule is not None
    assert rule.id == "bbl_regen"


# ----------------------------------------------------------------- 真编译钉
_XELATEX = shutil.which("xelatex")
_KPSEWHICH = shutil.which("kpsewhich")


def _have_biblatex() -> bool:
    if _KPSEWHICH is None:
        return False
    return (
        subprocess.run(  # noqa: S603
            [_KPSEWHICH, "biblatex.sty"], capture_output=True, check=False
        ).returncode
        == 0
    )


_HAVE_BIBLATEX = _have_biblatex()


def _xelatex(tmp_path: Path) -> None:
    subprocess.run(  # noqa: S603
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )


@pytest.mark.integration
@pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")
@pytest.mark.skipif(not _HAVE_BIBLATEX, reason="biblatex.sty not in texmf")
def test_real_xelatex_repro_and_fix(tmp_path: Path) -> None:
    """全真链钉：裸 \\entry .bbl 未修 → Undefined \\blx@dlist@name; 注入后零错。

    blxdlist 车道实证：修复稿 cites 解、书目排; 三参
    \\entry ×四参 \\blx@bbl@entry 的 #4 吞域杂字是登记 known_gap。
    """
    _ctx(tmp_path, bbl=True)
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert "Undefined control sequence" in log
    assert "\\blx@dlist@name" in log  # 未修态全真复现真稿签名

    ctx = _ctx(tmp_path)
    rule, _note = _match(ctx, "blx@dlist@name")
    assert rule is not None
    assert rule.id == _RULE_ID

    _xelatex(tmp_path)
    log2 = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    n_err = len(re.findall(r"^! ", log2, re.MULTILINE))
    assert n_err == 0, f"polyfill 注入后仍 {n_err} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")
@pytest.mark.skipif(not _HAVE_BIBLATEX, reason="biblatex.sty not in texmf")
def test_real_xelatex_ifx_guard_sentinel(tmp_path: Path) -> None:
    """ifx 守卫实证：cs 预定义 → polyfill 不重 def —— 混合格/已定义格零副作用。

    preamble 预置 ``\\blx@dlist@type``=SENTINEL + ``\\endlossort``=ENDSENT;
    钩内 ``\\ifx\\relax`` 判假 → 守卫块跳过，typeout 见证哨兵存活。
    """
    main = (
        "\\documentclass{article}\n"
        "\\usepackage[backend=bibtex]{biblatex}\n"
        "\\expandafter\\def\\csname blx@dlist@type\\endcsname{SENTINEL}\n"
        "\\expandafter\\def\\csname endlossort\\endcsname{ENDSENT}\n"
        "\\begin{document}\n"
        "\\typeout{GUARDTYPE=\\csname blx@dlist@type\\endcsname}\n"
        "\\typeout{GUARDEND=\\csname endlossort\\endcsname}\n"
        "x\n\\end{document}\n"
    )
    ctx = _ctx(tmp_path, main)
    rule, _note = _match(ctx, "blx@dlist@name")
    assert rule is not None
    assert rule.id == _RULE_ID
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    n_err = len(re.findall(r"^! ", log, re.MULTILINE))
    assert n_err == 0, f"守卫稿 {n_err} 个 '!' 错"
    assert "GUARDTYPE=SENTINEL" in log  # 守卫未覆写
    assert "GUARDEND=ENDSENT" in log
