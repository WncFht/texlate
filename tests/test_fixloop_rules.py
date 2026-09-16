"""rules.yaml 规则库装载校验 + when/condition 原语 + phase 序单测。"""

import re
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, RulesetError, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import (
    LoopCtx,
    Rule,
    _cond_ok,
    _substitute,
    _when_ok,
)


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（坏 yaml 报 test fail 而非 collection error）。"""
    return load_ruleset()


class _Eng:
    """cond 评估的最小引擎替身 (caps + probe)。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(self, probe_map: dict[str, str] | None = None) -> None:
        self.probe_map = probe_map or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd  # mock 不区分 cwd
        return self.probe_map.get(fname)

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def ctx_for(tmp_path: Path, engine_name: str = "xelatex") -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name=engine_name)


# ---------------------------------------------------------------- 结构校验
def test_phase_ordering() -> None:
    assert [r.id for r in _rs().phase("gate")] == [
        "pstricks_dvips_preflight",
        "latex209_reject",
    ]
    # v2: eps_route 挪 loop 层 (log 确证后兜底拒); pstricks 独立成 precheck 项
    assert [r.id for r in _rs().phase("precheck")] == [
        "pstricks_route",
        "static_precheck",
    ]
    loop = [r.id for r in _rs().phase("loop")]
    assert loop[0] == "install_file"
    assert loop[-1] == "undefined_cs_guess"
    orders = [r.order for r in _rs().phase("loop")]
    assert orders == sorted(orders)


def test_every_rule_has_provenance() -> None:
    for r in _rs().rules:
        assert r.raw.get("source_ref"), r.id
        assert r.raw.get("provenance"), r.id
        assert isinstance(r.raw.get("stats"), dict), r.id


def test_regex_rewrite_repl_no_literal_backref() -> None:
    # fixer-alreadydef 实证缺陷类 (b66a554): 单引号 yaml 'a\\g<0>' → 值含
    # \\g<0> → re.sub 把 \\ 解成字面 \, g<0> 沦为纯文本 → 匹配行被吞成
    # 字面 \g<0>。判定: g<N> 前紧邻的反斜杠串长为偶数 → 是字面非回引
    # (奇数 = ...\\ + \g<N> 合法: 转义反斜杠 + 真回引)。
    bad: list[str] = []
    for r in _rs().rules:
        act = r.raw.get("action") or {}
        if act.get("kind") != "regex_rewrite":
            continue
        for rw in (act.get("params") or {}).get("rewrites") or []:
            repl = rw.get("repl") or ""
            for m in re.finditer(r"\\+g<[^>]*>", repl):
                slashes = len(m.group(0)) - len(m.group(0).lstrip("\\"))
                if slashes % 2 == 0:
                    bad.append(f"{r.id}: {repl!r}")
    assert not bad, "literal g<N> (even backslash run) in repl: " + "; ".join(bad)


def test_version_guard_policy_present() -> None:
    # 对账第 25 条: 非 rules 条目, 是 filemap 段的 ctan_fetch 前置检查策略
    vg = _rs().filemap_cfg["version_guard"]
    assert vg["enabled"] is True
    assert vg["texlive_format_epoch"] == "2022-07-14"


def test_engine_spec_default_and_degrade() -> None:
    by_id = {r.id: r for r in _rs().rules}
    assert by_id["latex209_reject"].engine_spec("nonsense") == {"mode": "native"}
    spec = by_id["install_file"].engine_spec("tectonic")
    assert spec["mode"] == "degrade"
    assert spec["degrade"] == "ctan_fetch"
    assert by_id["eps_route"].engine_spec("xelatex")["mode"] == "skip"


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 2, "rules": []},
        {
            "version": 1,
            "rules": [{"phase": "loop", "when": {}, "action": {"kind": "run_tool"}}],
        },  # 缺 id
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "weird",
                    "when": {},
                    "action": {"kind": "run_tool"},
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {"id": "x", "phase": "loop", "when": {}, "action": {"kind": "nope"}}
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {"kind": "builtin_transform", "function": "no_such_fn"},
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {
                        "kind": "regex_rewrite",
                        "params": {
                            "rewrites": [{"pattern": "a", "function": "nope_fn"}]
                        },
                    },
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {"kind": "run_tool"},
                    "engines": {"xelatex": {"mode": "bogus"}},
                }
            ],
        },
    ],
)
def test_ruleset_validation_errors(bad: dict) -> None:
    with pytest.raises(RulesetError):
        Ruleset(bad)


def test_warn_driven_fixes_toggle() -> None:
    data = {
        "version": 1,
        "meta": {"loop": {"warn_driven_fixes": False}},
        "taxonomy": [
            {"id": "warn_utf8", "scope": "warnings", "warn_id": "invalid_utf8"}
        ],
        "rules": [],
    }
    rs = Ruleset(data)
    assert rs.taxonomy.warn == []
    assert rs.taxonomy.warn_cats == set()


# ---------------------------------------------------------------- when
def test_when_always() -> None:
    assert _when_ok({"always": True}, None, None, ctx_for(Path.cwd()))


def test_when_category_and_payload_required() -> None:
    ctx = ctx_for(Path.cwd())
    w = {"category": "missing_file", "payload_required": True}
    assert _when_ok(w, "missing_file", "a.sty", ctx)
    assert not _when_ok(w, "missing_file", None, ctx)
    assert not _when_ok(w, "missing_tfm", "a.tfm", ctx)


def test_when_any_with_main_head(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\documentstyle{article}\n")
    ctx = ctx_for(tmp_path)
    ctx.main_rel = "main.tex"
    w = {
        "any": [
            {"category": "latex209"},
            {"category": "missing_file", "main_head_contains": "\\documentstyle"},
        ]
    }
    assert _when_ok(w, "missing_file", "x.sty", ctx)
    assert not _when_ok(w, "other", None, ctx)


def test_when_empty_never_matches(tmp_path: Path) -> None:
    assert not _when_ok({}, "missing_file", "x", ctx_for(tmp_path))


# ---------------------------------------------------------------- substitute
def test_substitute_payload_nested() -> None:
    out = _substitute({"f": "{payload}.tfm", "l": ["{payload}", 1]}, "phvb")
    assert out == {"f": "phvb.tfm", "l": ["phvb", 1]}


# ---------------------------------------------------------------- condition
def test_cond_tool_and_cap(tmp_path: Path) -> None:
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"tool_available": "sh"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, why = _cond_ok(
        {"tool_available": "no_such_tool_xyz"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert not ok
    assert "unavailable" in why
    ok, _ = _cond_ok({"cap_available": "tlmgr"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"cap_available": "bundle"}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_engine_in_and_unknown_key(tmp_path: Path) -> None:
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"engine_in": ["xelatex"]}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"engine_in": ["tectonic"]}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok
    ok, why = _cond_ok({"bogus_key": 1}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok
    assert "unknown condition" in why  # fail-closed


def test_cond_source_ctx_fileset(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\usepackage{minted}\n\\pdfoutput=1\n")
    (tmp_path / "x.bbl").write_text("bbl")
    ctx, eng = ctx_for(tmp_path), _Eng()
    ctx.main_rel = "main.tex"
    ok, _ = _cond_ok(
        {"source_contains": "\\\\usepackage"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert ok
    ok, _ = _cond_ok(
        {"fileset": {"has_ext": [".bbl"], "lacks_ext": [".bib"]}},
        Rule({"id": "r"}),
        ctx,
        eng,
        None,
    )
    assert ok
    ok, _ = _cond_ok(
        {"fileset": {"has_ext": [".bib"]}}, Rule({"id": "r"}), ctx, eng, None
    )
    assert not ok
    ctx.err_head = "see \\hyphenation{中}"
    ok, _ = _cond_ok(
        {"ctx_suggests": "\\\\hyphenation"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert ok


def test_cond_cache_dir_glob_and_prim_read_form(tmp_path: Path) -> None:
    (tmp_path / "_minted-main").mkdir()
    (tmp_path / "main.tex").write_text("\\ifnum\\pdfoutput>0 yes\\fi\n")
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"cache_dir_glob": "_minted-*"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"prim_read_form": "pdfoutput"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"prim_read_form": "pdfinfo"}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_package_version_ge(tmp_path: Path) -> None:
    sty = tmp_path / "minted.sty"
    sty.write_text("\\ProvidesPackage{minted}[2025/01/01 v3.0 minted]\n")
    ctx, eng = ctx_for(tmp_path), _Eng({"minted.sty": str(sty)})
    cond = {"package_version_ge": {"file": "minted.sty", "version": 3}}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    cond = {"package_version_ge": {"file": "minted.sty", "version": 4}}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_any_or() -> None:
    ctx, eng = ctx_for(Path.cwd()), _Eng()
    cond = {"any": [{"cap_available": "bundle"}, {"cap_available": "tlmgr"}]}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    cond = {"any": [{"cap_available": "bundle"}, {"cap_available": "none"}]}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


# ---------------------------------------------------------------- 2026-09-16 规则单元


class _EngInstall(_Eng):
    """_Eng + install_file (cs_targeted_fix 的装包断言用)。"""

    def __init__(
        self, probe_map: dict[str, str] | None = None, installable: tuple = ()
    ) -> None:
        super().__init__(probe_map)
        self.installable = set(installable)
        self.install_calls: list[str] = []

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        return fname in self.installable


def test_strip_inputenc_solo_list_and_inputencoding(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[latin1]{inputenc}\n"
        "\\usepackage{amsmath,inputenc,graphicx}\n"
        "\\inputencoding{latin9}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    ctx, eng = ctx_for(tmp_path), _Eng()
    ctx.main_rel = "main.tex"
    ok, note = TRANSFORM_FNS["strip_inputenc"](ctx, eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    # 独载 → 整行注释; 列表 → 外科摘除; \inputencoding → 删除
    assert "% fixloop: stripped \\usepackage[latin1]{inputenc}" in t
    assert "\\usepackage{amsmath,graphicx}" in t
    assert "\\inputencoding" not in t
    # 非注释行里不再装载 inputenc
    for ln in t.splitlines():
        assert "inputenc" not in ln or ln.lstrip().startswith("%"), ln


def test_strip_inputenc_inline_solo_keeps_tail(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\usepackage{inputenc}\\usepackage{amsmath}\n")
    ctx, eng = ctx_for(tmp_path), _Eng()
    ctx.main_rel = "main.tex"
    ok, _ = TRANSFORM_FNS["strip_inputenc"](ctx, eng, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{amsmath}" in t  # 行内嵌入置空, 不吃行尾


def test_cs_targeted_fix_strips_breakurl(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{hyperref}\n"
        "\\usepackage[hyphenbreaks]{breakurl}\n\\begin{document}\n\\end{document}\n"
    )
    ctx, eng = ctx_for(tmp_path), _EngInstall()
    ctx.main_rel = "main.tex"
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "headerps@out", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "% fixloop: stripped \\usepackage[hyphenbreaks]{breakurl}" in t
    assert "\\usepackage{hyperref}" in t  # 无关包不动


def test_cs_targeted_fix_mathbbm_per_engine(tmp_path: Path) -> None:
    # tectonic: bbm 剥 + dsfont 注入 + \\mathbbm→\\mathds
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{bbm}\n"
        "\\begin{document}\n$\\mathbbm{1}$\n\\end{document}\n"
    )
    ctx, eng = ctx_for(tmp_path, "tectonic"), _EngInstall(installable=("dsfont.sty",))
    ctx.main_rel = "main.tex"
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "mathbbm", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{dsfont}" in t
    assert "\\mathds{1}" in t
    assert "\\mathbbm" not in t
    assert "dsfont.sty" in eng.install_calls

    # xelatex: bbm 已在源码 → 不重复注入, 只确保 bbm.sty 可用
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{bbm}\n"
        "\\begin{document}\n$\\mathbbm{1}$\n\\end{document}\n"
    )
    ctx2, eng2 = ctx_for(tmp_path), _EngInstall(installable=("bbm.sty",))
    ctx2.main_rel = "main.tex"
    ok, _ = TRANSFORM_FNS["cs_targeted_fix"](ctx2, eng2, "mathbbm", {})
    assert ok
    t2 = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{dsfont}" not in t2  # bbm 已装载 → 不重复注入
    assert "\\mathbbm{1}" in t2  # xelatex 不改写 cs
    assert "bbm.sty" in eng2.install_calls


def test_cs_targeted_fix_unknown_cs_noop(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ctx, eng = ctx_for(tmp_path), _EngInstall()
    ctx.main_rel = "main.tex"
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](ctx, eng, "whatevercs", {})
    assert not ok
    assert "not in cs-fix table" in note


def test_new_rules_present_and_ordered() -> None:
    ids = [r.id for r in _rs().phase("loop")]
    assert "inputenc_strip" in ids
    assert "cs_targeted_fix" in ids
    assert ids.index("inputenc_strip") < ids.index("non_utf8_source")
    assert ids.index("cs_targeted_fix") > ids.index("journal_cs_polyfill")
    assert ids.index("cs_targeted_fix") < ids.index("undefined_cs_guess")
