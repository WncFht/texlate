r"""renewguard (task #234) —— cs_targeted_fix ``guard``/``guard_pre`` 键单测。

``Command \X undefined`` (latex.ltx ``\\renew@command`` 内核标记) 与 @-名/
``\\csname`` 派发 cs_table 条目的通用臂: 手写 ``\\providecommand\\X``
字面 polyfill 有两处死形 —— 裸 ``\\providecommand\\foo@bar`` 在 @=other
读面断名成 ``\\foo``+stray 字母 (静默错义 + ``Missing \\begin{document}``
级联); ``\\providecommand\\csname`` 直写把 ``\\csname`` 当已定义名静默
no-op。``guard`` emission 恒走 ``\\expandafter\\providecommand\\expandafter
{\\csname <cs>\\endcsname}<args>{<body>}`` —— @-名/裸名/含 ``.`` ``*``
名通吃 (renewguard 车道 forms*.tex 全形实证)。

语料: 2609.20238 ``\\renewcommand*\\backref[1]`` (hyperref 未开 backref
选项), math/0408290 ``\\renewcommand{\\U}{\\Upsilon}``, 1306.0124
``\\renewcommand{\\C}{\\mathbb C}``, math-ph/9901018 iopart.cls ``\\PF``
(cls 执行期 → ``guard_pre`` 面)。
"""

from pathlib import Path

from _fixloopkit import mk_ctx, n_err, requires_xelatex, run_xelatex

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.builtins.csfix import _guard_snippet

_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]

_ctx = mk_ctx


class _EngStub:
    """引擎面替身 —— probe 恒命中，install 恒成。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


def _proj(tmp_path: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _read(tmp_path: Path, rel: str) -> str:
    return (tmp_path / rel).read_text(encoding="utf-8")


# ═══════════════════════ _guard_snippet 值形归一 ═══════════════════════


def test_snippet_true_zero_arg() -> None:
    s = _guard_snippet("backref", guard=True)
    assert s == (
        "\\expandafter\\providecommand\\expandafter{\\csname backref\\endcsname}{}"
    )


def test_snippet_argspec_string() -> None:
    s = _guard_snippet("U", "[1]")
    assert s == (
        "\\expandafter\\providecommand\\expandafter{\\csname U\\endcsname}[1]{}"
    )


def test_snippet_dict_full() -> None:
    s = _guard_snippet("QED", {"args": "[1]", "body": "\\textbf{#1}"})
    assert s == (
        "\\expandafter\\providecommand\\expandafter"
        "{\\csname QED\\endcsname}[1]{\\textbf{#1}}"
    )


def test_snippet_dict_body_only() -> None:
    s = _guard_snippet("No", {"body": "\\textnumero"})
    assert s == (
        "\\expandafter\\providecommand\\expandafter"
        "{\\csname No\\endcsname}{\\textnumero}"
    )


def test_snippet_at_name_csname_wrapped() -> None:
    """@-名恒走 csname 包裹 —— 裸 ``\\providecommand\\foo@bar`` 断名死形规避。"""
    s = _guard_snippet("NAT@force@numbers", guard=True)
    assert s is not None
    assert "\\csname NAT@force@numbers\\endcsname" in s
    assert "\\providecommand\\NAT" not in s  # 断名形绝不出现


def test_snippet_rejects_structural_cs() -> None:
    for bad in ("foo{bar", "foo\\endcsname", "", "a b"):
        assert _guard_snippet(bad, guard=True) is None


def test_snippet_rejects_bad_value_type() -> None:
    assert _guard_snippet("x", 42) is None
    assert _guard_snippet("x", ["[1]"]) is None


# ═══════════════════════ cs_targeted_fix guard 分派 ═══════════════════════


def test_guard_injects_after_docclass(tmp_path: Path) -> None:
    """``guard`` → docclass 缝后 csname 形预置 (2609.20238 backref 形)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\renewcommand*\\backref[1]{}\n"
                "\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "backref",
        {"cs_table": {"backref": {"guard": "[1]"}}},
    )
    assert ok, note
    assert "guard seed injected" in note
    text = _read(tmp_path, "main.tex")
    seed = (
        "\\expandafter\\providecommand\\expandafter{\\csname backref\\endcsname}[1]{}"
    )
    assert seed in text
    # 序：docclass < seed < renew 站
    assert text.index("\\documentclass") < text.index(seed)
    assert text.index(seed) < text.index("\\renewcommand*\\backref")


def test_guard_pre_injects_before_docclass(tmp_path: Path) -> None:
    """``guard_pre`` → docclass 行前预置 (cls 执行期 renew 站，iopart \\PF 形)。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{iopart}\n\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "PF",
        {"cs_table": {"PF": {"guard_pre": True}}},
    )
    assert ok, note
    assert "pre-docclass guard injected" in note
    text = _read(tmp_path, "main.tex")
    seed = "\\expandafter\\providecommand\\expandafter{\\csname PF\\endcsname}{}"
    assert seed in text
    assert text.index(seed) < text.index("\\documentclass")


def test_guard_at_name_payload(tmp_path: Path) -> None:
    """@-payload 直达：``Command \\foo@bar undefined`` 表键命中即预置。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "NAT@force@numbers",
        {"cs_table": {"NAT@force@numbers": {"guard": True}}},
    )
    assert ok, note
    text = _read(tmp_path, "main.tex")
    assert "\\csname NAT@force@numbers\\endcsname" in text


def test_guard_idempotent_refire(tmp_path: Path) -> None:
    """重复触发幂等 —— 第二次 applied nothing。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    params = {"cs_table": {"backref": {"guard": "[1]"}}}
    ok1, _ = _TARGETED(_ctx(tmp_path), _EngStub(), "backref", params)
    assert ok1
    ok2, note2 = _TARGETED(_ctx(tmp_path), _EngStub(), "backref", params)
    assert not ok2
    assert "applied nothing" in note2
    assert _read(tmp_path, "main.tex").count("\\csname backref\\endcsname") == 1


def test_guard_coexists_polyfill_order(tmp_path: Path) -> None:
    """guard 分派先于 polyfill (note 序), 双臂同发。

    物理文件序相反：两键同走 ``_inject_after_docclass`` eol+1 缝，后注入者
    压栈在前 —— 缝位堆栈是注入器既有性质 (双 polyfill 同形), 与 spec
    应用序无关; 两枚 ``\\providecommand`` 种子相互独立，序无语义。
    """
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "x",
        {
            "cs_table": {
                "x": {
                    "guard": True,
                    "polyfill": "\\providecommand{\\ybuddy}{}",
                }
            }
        },
    )
    assert ok, note
    assert note.index("guard seed injected") < note.index("polyfill injected")
    text = _read(tmp_path, "main.tex")
    assert "\\csname x\\endcsname" in text
    assert "\\ybuddy" in text
    assert text.index("\\documentclass") < text.index("\\ybuddy")
    assert text.index("\\documentclass") < text.index("\\csname x\\endcsname")


def test_guard_existing_table_entries_intact(tmp_path: Path) -> None:
    """既有键语义零扰动 —— sortlist polyfill 仍走字面注入。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(_ctx(tmp_path), _EngStub(), "sortlist", {})
    assert ok, note
    assert "polyfill injected" in note
    assert "guard" not in note


# ═══════════════════════ xelatex 端到端 (有引擎才跑) ═══════════════════════


@requires_xelatex
def test_e2e_renew_after_guard_compiles(tmp_path: Path) -> None:
    """guard 预置 → doc 侧 ``\\renewcommand`` 合法接管 —— 2609.20238 全真形。"""
    tex = (
        "\\documentclass{article}\n"
        "\\renewcommand*\\backref[1]{#1}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    # 预检：无 guard 时即 "Command \backref undefined" 死形
    log0 = run_xelatex(tmp_path, tex)
    assert "Command \\backref undefined" in log0 or "Undefined control sequence" in log0

    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "backref",
        {"cs_table": {"backref": {"guard": "[1]"}}},
    )
    assert ok, note
    # 第二趟须编译**改写后**的 main.tex——回读现文喂回 run_xelatex (不覆盖 seed)
    log1 = run_xelatex(tmp_path, _read(tmp_path, "main.tex"))
    assert "Command \\backref undefined" not in log1
    assert n_err(log1) == 0
    assert (tmp_path / "main.pdf").exists()


@requires_xelatex
def test_e2e_at_name_renew_via_makeatletter(tmp_path: Path) -> None:
    """@-名 seed → ``\\makeatletter`` 域内 ``\\renewcommand`` 接管。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\makeatletter\n\\renewcommand\\NAT@force@numbers{}\n\\makeatother\n"
                "\\begin{document}\nx\n\\end{document}\n"
            )
        },
    )
    ok, note = _TARGETED(
        _ctx(tmp_path),
        _EngStub(),
        "NAT@force@numbers",
        {"cs_table": {"NAT@force@numbers": {"guard": True}}},
    )
    assert ok, note
    log = run_xelatex(tmp_path, _read(tmp_path, "main.tex"))
    # 严格形 (实编译复核 log 全文无 undefined 字样): renew 死形
    # ``Command \NAT@force@numbers undefined`` 与裸 undefined_cs 一并收。
    assert "undefined" not in log.lower()
    assert n_err(log) == 0


@requires_xelatex
def test_e2e_naive_at_name_form_dies(tmp_path: Path) -> None:
    """对照死形：裸 ``\\providecommand\\foo@bar`` 字面注入静默错义 —
    ``\\foo`` 被定义、``@bar`` 成裸文，目标名恒 ``\\relax``。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\providecommand\\foo@bar{}\n"
                "\\begin{document}\n"
                "\\expandafter\\ifx\\csname foo@bar\\endcsname\\relax"
                "\\typeout{RGVERDICT=DEAD}\\else\\typeout{RGVERDICT=LIVE}\\fi\n"
                "\\end{document}\n"
            )
        },
    )
    log = run_xelatex(tmp_path, _read(tmp_path, "main.tex"))
    # 裸形 = 断名错义：``foo@bar`` 仍未定义 —— guard csname emission 存在性旁证
    assert "RGVERDICT=DEAD" in log


@requires_xelatex
def test_e2e_csname_form_seeds_at_name(tmp_path: Path) -> None:
    """正面对照：guard emission 形手工复写 → ``foo@bar`` 真被预置。"""
    _proj(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n"
                "\\expandafter\\providecommand\\expandafter"
                "{\\csname foo@bar\\endcsname}{}\n"
                "\\begin{document}\n"
                "\\expandafter\\ifx\\csname foo@bar\\endcsname\\relax"
                "\\typeout{RGVERDICT=DEAD}\\else\\typeout{RGVERDICT=LIVE}\\fi\n"
                "\\end{document}\n"
            )
        },
    )
    log = run_xelatex(tmp_path, _read(tmp_path, "main.tex"))
    assert "RGVERDICT=LIVE" in log
    assert n_err(log) == 0
