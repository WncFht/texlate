"""sabfix 双修单测 (sabdeg census 1107.0063 + 1107.0009)。

FIX A (1107.0063): ``_AUTOBIB_DISARM`` 双发射位 ``\\string@`` catcode 安全化 ——
doc ``\\MakeShortVerb{\\@}`` 把 @ 激活 (catcode 13) 时裸 @ token 在
``\\ifcsname``/``\\csname`` 名扫里被当 active cs 展开 → ``Missing \\endcsname
inserted`` (revtex ``\\bibliography`` → ``\\input`` 改写点实证)。``\\string``
直接取记号产 catcode-12 字面 @ → @=11/12/13 三态同名同读;
``normalize.use_bundled_bibliography`` 与 fixloop ``bbl_stub_rewrite``
两发射位必须字节同一 (单侧漂移即另一臂复毒)。

FIX B (1107.0009): ``mn2e_usegraphicx_defer`` —— 稿自带 mn2e.cls v2.2
``\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage[xetex]{graphicx}}``
(:52) 把 ``\\usepackage`` 写进 ``\\ds@`` 选项声明体 → ``\\ProcessOptions``
执行 → ``\\RequirePackage or \\LoadClass in Options Section`` 硬错 (嵌套
fontenc 载入归名 fontenc.sty:115, cat=options_section)。
``mnras_texmf_shadow_drop`` (11.91) ctx 同签但文件闸只认 mnras.cls →
本格 fired-unfixed。vendor/ 无 mn2e 补丁件可投 → 走原位补丁 (mnras #51
姊妹病同族, engine_guard_strip/abstract_edef 同形): regex_rewrite 把
``@usegraphicxtrue`` 后紧邻的内联 ``\\usepackage[...]{graphicx}`` 裹进
``\\AtEndOfClass{...}`` 推迟出类选项段 —— ds@ 体仍只置 flag, 包装载
出选项段后执行 (mn2e.cls 自身 ``\\if@usenatbib``→natbib :1201 同款
推迟惯用法), 驱动选项 ``[xetex]`` 原样保留。
"""

import re
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, fixloop, load_ruleset
from texlate.compile.fixloop._builtins_bib import (
    _AUTOBIB_DISARM as _DISARM_FIXLOOP,
)
from texlate.compile.fixloop._builtins_bib import bbl_stub_rewrite
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, parse_text
from texlate.compile.normalize import (
    _AUTOBIB_DISARM as _DISARM_NORM,
)
from texlate.compile.normalize import use_bundled_bibliography

_RULE_ID = "mn2e_usegraphicx_defer"

#: 修复形钉版: 名扫段 @ 全 ``\string@`` —— doc 激活 @ (1107.0063 ``\MakeShortVerb{\@}``)
#: 下裸 ``auto@bib`` 旧形在 ``\ifcsname`` 名扫里炸 ``Missing \endcsname``。
_DISARM_EXPECT = (
    r"\ifcsname auto\string@bib\endcsname"
    r"\expandafter\let\csname auto\string@bib\expandafter\endcsname"
    r"\csname \string@empty\endcsname\fi"
)

# 1107.0009 实证首错 (file-line-error 形态, cat=options_section):
# 嵌套 fontenc 载入归名 fontenc.sty —— 错件仍是稿自带 mn2e.cls:52。
_ERR_FONTENC = (
    "/work/1107.0009/splice/fontenc.sty:115: LaTeX Error: \\RequirePackage or "
    "\\LoadClass in Options Section.\n"
)
_ERR_FONTENC_CTX = (
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
    "Type  H <return>  for immediate help.\n"
    "l.72 \\ProcessOptions\n"
)
# '!' 形态同款: rep.first 无文件名, "Options Section" 字面同闸收
_BANG_ERR = "! LaTeX Error: \\RequirePackage or \\LoadClass in Options Section.\n"
# mn2e.cls 点名归名变体 (ctx_suggests 第二备选 mn2e\.cls 亦收)
_ERR_MN2E_ATTR = (
    "./mn2e.cls:52: LaTeX Error: \\RequirePackage or \\LoadClass in Options Section.\n"
)
# 签名散格变体: 同文件 Missing number (syntax) —— 错面同闸收
_ERR_MISSINGNUM = "./mn2e.cls:114: Missing number, treated as zero.\n"

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"

# 稿自带 mn2e.cls v2.2 (2001/02/06) 实证病形: :52 ds@usegraphicx 行内联
# \usepackage[xetex]{graphicx} —— \ProcessOptions 执行 → Options Section。
_MN2E_BUGGY = (
    "% mn2e.cls v2.2 excerpt (1107.0009 shipped)\n"
    "\\newif\\if@usegraphicx\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage[xetex]{graphicx}}\n"
    "\\ProcessOptions\n"
)
# 补丁后期望行: 内联 \usepackage 裹进 \AtEndOfClass, 驱动选项原样保留, 尾挂注入标
_MN2E_PATCHED_LINE = (
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\AtEndOfClass{"
    "\\usepackage[xetex]{graphicx}}} % texlate-fixloop-injected: "
    "ds@usegraphicx deferred past ProcessOptions"
)
# 无选项 / RequirePackage 变体病形 (pattern 的 [..] 可选组与双命令名都盖)
_MN2E_BUGGY_NOOPT = "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}\n"
_MN2E_BUGGY_REQPKG = (
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\RequirePackage{graphicx}}\n"
)
# vendor shim mn2e.cls 形: \\mn@graphicx 旗 —— 无 \\@usegraphicxtrue → 指纹阴性
_MN2E_SHIM = (
    "% texlate mn2e shim bridge\n"
    "\\newif\\ifmn@graphicx\n"
    "\\DeclareOption{usegraphicx}{\\mn@graphicxtrue}\n"
    "\\ProcessOptions\n"
    "\\ifmn@graphicx\\RequirePackage{graphicx}\\fi\n"
)
# 补丁 mnras.cls 形: ds@ 行净 (\\@usegraphicxtrue 后紧邻 }) → 指纹阴性
_MNRAS_PATCHED = (
    "% texlate patch: \\usepackage deferred past \\ProcessOptions\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue}\n"
    "\\if@usegraphicx\n  \\usepackage{graphicx}\n\\fi\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == _RULE_ID)


def _classify(head_text: str) -> tuple[str | None, str | None]:
    rep = parse_text(head_text + "\n")
    return _rs().taxonomy.classify(rep)


def _doc(docclass: str = "revtex4-1") -> str:
    return (
        f"\\documentclass{{{docclass}}}\n\\begin{{document}}\nx\n"
        "\\bibliography{refs}\n\\end{document}"
    )


def _bbl(tmp_path: Path, stem: str = "main") -> None:
    (tmp_path / f"{stem}.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )


def _plant_mn2e(wdir: Path, body: str = _MN2E_BUGGY) -> Path:
    """稿自带布局落件: ``wdir/mn2e.cls`` (cwd 序现胜者)。"""
    f = wdir / "mn2e.cls"
    f.write_text(body, encoding="utf-8")
    return f


# ---------------------------------------------------------------- FIX A: \\string@ 发射
def test_disarm_sites_byte_identical() -> None:
    """normalize 与 fixloop 双发射位字节同一 —— 单侧漂移即另一臂复毒。"""
    assert _DISARM_NORM == _DISARM_FIXLOOP


def test_disarm_pinned_string_escape_literal() -> None:
    """钉版修复形全文: 三处名扫 @ 皆 ``\\string@`` 转义, 其余字节不动。"""
    assert _DISARM_NORM == _DISARM_EXPECT


def test_disarm_no_bare_at_in_name_scans() -> None:
    """发射体内零裸 @: 每个 @ token 必须由 ``\\string`` 直取 (doc @=13 不炸)。"""
    assert _DISARM_NORM.count("@") == 3  # noqa: PLR2004 - auto@bib ×2 + @empty ×1
    assert "auto@bib" not in _DISARM_NORM
    assert " @empty" not in _DISARM_NORM
    assert not re.findall(r"(?<!\\string)@", _DISARM_NORM)


def test_use_bundled_bibliography_emits_string_guard(tmp_path: Path) -> None:
    """normalize 臂: ``\\bibliography`` 改写 → disarm 行紧贴 ``\\input`` 之前。"""
    main = tmp_path / "main.tex"
    main.write_text(_doc("revtex4-1"))
    _bbl(tmp_path)
    out = use_bundled_bibliography(main.read_text(), main)
    assert f"{_DISARM_EXPECT}\n\\input{{main.bbl}}" in out
    assert "\\bibliography" not in out
    assert "auto@bib" not in out


def test_bbl_stub_rewrite_emits_string_guard(tmp_path: Path) -> None:
    """fixloop 臂: ``bbl_stub_rewrite`` 改写补同款 ``\\string@`` disarm。"""
    (tmp_path / "main.tex").write_text(_doc())
    _bbl(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, _note = bbl_stub_rewrite(ctx, None, None, {})
    assert ok
    out = (tmp_path / "main.tex").read_text()
    assert f"{_DISARM_EXPECT}\n\\input{{main.bbl}}" in out
    assert "auto@bib" not in out


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_fontenc_attr_is_options_section() -> None:
    """实证签名: fontenc.sty:115 归名 Options Section → options_section。"""
    cat, _ = _classify(_ERR_FONTENC + _ERR_FONTENC_CTX)
    assert cat == "options_section"


def test_taxonomy_mn2e_attr_is_options_section() -> None:
    """mn2e.cls 点名归名变体同归 options_section (taxrow 只认错误文本)。"""
    cat, _ = _classify(_ERR_MN2E_ATTR + _ERR_FONTENC_CTX)
    assert cat == "options_section"


def test_taxonomy_missing_number_is_syntax() -> None:
    """同文件 Missing number 变体 → syntax (签名散格同闸收)。"""
    cat, _ = _classify(_ERR_MISSINGNUM)
    assert cat == "syntax"


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.905 → regex_rewrite .cls 原位补丁 + 注入标。"""
    rule = _rule()
    assert rule.order == 11.905  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"syntax", "undefined_cs", "other", "options_section"}
    assert "Options Section" in rule.condition["ctx_suggests"]
    assert "mn2e" in rule.condition["ctx_suggests"]
    assert rule.condition["cache_dir_glob"] == "**/mn2e.cls"
    assert "@usegraphicxtrue" in rule.condition["source_contains"]
    assert rule.action["kind"] == "regex_rewrite"
    params = rule.action["params"]
    assert params["exts"] == [".cls"]
    rw = params["rewrites"][0]
    assert "ds@usegraphicx" in rw["pattern"]
    assert "usepackage|RequirePackage" in rw["pattern"]
    assert "graphicx" in rw["pattern"]
    assert "\\AtEndOfClass" in rw["repl"]
    assert "texlate-fixloop-injected" in rw["repl"]  # mnras 闸文件级标检跳过


def test_rule_order_neighbors() -> None:
    """order 排序自洽: pstricks(11.9) < 本规则 < mnras(11.91) < abstract_edef(11.95)。

    mn2e-shipped 格先修真病件, 不白烧 mnras 投递轮; 无 mn2e.cls 格 glob
    cond-skip 同轮落 mnras 面零成本。
    """
    orders = {r.id: r.order for r in _rs().phase("loop")}
    assert orders["pstricks_add_pair_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["mnras_texmf_shadow_drop"]
    assert (
        orders["mnras_texmf_shadow_drop"] < orders["abstract_edef_capture_neutralize"]
    )


# ---------------------------------------------------------------- condition 闸
def test_cond_pass_shipped_buggy_fontenc_err(tmp_path: Path) -> None:
    """实证形: 稿自带病件在场 + fontenc 归名 Options Section 签名 → 闸过。"""
    _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_FONTENC + _ERR_FONTENC_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_bang_form(tmp_path: Path) -> None:
    """'!' 形态: 文件名缺席但 "Options Section" 字面在 rep.first → 同闸收。"""
    _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _BANG_ERR + _ERR_FONTENC_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_mn2e_attr_form(tmp_path: Path) -> None:
    """mn2e.cls 点名归名变体 → ctx_suggests 第二备选收 (双签名通道)。"""
    _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_MN2E_ATTR + _ERR_FONTENC_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_skip_when_error_elsewhere(tmp_path: Path) -> None:
    """错误不点名 mn2e.cls/Options Section (别包错) → ctx_suggests 闸拒。"""
    _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = "./main.tex:10: Undefined control sequence.\nl.10 \\foo\n"
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_skip_when_mn2e_absent(tmp_path: Path) -> None:
    """wdir 无 mn2e.cls → cache_dir_glob 闸拒 (同轮落 mnras 面零成本)。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_FONTENC + _ERR_FONTENC_CTX
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_skip_when_shim_shape(tmp_path: Path) -> None:
    """vendor shim mn2e.cls (\\mn@graphicx 旗, 无 \\@usegraphicxtrue) → 指纹阴性拒。"""
    _plant_mn2e(tmp_path, _MN2E_SHIM)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_FONTENC + _ERR_FONTENC_CTX
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_skip_when_mnras_patched_shape(tmp_path: Path) -> None:
    """补丁 mnras.cls 同指纹形 (ds@ 行净): \\@usegraphicxtrue 紧邻 } → 阴性拒。"""
    _plant_mn2e(tmp_path, _MNRAS_PATCHED)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_FONTENC + _ERR_FONTENC_CTX
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


# ---------------------------------------------------------------- 动作直驱
def test_apply_patches_buggy_in_place(tmp_path: Path) -> None:
    """病件原位补丁: 内联 \\usepackage 裹 \\AtEndOfClass + 注入标, 其余字节不动。"""
    cls = _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    out = cls.read_text(encoding="utf-8")
    assert _MN2E_PATCHED_LINE in out
    assert out.replace(_MN2E_PATCHED_LINE, "") == _MN2E_BUGGY.replace(
        "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage[xetex]{graphicx}}",
        "",
    )


def test_apply_preserves_driver_option(tmp_path: Path) -> None:
    """``[xetex]`` 驱动选项原样保留进 \\AtEndOfClass 参数 (verbatim 搬运)。"""
    cls = _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok
    out = cls.read_text(encoding="utf-8")
    assert "\\AtEndOfClass{\\usepackage[xetex]{graphicx}}" in out


def test_apply_noopt_and_reqpkg_variants(tmp_path: Path) -> None:
    """无选项 ``\\usepackage{graphicx}`` 与 ``\\RequirePackage`` 变体同裹。"""
    cls = _plant_mn2e(tmp_path, _MN2E_BUGGY_NOOPT + _MN2E_BUGGY_REQPKG)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok
    out = cls.read_text(encoding="utf-8")
    assert "\\AtEndOfClass{\\usepackage{graphicx}}" in out
    assert "\\AtEndOfClass{\\RequirePackage{graphicx}}" in out


def test_apply_declines_shim_shape(tmp_path: Path) -> None:
    """shim 件 (无 \\@usegraphicxtrue\\usepackage 紧邻指纹) → 零改写 decline。"""
    cls = _plant_mn2e(tmp_path, _MN2E_SHIM)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert not ok
    assert cls.read_text(encoding="utf-8") == _MN2E_SHIM


def test_apply_idempotent_second_run(tmp_path: Path) -> None:
    """二跑幂等: 补丁后紧邻指纹消失 → decline, 文件不再变。"""
    cls = _plant_mn2e(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok1, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    once = cls.read_text(encoding="utf-8")
    ok2, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok1
    assert not ok2
    assert cls.read_text(encoding="utf-8") == once


def test_apply_cls_scope_only(tmp_path: Path) -> None:
    """exts=[.cls] 域闸: 病形在 .tex 里不改写 (mn2e.cls shim 占位供 glob)。"""
    tex = tmp_path / "main.tex"
    tex.write_text(_MN2E_BUGGY, encoding="utf-8")
    _plant_mn2e(tmp_path, _MN2E_SHIM)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert not ok
    assert tex.read_text(encoding="utf-8") == _MN2E_BUGGY


# ---------------------------------------------------------------- e2e
class _MockRes:
    """impl CompRes duck-type 替身 (test_fixloop_mnrasretire 同款微缩)。"""

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
    """逐轮吐 spec; probe_file 只认 cwd 在场件 (稿自带 mn2e.cls 直达)。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(self, script: list, *, available: set[str] | None = None) -> None:
        self.script = list(script)
        self.available = available or set()
        self.rounds = 0

    def compile(self, wdir: Path, main: str, **_kw: object) -> _MockRes:
        del main  # mock 按轮吐 spec, 不编译真文件
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return _MockRes(Path(wdir), self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        return f"/texmf/{fname}" if fname in self.available else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _proj(tmp_path: Path, body: str = _MN2E_BUGGY) -> Path:
    """1107.0009 稿自带布局: wdir 根 main.tex + 病件 mn2e.cls。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[useAMS,usenatbib,usegraphicx]{mn2e}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    _plant_mn2e(tmp_path, body)
    return tmp_path


def _null_runner(
    argv: list[str], timeout: int, wdir: Path
) -> tuple[int, str, float, bool]:
    """regex_rewrite 不走 runner —— 拒答替身反证动作不依赖外部工具。"""
    del argv, timeout, wdir
    return 127, "runner should not be invoked", 0.0, False


def test_e2e_patch_flips_cell_clean(tmp_path: Path) -> None:
    """整链: Options Section → 原位补丁 → clean; 病件带注入标, 驱动选项存。"""
    eng = _MockEngine(
        [
            {"log": _ERR_FONTENC + _ERR_FONTENC_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_null_runner)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    out = (tmp_path / "mn2e.cls").read_text(encoding="utf-8")
    assert _MN2E_PATCHED_LINE in out
    assert "\\AtEndOfClass{\\usepackage[xetex]{graphicx}}" in out


def test_e2e_no_fire_on_other_error(tmp_path: Path) -> None:
    """非本签名: 别包错 → 本规则不动件 (mn2e.cls 原样)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\foo\n\\end{document}\n",
        encoding="utf-8",
    )
    cls = _plant_mn2e(tmp_path)
    eng = _MockEngine(
        [
            {"log": "./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng, runner=_null_runner)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert cls.read_text(encoding="utf-8") == _MN2E_BUGGY


def test_e2e_shim_mn2e_untouched(tmp_path: Path) -> None:
    """shim 形 mn2e.cls + Options Section 签名: 指纹阴性 → 零改写, 格照走。"""
    eng = _MockEngine(
        [
            {"log": _ERR_FONTENC + _ERR_FONTENC_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path, _MN2E_SHIM), eng, runner=_null_runner)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert (tmp_path / "mn2e.cls").read_text(encoding="utf-8") == _MN2E_SHIM
