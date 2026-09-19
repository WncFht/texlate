"""csfix2 批 (task #119) —— 四件直改单测。

item 1 ``undefine_for_redef`` 包装载点臂 (bbkresid 4 格): file:line 形
already_def 抽肇事包 sty 茎, ``\\let\\X\\@undefined`` 前置到其每个 live
用户件 ``\\usepackage``/``\\RequirePackage`` 装载点 —— 报错包恒为后定义者
→ 序恒正确; docclass 块鞭长莫及的 preamble 包先定义互撞由此收
(newtxmath→amssymb ``\\Bbbk`` 同型)。无用户件装载点 (cls 内传递装载) →
docclass 块兜底; 死站 (注释/verbatim) 遮盖复核剔除。

item 2 ``\\reserveinserts`` (shipclscen 2308.04212/2403.00111): WileyNJD-v2
cls:248 调已移除内核 cs → ``polyfill_pre`` 落 ``\\documentclass`` 行前
(cls 执行期调用面, 缝后注入够不到)。

item 3 ``premature_cs_guard`` (shipclscen 2009.11053): 随源 mystyle.sty:33
装载期 ``\\numberwithin`` 先于 amsmath 装载 → Missing ``\\begin{document}``
级联。供方 ``\\usepackage`` 前置到肇事 sty 的每个 live 消费方装载点 (真
def 就位非 gobble); .tex 肇事件退 docclass 缝顶; .cls/.def/.clo 传递装载
无锚点 abstain。TRANSFORM_FNS 注册是 leader 待办 → 测试直取叶子函数。

item 4 扫描器双守 (aastex61if census): ``unclosed_if_close`` 内嵌扫描器
假开两族 —— ``\\@boole@def`` caller-supplies-\\fi 习语 (aastex 5.2 ×5,
def 组冻结计) 与 ``\\let\\sep=,`` 字符赋值 CONSUME=2 吞真 ``\\fi``
(elsarticle/IEEEtran); 196/196.5 双拷贝同改, 真亏格注入面不退。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop._builtins_csfix import premature_cs_guard
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport
from texlate.textutil import ifscan

_UNDEF = TRANSFORM_FNS["undefine_for_redef"]
_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]
_IFCLOSE_IDS = ("unclosed_if_close", "unclosed_if_close_eof")
_MARK = "texlate-fixloop-injected"

#: bbkresid 同型 file:line already_def (amssymb.sty:261 报错 = 后定义者)。
_BBBK_LOG = (
    "./main.tex:183: \\usepackage{amssymb}\n"
    "/texmf-dist/tex/latex/amsfonts/amssymb.sty:261: LaTeX Error: "
    "Command `\\Bbbk' already defined.\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
)

#: 2009.11053 同型: 肇事 sty file:line + l.N 行尾肇事 cs。
_MBD_STY_LOG = (
    "./mystyle.sty:33: LaTeX Error: Missing \\begin{document}.\n"
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
    "l.33 \\numberwithin{e\n"
)


class _EngStub:
    """引擎面替身 —— probe 恒命中, install 恒成 (可用支路)。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


class _EngMissing:
    """供方包双侧均缺 → WARNING 支路。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del fname, cwd
        return ""

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False


def _ctx(tmp_path: Path, **kw: object) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", **kw)


def _proj(tmp_path: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _read(tmp_path: Path, rel: str) -> str:
    return (tmp_path / rel).read_text(encoding="utf-8")


# ═══════════════════════ item 1: 包装载点清位臂 ═══════════════════════


def test_pkgloadsite_basic_prepend_before_usepackage(tmp_path: Path) -> None:
    """肇事包 amssymb 的 ``\\usepackage`` 站前 ``\\makeatletter`` 包裹清位。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{newtxmath}\n"
                "\\usepackage{amssymb}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok, note
    assert "pkg-load-site" in note
    text = _read(tmp_path, "main.tex")
    ins = "\\makeatletter\\let\\Bbbk\\@undefined\\makeatother\n\\usepackage{amssymb}"
    assert ins in text
    # 装载点清位已覆盖 → docclass 块不再重发 (全件恰一处 \let)。
    assert text.count("\\let\\Bbbk\\@undefined") == 1
    assert "% fixloop: batch undefine" not in text
    # 序: newtxmath (先定义者) < 清位 < amssymb (后定义者)。
    assert text.index("\\usepackage{newtxmath}") < text.index(ins)


def test_pkgloadsite_opts_and_comma_list(tmp_path: Path) -> None:
    """``[opts]`` 前缀 + 逗号列含肇事茎 → 同站前置。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage[psamsfonts]{amssymb,amsfonts}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, _ = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok
    text = _read(tmp_path, "main.tex")
    assert (
        "\\makeatletter\\let\\Bbbk\\@undefined\\makeatother\n"
        "\\usepackage[psamsfonts]{amssymb,amsfonts}" in text
    )


def test_pkgloadsite_requirepackage_and_dup_sites(tmp_path: Path) -> None:
    """``\\RequirePackage`` 同收; dup 装载点逐站前置 (2003.10792 双载形)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amssymb}\n"
                "\\RequirePackage{amssymb}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok, note
    assert "2 usepackage site(s)" in note
    text = _read(tmp_path, "main.tex")
    assert text.count("\\let\\Bbbk\\@undefined") == 2  # noqa: PLR2004 - dup 双站
    assert text.count("\\makeatletter") == 2  # noqa: PLR2004 - 同上每站一对


def test_pkgloadsite_dead_site_falls_back_docclass(tmp_path: Path) -> None:
    """唯一装载点被注释 → 死站不锚, docclass 块兜底 (仍是清位非 no-op)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "% \\usepackage{amssymb}\n"
                "\\usepackage{newtxmath}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok, note
    assert "pkg-load-site" not in note
    text = _read(tmp_path, "main.tex")
    assert text.count("\\let\\Bbbk\\@undefined") == 1
    assert "% fixloop: batch undefine" in text
    # docclass 块在 docclass 后、无关 \usepackage 前不无谓前置。
    assert text.index("\\let\\Bbbk\\@undefined") > text.index("\\documentclass")
    assert text.index("\\let\\Bbbk\\@undefined") < text.index("\\usepackage{newtxmath}")


def test_pkgloadsite_no_user_site_docclass_fallback(tmp_path: Path) -> None:
    """肇事包零用户件装载点 (cls 内传递装载) → abstain 臂 + docclass 块兜底。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{newtxmath}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok, note
    assert "docclass block" in note
    text = _read(tmp_path, "main.tex")
    assert text.count("\\let\\Bbbk\\@undefined") == 1
    # 不往无关 \usepackage 前塞 no-op 清位。
    assert (
        "\\makeatletter\\let\\Bbbk\\@undefined\\makeatother\n\\usepackage{newtxmath}"
        not in text
    )


def test_pkgloadsite_sty_file_bare_let(tmp_path: Path) -> None:
    """``.sty`` 消费件 ``\\RequirePackage`` 站 → 裸 ``\\let`` (@ 本 letter)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{mypkg}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mypkg.sty": (
                "\\NeedsTeXFormat{LaTeX2e}\n\\RequirePackage{amssymb}\n\\endinput\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ok, _ = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok
    sty = _read(tmp_path, "mypkg.sty")
    assert "\\let\\Bbbk\\@undefined\n\\RequirePackage{amssymb}" in sty
    assert "\\makeatletter" not in sty
    # 主件只装 mypkg (非肇事茎) → 不动也无 docclass 块。
    main = _read(tmp_path, "main.tex")
    assert "\\let\\Bbbk" not in main


def test_pkgloadsite_endstar_name_excluded(tmp_path: Path) -> None:
    """``end*`` 恒拒名不入装载点臂亦不入 docclass 块 → 诚实 decline。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amssymb}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": (
                "/texmf/amssymb.sty:100: LaTeX Error: "
                "Command `\\endfoo' already defined.\n"
            ),
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "endfoo", {})
    assert not ok
    assert "end*" in note
    text = _read(tmp_path, "main.tex")
    assert "\\let\\endfoo" not in text
    assert "\\@rc@ifdefinable" not in text


def test_pkgloadsite_refire_idempotent(tmp_path: Path) -> None:
    """二轮: 前缀窗见 ``\\let\\Bbbk\\@undefined`` → 跳过, docclass 块亦不重发。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amssymb}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG,
        },
    )
    ctx = _ctx(tmp_path)
    ok1, _ = _UNDEF(ctx, _EngStub(), "Bbbk", {})
    assert ok1
    ctx2 = _ctx(tmp_path)
    ok2, note2 = _UNDEF(ctx2, _EngStub(), "Bbbk", {})
    assert not ok2
    assert "already cleared" in note2
    assert _read(tmp_path, "main.tex").count("\\let\\Bbbk\\@undefined") == 1


def test_pkgloadsite_min_batch_gate(tmp_path: Path) -> None:
    """``min_batch=2`` (110.5 批规则口径): 单撞名让位, 双撞名同站合清。"""
    tex = (
        "\\documentclass{article}\n"
        "\\usepackage{amssymb}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    _proj(tmp_path, {"main.tex": tex, "main.log": _BBBK_LOG})
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {"min_batch": 2})
    assert not ok
    assert "<2" in note

    tmp2 = tmp_path / "two"
    _proj(
        tmp2,
        {
            "main.tex": tex,
            "main.log": _BBBK_LOG + "/texmf/amssymb.sty:262: LaTeX Error: "
            "Command `\\Foo' already defined.\n",
        },
    )
    ok2, _ = _UNDEF(_ctx(tmp2), _EngStub(), "Bbbk", {"min_batch": 2})
    assert ok2
    text = _read(tmp2, "main.tex")
    assert "\\let\\Bbbk\\@undefined\\let\\Foo\\@undefined" in text


def test_pkgloadsite_multi_err_stems_split(tmp_path: Path) -> None:
    """双肇事包 (不同 sty 茎) → 各自装载点前清位。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amssymb}\n"
                "\\usepackage{mathrsfs}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": _BBBK_LOG + "/texmf/mathrsfs.sty:74: LaTeX Error: "
            "Command `\\mathscr' already defined.\n",
        },
    )
    ok, note = _UNDEF(_ctx(tmp_path), _EngStub(), "Bbbk", {})
    assert ok, note
    text = _read(tmp_path, "main.tex")
    assert (
        "\\makeatletter\\let\\Bbbk\\@undefined\\makeatother\n\\usepackage{amssymb}"
        in text
    )
    assert (
        "\\makeatletter\\let\\mathscr\\@undefined\\makeatother\n\\usepackage{mathrsfs}"
        in text
    )


# ═══════════════════ item 2: \reserveinserts polyfill_pre ═══════════════════


def test_reserveinserts_polyfill_pre_before_docclass(tmp_path: Path) -> None:
    """cls 执行期调用面 → ``\\providecommand`` 落 ``\\documentclass`` 行前。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{WileyNJD-v2}\n"
                "\\usepackage{amsmath}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(_ctx(tmp_path), _EngStub(), "reserveinserts", {})
    assert ok, note
    assert "pre-docclass" in note
    text = _read(tmp_path, "main.tex")
    assert "\\providecommand\\reserveinserts[1]{}" in text
    assert text.index("\\providecommand\\reserveinserts") < text.index(
        "\\documentclass"
    )


def test_reserveinserts_refire_applied_nothing(tmp_path: Path) -> None:
    """二轮 snippet 已在 → applied nothing, 不重复注入。"""
    _proj(
        tmp_path,
        {
            "main.tex": "\\documentclass{WileyNJD-v2}\n\\begin{document}\nx\n\\end{document}\n"
        },
    )
    ok1, _ = _TARGETED(_ctx(tmp_path), _EngStub(), "reserveinserts", {})
    assert ok1
    ok2, note2 = _TARGETED(_ctx(tmp_path), _EngStub(), "reserveinserts", {})
    assert not ok2
    assert "applied nothing" in note2


# ═══════════ item 3: premature_cs_guard (供方前置, TRANSFORM_FNS 待注册) ═══════════


def _premature(
    ctx: LoopCtx, eng: object = None, params: dict | None = None
) -> tuple[bool, str]:
    return premature_cs_guard(ctx, eng or _EngStub(), None, params or {})


def test_premature_sty_consumer_site_prepend(tmp_path: Path) -> None:
    """2009.11053 同型: mystyle 站前补 ``\\usepackage{amsmath}`` —— 供方虽
    在更后逗号列已装, 消费方装载期仍缺位 → 前置到消费方装载点才保时序。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{ctexart}\n"
                "\\usepackage{mystyle}\n"
                "\\usepackage{amssymb,amsmath,amsfonts}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": (
                "\\NeedsTeXFormat{LaTeX2e}\n"
                "\\numberwithin{equation}{chapter}\n"
                "\\endinput\n"
            ),
            "main.log": _MBD_STY_LOG,
        },
    )
    ok, note = _premature(_ctx(tmp_path))
    assert ok, note
    assert "provider prepend" in note
    text = _read(tmp_path, "main.tex")
    ins = "\\usepackage{amsmath} % fixloop: premature provider\n\\usepackage{mystyle}"
    assert ins in text
    # 供方更后的装载行原样保留 (kernel 幂等去重)。
    assert "\\usepackage{amssymb,amsmath,amsfonts}" in text
    assert text.count("fixloop: premature provider") == 1


def test_premature_sty_opts_comma_consumer(tmp_path: Path) -> None:
    """消费方在 ``[opts]``/逗号列装载点内 → 同站前置。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage[dvips]{graphicx,mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\numberwithin{equation}{section}\n\\endinput\n",
            "main.log": _MBD_STY_LOG,
        },
    )
    ok, _ = _premature(_ctx(tmp_path))
    assert ok
    text = _read(tmp_path, "main.tex")
    assert (
        "\\usepackage{amsmath} % fixloop: premature provider\n"
        "\\usepackage[dvips]{graphicx,mystyle}" in text
    )


def test_premature_sty_provider_already_first_noop(tmp_path: Path) -> None:
    """供方已先于消费方装载 → seen 集跳过, 诚实 decline 不烧轮次。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{amsmath}\n"
                "\\usepackage{mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\numberwithin{equation}{section}\n\\endinput\n",
            "main.log": _MBD_STY_LOG,
        },
    )
    tex = _read(tmp_path, "main.tex")
    ok, note = _premature(_ctx(tmp_path))
    assert not ok
    assert "no reachable consumer load site" in note
    assert _read(tmp_path, "main.tex") == tex


def test_premature_tex_stem_docclass_seam(tmp_path: Path) -> None:
    """肇事件是 .tex (无 usepackage 自锚) → docclass 缝顶补供方。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\numberwithin{equation}{section}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "main.log": (
                "./main.tex:2: LaTeX Error: Missing \\begin{document}.\n"
                "l.2 \\numberwithin{e\n"
            ),
        },
    )
    ok, note = _premature(_ctx(tmp_path))
    assert ok, note
    assert "docclass-seam provider amsmath" in note
    text = _read(tmp_path, "main.tex")
    assert text.index("\\usepackage{amsmath} % fixloop") < text.index("\\numberwithin")


def test_premature_cls_stem_abstain(tmp_path: Path) -> None:
    """肇事 .cls/.def/.clo 系 cls 内传递装载 → 无用户件锚点, abstain。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{mycls}\n\\begin{document}\nx\n\\end{document}\n"
            ),
            "mycls.cls": "\\numberwithin{equation}{section}\n",
            "main.log": (
                "./mycls.cls:1: LaTeX Error: Missing \\begin{document}.\n"
                "l.1 \\numberwithin{e\n"
            ),
        },
    )
    ok, note = _premature(_ctx(tmp_path))
    assert not ok
    assert "no premature-cs pair" in note
    assert "\\usepackage{amsmath}" not in _read(tmp_path, "main.tex")


def test_premature_unknown_cs_decline(tmp_path: Path) -> None:
    """l.N 行尾肇事 cs 不在供方表 → 供方不可考, decline。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\boguscs{x}\n\\endinput\n",
            "main.log": (
                "./mystyle.sty:1: LaTeX Error: Missing \\begin{document}.\n"
                "l.1 \\boguscs{x\n"
            ),
        },
    )
    ok, note = _premature(_ctx(tmp_path))
    assert not ok
    assert "no premature-cs pair" in note


def test_premature_refire_idempotent(tmp_path: Path) -> None:
    """二轮: 自注 ``\\usepackage{amsmath}`` 行即成先装站 → seen 集免重复。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\numberwithin{equation}{section}\n\\endinput\n",
            "main.log": _MBD_STY_LOG,
        },
    )
    ok1, _ = _premature(_ctx(tmp_path))
    assert ok1
    ok2, note2 = _premature(_ctx(tmp_path))
    assert not ok2
    assert "no reachable" in note2
    assert _read(tmp_path, "main.tex").count("\\usepackage{amsmath}") == 1


def test_premature_err_head_source(tmp_path: Path) -> None:
    """err_head 载错误面 (log 缺席) → 同判同修。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\numberwithin{equation}{section}\n\\endinput\n",
        },
    )
    ctx = _ctx(
        tmp_path,
        err_head=(
            "mystyle.sty:1: LaTeX Error: Missing \\begin{document}.\n"
            "l.1 \\numberwithin{e"
        ),
    )
    ok, _ = _premature(ctx)
    assert ok
    assert "\\usepackage{amsmath} % fixloop" in _read(tmp_path, "main.tex")


def test_premature_missing_provider_warns(tmp_path: Path) -> None:
    """供方包装不上 → 修已施 + WARNING 注记 (不转 fail)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\usepackage{mystyle}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            ),
            "mystyle.sty": "\\numberwithin{equation}{section}\n\\endinput\n",
            "main.log": _MBD_STY_LOG,
        },
    )
    ok, note = _premature(_ctx(tmp_path), _EngMissing())
    assert ok
    assert "WARNING: amsmath.sty not found" in note


# ═══════════ item 4: unclosed_if_close 扫描器双守 (196/196.5 同改) ═══════════


def _rule(rid: str) -> Rule:
    return next(r for r in load_ruleset().rules if r.id == rid)


def _scan(tmp_path: Path, rid: str = "unclosed_if_close") -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 测试面直驱同 ifclose 先例
        _rule(rid),
        LoopCtx(wdir=tmp_path, engine_name="xelatex"),
        None,
        None,
        ErrReport(),
    )


def test_scanner_both_copies_carry_guards() -> None:
    """196/196.5 双拷贝共用 ``textutil.ifscan`` —— ``@boole@def`` + ``let`` lookahead 特判在模块表。"""
    for rid in _IFCLOSE_IDS:
        script = _rule(rid).action["params"]["argv"][2]
        assert "scan_ifs" in script, rid
    assert "@boole@def" in ifscan.DEFCMD
    assert "let" not in ifscan.CONSUME


def test_scanner_booledef_idiom_no_false_open(tmp_path: Path) -> None:
    """caller-supplies-\\fi 习语: def 组冻结计 → 不注 ``\\fi`` (aastex 5.2 ×N)。"""
    tex = (
        "\\documentclass{article}\n"
        "\\@boole@def\\@ifx#1{\\ifx#1}\n"
        "\\@boole@def\\@ifnum#1{\\ifnum#1}\n"
        "\\@boole@def\\@ifdimb#1{\\ifdim#1}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    _proj(tmp_path, {"main.tex": tex})
    ok, note = _scan(tmp_path)
    assert ok
    assert _read(tmp_path, "main.tex") == tex
    assert "noop" in note


def test_scanner_let_char_value_close_stays_live(tmp_path: Path) -> None:
    """``\\let\\sep=,`` 字符赋值: 其 ``\\fi`` 是 live close 非名位 → 不吞。"""
    tex = (
        "\\documentclass{article}\n"
        "\\newif\\iffoo\n"
        "\\iffoo \\let\\sep=,\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    _proj(tmp_path, {"main.tex": tex})
    ok, _ = _scan(tmp_path)
    assert ok
    assert _read(tmp_path, "main.tex") == tex


def test_scanner_let_cs_value_still_consumed(tmp_path: Path) -> None:
    """``\\let\\a\\fi`` cs 赋值对象仍吃 → ``\\iffoo`` 真亏格照注。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\iffoo \\let\\a\\fi\n"
                "\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, _ = _scan(tmp_path)
    assert ok
    text = _read(tmp_path, "main.tex")
    assert _MARK in text  # 注入发生 = \fi 被 let 吃掉后亏格正确识别


def test_scanner_real_deficit_still_injects(tmp_path: Path) -> None:
    """真未闭 ``\\if`` → ``\\fi`` 照注 (守卫不过矫)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\iffoo x\n"
                "\\begin{document}\ny\n\\end{document}\n"
            )
        },
    )
    ok, _ = _scan(tmp_path)
    assert ok
    text = _read(tmp_path, "main.tex")
    assert "\\fi" in text
    assert _MARK in text
