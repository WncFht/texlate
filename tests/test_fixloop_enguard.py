"""稿自带 .sty/.cls ``\\Require{PDF,Lua,LuaMeta}TeX`` 引擎闸剥除单测.

实证背景 (failmine4 普查, soak-2026-09-18 15 fresh cells 全 2609.*):
e-print 自带 ``aaai2027.sty`` (4 md5 变体) 内置
``\\RequirePackage{iftex}`` + ``\\RequirePDFTeX`` 独占行引擎闸
(:14/:43/:59/:62 变体位) —— xelatex 下 iftex 打横幅
``pdfTeX is required to compile this document`` 后 file-line 形
``aaai2027.sty:N: Emergency stop`` + ``l.N \\RequirePDFTeX`` 回显,
taxonomy 归 ``emergency`` (2609.19158 build-base/main.log 实读
``('emergency', None)``)。修复面: err ctx 回显 guard cs ∧ 顶层
``*.sty``/``*.cls`` 在场 ∧ 源 blob 含 guard cs 三证 → sh 脚本逐件剥
注释行后按独占行形确证删行 (行尾允许空白/% 注释), 尾注
``texlate-fixloop-injected`` 幂等; ``iftex`` 载留无害, 不路由 pdftex
(zh 管线定死 xelatex+ctex)。剥面只收 xelatex 下必死子集
(``PDFTeX``/``LuaTeX``/``LuaMetaTeX``) —— ``\\RequireXeTeX`` 本机通过
不剥。下游 ``\\pdfinfo`` 原语残留属既有 ``PDFTEX_PRIMS``/shim 覆盖面
(2609.19158 真实 cell 剥后 xelatex 出 11 页 PDF, 残 ``\\pdfinfo``
undefined_cs ×2 由后位规则接)。
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, actions, fixloop, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport, parse_text

_RULE_ID = "engine_guard_strip"

# 2609.19158 build-base/main.log 实证 err_head 形 (file-line Emergency +
# l.N 回显 + cannot-read 尾) —— rep.first + rep.ctx 拼接态。
_ERR_PDFTEX = (
    "./aaai2027.sty:59: Emergency stop.\n"
    "<read *> \n         \n"
    "l.59 \\RequirePDFTeX\n"
    "                   \n"
    "*** (cannot \\read from terminal in nonstop modes)\n"
)
_ERR_LUATEX = (
    "./aaai2027.sty:14: Emergency stop.\n"
    "<read *> \n         \n"
    "l.14 \\RequireLuaTeX\n"
    "                   \n"
    "*** (cannot \\read from terminal in nonstop modes)\n"
)

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"

#: 4 变体实证闸行位 (aaai2027.sty md5 变体: 19164→14, 19559→43,
#: 19158→59, 20304→62)。
_GUARD_LINES = (14, 43, 59, 62)

#: 本机 soak cell 抽出的真实 aaai2027.sty (gitignored —— 缺席 skip)。
_REAL_STY = Path("bench/results/soak-2026-09-18/work/2609.19158/src/aaai2027.sty")


def _guard_sty(guard_line: int, guard: str = "\\RequirePDFTeX") -> str:
    """构造稿自带 sty: 引擎闸行落在指定行号 (aaai2027 变体位复刻)."""
    head = ["\\ProvidesPackage{aaai2027}[2027/05/04 AAAI 2027 Submission]"]
    while len(head) < guard_line - 2:
        head.append("% filler comment")
    head.append("\\RequirePackage{iftex}")
    head.append(guard)
    head.append("\\RequirePackage[T1]{fontenc}")
    head.append("\\newcommand*\\aaaidummy{keep me}")
    head.append("\\endinput\n")
    return "\n".join(head)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == _RULE_ID)


def _classify(head_text: str) -> tuple[str | None, str | None]:
    rep = parse_text(head_text + "\n")
    return _rs().taxonomy.classify(rep)


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_emergency_stop() -> None:
    """实证签名: file-line `Emergency stop` → emergency (emergency 族条)。"""
    cat, _ = _classify(_ERR_PDFTEX)
    assert cat == "emergency"


def test_taxonomy_emergency_stop_luatex() -> None:
    """同族臂: \\RequireLuaTeX 死法同归 emergency。"""
    cat, _ = _classify(_ERR_LUATEX)
    assert cat == "emergency"


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.99 → run_tool sh -c 闸行剥除。"""
    rule = _rule()
    assert rule.order == 11.99  # noqa: PLR2004 - schema 断言值
    assert rule.when == {"category": "emergency"}
    assert rule.condition["ctx_suggests"] == "\\\\Require(PDFTeX|LuaTeX|LuaMetaTeX)"
    assert rule.condition["source_contains"] == "\\\\Require(PDFTeX|LuaTeX|LuaMetaTeX)"
    assert {c.get("cache_dir_glob") for c in rule.condition["any"]} == {
        "*.sty",
        "*.cls",
    }
    assert rule.condition["tool_available"] == "sh"
    assert rule.action["kind"] == "run_tool"
    argv = rule.action["params"]["argv"]
    assert argv[:2] == ["sh", "-c"]
    script = argv[2]
    assert "texlate-fixloop-injected" in script  # 指纹幂等闸
    assert "\\Require(PDFTeX|LuaTeX|LuaMetaTeX)" in script  # 内容签名自证
    assert "*.sty *.cls" in script  # 双扩展扫描面


def test_rule_order_after_revtex_before_legacy_shim() -> None:
    """order 排序自洽: revtex_era_retire(11.98) < 本规则 < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in _rs().phase("loop")}
    assert orders["revtex_era_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_when_no_sty(tmp_path: Path) -> None:
    """wdir 无 .sty/.cls → cache_dir_glob any 闸拒。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_PDFTEX
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        _rule().condition, _rule(), ctx, None, None
    )
    assert not ok
    assert "any" in why


def test_cond_skip_when_ctx_unsigned(tmp_path: Path) -> None:
    """.sty 在场但错误无 guard cs 回显 → ctx_suggests 闸拒。"""
    (tmp_path / "aaai2027.sty").write_text(_guard_sty(14), encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = "./main.tex:10: Undefined control sequence.\nl.10 \\foo\n"
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_skip_when_source_lacks_guard(tmp_path: Path) -> None:
    """err ctx 回显 guard 但工程内无件载之 (系统 sty 死) → source_contains 闸拒。"""
    (tmp_path / "clean.sty").write_text(
        "\\ProvidesPackage{clean}\\newcommand*\\x{y}\n", encoding="utf-8"
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_PDFTEX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok
    assert "源码" in why


def test_cond_pass_on_signature(tmp_path: Path) -> None:
    """.sty + guard 回显 err blob + 源含 guard → 条件过。"""
    (tmp_path / "aaai2027.sty").write_text(_guard_sty(14), encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_PDFTEX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


# ---------------------------------------------------------------- 动作直驱 (真 sh)
@pytest.mark.parametrize("line", _GUARD_LINES)
def test_apply_strips_guard_each_variant(tmp_path: Path, line: int) -> None:
    """4 变体位逐一: guard 独占行删, iftex 载留, 尾注幂等标。"""
    src = _guard_sty(line)
    (tmp_path / "aaai2027.sty").write_text(src, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    patched = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert "\\RequirePDFTeX" not in patched
    assert "\\RequirePackage{iftex}" in patched  # iftex 载留无害
    assert "texlate-fixloop-injected" in patched
    assert "\\newcommand*\\aaaidummy{keep me}" in patched  # 其余逐字节保留
    # 逐字节差分: 恰删 1 行 + 尾注 1 行
    assert len(patched.splitlines()) == len(src.splitlines())


def test_apply_strips_luatex_guard(tmp_path: Path) -> None:
    """同族臂: \\RequireLuaTeX 独占行同剥。"""
    (tmp_path / "aaai2027.sty").write_text(
        _guard_sty(14, "\\RequireLuaTeX"), encoding="utf-8"
    )
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    patched = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert "\\RequireLuaTeX" not in patched
    assert "texlate-fixloop-injected" in patched


def test_apply_keeps_xetex_guard(tmp_path: Path) -> None:
    """剥面边界: \\RequireXeTeX 本机通过 —— 指纹不中, 文件逐字节不动。"""
    src = _guard_sty(14, "\\RequireXeTeX")
    (tmp_path / "conf.sty").write_text(src, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "conf.sty").read_text(encoding="utf-8") == src


def test_apply_guard_with_trailing_comment(tmp_path: Path) -> None:
    """闸行尾带 % 注释 (\\RequirePDFTeX % engine check) → 同剥。"""
    src = _guard_sty(14).replace(
        "\\RequirePDFTeX\n", "\\RequirePDFTeX % engine check\n"
    )
    (tmp_path / "aaai2027.sty").write_text(src, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    patched = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert "\\RequirePDFTeX" not in patched
    assert "texlate-fixloop-injected" in patched


def test_apply_skips_unsigned_sty(tmp_path: Path) -> None:
    """无签名件 → 脚本 continue, 文件逐字节不动。"""
    clean = "\\ProvidesPackage{foo}\\newcommand*\\foo{bar}\n\\endinput\n"
    (tmp_path / "foo.sty").write_text(clean, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note  # run_tool 恒 applied (rc=0 no-op)
    assert (tmp_path / "foo.sty").read_text(encoding="utf-8") == clean


def test_apply_skips_comment_only_guard(tmp_path: Path) -> None:
    """guard 仅活注释行 (% \\RequirePDFTeX) → 判无签名不补丁。"""
    comment_only = (
        "\\ProvidesPackage{foo}\n"
        "% \\RequirePackage{iftex}\n"
        "% \\RequirePDFTeX\n"
        "\\newcommand*\\foo{bar}\n"
        "\\endinput\n"
    )
    (tmp_path / "foo.sty").write_text(comment_only, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "foo.sty").read_text(encoding="utf-8") == comment_only


def test_apply_skips_inline_guard(tmp_path: Path) -> None:
    """known_gap: guard 行内嵌入 (多 cs 同行) → 指纹要求独占行, 不补丁。"""
    inline = (
        "\\ProvidesPackage{foo}\n"
        "\\RequirePackage{iftex}\n"
        "\\ifx\\foo\\undefined\\RequirePDFTeX\\fi\n"
        "\\newcommand*\\foo{bar}\n"
        "\\endinput\n"
    )
    (tmp_path / "foo.sty").write_text(inline, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "foo.sty").read_text(encoding="utf-8") == inline


def test_apply_idempotent_second_run(tmp_path: Path) -> None:
    """指纹闸: 二次 _apply 同件不再补丁 (防重投/重复删行)。"""
    (tmp_path / "aaai2027.sty").write_text(_guard_sty(14), encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok1, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok1
    once = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert once.count("texlate-fixloop-injected") == 1
    ok2, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok2
    assert (tmp_path / "aaai2027.sty").read_text(encoding="utf-8") == once


def test_apply_patches_signed_cls(tmp_path: Path) -> None:
    """.cls 臂: guard 在 cls 件 → 同获剥除。"""
    (tmp_path / "conf.cls").write_text(_guard_sty(14), encoding="utf-8")
    (tmp_path / "dummy.sty").write_text("\\ProvidesPackage{dummy}\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    patched = (tmp_path / "conf.cls").read_text(encoding="utf-8")
    assert "\\RequirePDFTeX" not in patched
    assert "texlate-fixloop-injected" in patched
    assert "texlate-fixloop-injected" not in (tmp_path / "dummy.sty").read_text(
        encoding="utf-8"
    )


def test_apply_noop_when_dir_empty(tmp_path: Path) -> None:
    """空 wdir → *.sty 字面量不命中, [ -f ] 兜住 → exit 0 no-op。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not _REAL_STY.is_file(), reason="soak 抽件不在本机 (gitignored)")
def test_apply_real_aaai2027_sty(tmp_path: Path) -> None:
    """真实件臂: soak-09-18 抽出 aaai2027.sty 剥后无 guard 行。"""
    real = _REAL_STY.read_text(encoding="utf-8")
    (tmp_path / "aaai2027.sty").write_text(real, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    patched = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert "\\RequirePDFTeX" not in patched
    assert "\\RequirePackage{iftex}" in patched
    assert "texlate-fixloop-injected" in patched
    # 逐字节差分: 恰删 1 guard 行 + 尾注 1 行
    assert len(patched.splitlines()) == len(real.splitlines())


# ---------------------------------------------------------------- e2e
class _MockRes:
    """impl CompRes duck-type 替身 (test_fixloop_draftsty 同款微缩)。"""

    def __init__(self, wdir: Path, spec: dict) -> None:
        self.log_path = wdir / "main.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        self.pdf = wdir / "main.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = False
        self.killed_signal = None
        self.seconds = 0.05
        self.stdout_tail = ""
        self.log_text = ""

    @property
    def has_pdf(self) -> bool:
        return self.pdf is not None and self.pdf_bytes > 0


class _MockEngine:
    """逐轮吐 spec。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr"})

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.rounds = 0

    def compile(self, wdir: Path, main: str, **_kw: object) -> _MockRes:
        del main
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return _MockRes(Path(wdir), self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _proj(tmp_path: Path, guard_line: int = 14) -> Path:
    (tmp_path / "main.tex").write_text(
        "\\documentclass[letterpaper]{article}\n\\usepackage[draft]{aaai2027}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "aaai2027.sty").write_text(_guard_sty(guard_line), encoding="utf-8")
    return tmp_path


def test_e2e_emergency_stripped_then_clean(tmp_path: Path) -> None:
    """整链: Emergency stop 首错 → 闸行剥除 → 下轮 clean。"""
    eng = _MockEngine(
        [
            {"log": _ERR_PDFTEX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    patched = (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
    assert "\\RequirePDFTeX" not in patched
    assert "texlate-fixloop-injected" in patched


def test_e2e_no_fire_on_unsigned_ctx(tmp_path: Path) -> None:
    """.sty 带 guard 但错误是别家签名 → ctx 闸拒, 不动文件。"""
    eng = _MockEngine(
        [
            {"log": "./main.tex:5: Undefined control sequence.\nl.5 \\foo\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert "\\RequirePDFTeX" in (tmp_path / "aaai2027.sty").read_text(encoding="utf-8")
