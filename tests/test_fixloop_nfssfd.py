r"""nfssfd 车道 (2026-09-19): NFSS ``.fd`` 缺档硬错 taxonomy + install 通路钉。

格面: stagerun-loop2 普查 8 cells (7× ``No file LGRcmr.fd.`` + 1×
``No file OT2lmr.fd.``)——``babel_lang_ldf_install`` 落 ``lgrenc.def``
后 LGR 编码激活, 内核 ``\try@load@fontshape`` 小写/原名双探 .fd 皆空
→ ``\@input@`` ``\typeout`` 裸行 ``No file X.fd.`` 先于错误行 ~2 行
落 log (ctx8 前向窗够不着), 旧恒归 ``other|None`` 无路由。

机制三件:
  - ``ErrReport.pre`` (首错前 4 行, logparse ``_PRE_LINES``) + taxonomy
    ``use_pre: true`` 条目——``pre + head`` 拼接 blob 检索仅本条目,
    其余条目 head-only 不变 (pre 行内宽词不扰既有评估序);
  - 签双约束: ``^No file`` 行首锚 (排 ``LaTeX Font Info:    No file
    X.fd.`` 行内良性替换 info 形) + ``NFSS system isn't set up
    properly`` 同窗 (排可恢复 .fd 缺档);
  - ``_apply_install_file`` .fd 小写变体候选——内核探测序小写先原名
    后; filemap ``lgrcmr.fd``→cbfonts-fd, 混档 ``OT1Tempora-TLF.fd``
    →tempora 原名才中, 双形互补全收。
消费规则 = 既有 ``install_file`` (missing_file|payload_required)——
无新规则 id。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _classify(text: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _rs().warn_patterns))


class _Eng:
    """最小引擎替身 (probe/filemap 恒 miss——decline 面直驱)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


class _EngInstall(_Eng):
    """_Eng + install_file: installable 集合内名落 fake texmf, probe 复核命中。"""

    def __init__(self, texmf: Path, installable: set[str]) -> None:
        self.texmf = texmf
        self.texmf.mkdir(parents=True, exist_ok=True)
        self.installable = set(installable)
        self.install_calls: list[str] = []
        self.font_related_calls: list[bool] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        hit = self.texmf / fname
        return str(hit) if hit.is_file() else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        self.install_calls.append(fname)
        self.font_related_calls.append(font_related)
        if fname not in self.installable:
            return False
        (self.texmf / fname).write_text("", encoding="utf-8")
        return True

    def rebuild_fontmaps(self) -> bool:
        return True


def _apply(
    rule: Rule, tmp_path: Path, pay: str, eng: _Eng | None = None
) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        rule, _ctx(tmp_path), eng or _Eng(), pay, ErrReport()
    )


# ──────────────────────────── taxonomy: No file X.fd ────────────────────────────
_NFSS_TAIL = (
    "\n\nSee the LaTeX manual or LaTeX Companion for explanation.\n"
    "Type  H <return>  for immediate help.\n ...\n"
    "l.340 \\begin{document}\n"
)


def test_taxonomy_nfss_fd_fileline_signature() -> None:
    """真实 log 解剖 (2410.00035): file-line 形 NFSS 硬错 → missing_file|fd。"""
    log = (
        "LaTeX Font Info:    Trying to load font information for LGR+cmr"
        " on input line 340.\n\n"
        "No file LGRcmr.fd.\n\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    assert _classify(log) == ("missing_file", "LGRcmr.fd")


def test_taxonomy_nfss_fd_bang_signature() -> None:
    """'!' 前缀形同样命中 (pdftex 无 -file-line-error 通路); 他族名也收。"""
    log = (
        "LaTeX Font Info:    Trying to load font information for OT2+lmr"
        " on input line 467.\n\n"
        "No file OT2lmr.fd.\n\n"
        "! LaTeX Error: This NFSS system isn't set up properly." + _NFSS_TAIL
    )
    assert _classify(log) == ("missing_file", "OT2lmr.fd")


def test_taxonomy_font_info_inline_no_file_rejected() -> None:
    """``LaTeX Font Info:    No file X.fd.`` 行内形态不命中 ``^No file`` 锚。

    内核字体替换成功时同样印 ``No file`` 字样但带 Font Info 前缀——
    良性 info, 非缺档硬错; NFSS 错行本体签 → taxrow 归 nfss_setup
    (无消费臂, 路由语义同原 other 兜底)。
    """
    log = (
        "LaTeX Font Info:    No file LGRcmr.fd.\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    assert _classify(log) == ("nfss_setup", None)


def test_taxonomy_no_file_fd_without_nfss_not_matched() -> None:
    """裸 ``No file X.fd.`` 但无 NFSS 硬错同窗 → 不抢后续真实错误路由。

    可恢复 .fd 缺档 (substitution 成功) 与无关首错共存时, NFSS 共现
    约束把本签关在窗外——错误行本体签名正常评估。
    """
    log = "No file LGRcmr.fd.\n! Undefined control sequence.\nl.5 \\foo\n"
    assert _classify(log) == ("undefined_cs", "foo")


def test_taxonomy_no_file_nonfd_rejected() -> None:
    """``No file X.bbl/toc/aux`` 等非 .fd 探测行不收——payload 限定 .fd。"""
    log = (
        "No file main.toc.\n\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    assert _classify(log) == ("nfss_setup", None)  # NFSS 头签 → nfss_setup taxrow


def test_taxonomy_no_file_fd_outside_pre_window() -> None:
    """``No file`` 距首错 >_PRE_LINES(4) 行 → 窗外不命中, NFSS 头签归 nfss_setup。"""
    filler = "\n".join(
        f"LaTeX Font Info:    Trying to load font information for LGR+f{i}"
        " on input line 340."
        for i in range(6)
    )
    log = (
        "No file LGRcmr.fd.\n" + filler + "\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    assert _classify(log) == ("nfss_setup", None)


def test_taxonomy_existing_missing_file_signatures_intact() -> None:
    """前三条 missing_file 签保持先序——反引号/not-found 形不被新签抢。"""
    assert _classify("! LaTeX Error: File `foo.sty' not found.\nl.3 \\usepackage") == (
        "missing_file",
        "foo.sty",
    )
    assert _classify("! I can't find file `bar'.\nl.7 \\input{bar}") == (
        "missing_file",
        "bar",
    )


# ─────────────────── errs 边界: 次级错误面无 pre (forward-only) ───────────────────
def test_errs_secondary_nfss_boundary() -> None:
    """``rep.errs`` 逐条分类不携 pre——远端次级 NFSS 错行归 nfss_setup (已知边界)。

    首错 ctx8 窗够不到远处 No-file+NFSS 对时, 次级 NFSS 错行保持未覆盖;
    首错本身是 NFSS 形 (或 ctx8 内含该对) 才经 ``ErrReport.pre``/blob
    路由。两错间距 >CTX_LINES 保证对不出现在首错 ctx 内。
    """
    filler = "\n".join(f"[{i}]" for i in range(10))
    log = (
        "! Undefined control sequence.\n"
        "l.5 \\foo\n" + filler + "\n"
        "No file LGRcmr.fd.\n\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    rep = parse_text(log, _rs().warn_patterns)
    assert _rs().taxonomy.classify(rep) == ("undefined_cs", "foo")
    cands = _rs().taxonomy.err_candidates(rep)
    nfss = [c for c in cands if "NFSS" in c[2]]
    assert nfss
    assert all(cat == "nfss_setup" for cat, _pay, _l, _b in nfss)


def test_errs_ctx8_pair_routes_missing_file() -> None:
    """No-file+NFSS 对落在首错 ctx8 内 → missing_file|fd (head-blob 原语义)。

    评估域恒为 first+ctx8——对内签名在窗内即达, 与 ``use_pre`` 无关;
    条目序让 missing_file 先于 undefined_cs 命中, 装档后下一轮处理
    undefined_cs (双错皆可修, 路由序不丢修)。
    """
    log = (
        "! Undefined control sequence.\n"
        "l.5 \\foo\n"
        "No file LGRcmr.fd.\n\n"
        "./main.tex:340: LaTeX Error: This NFSS system isn't set up properly."
        + _NFSS_TAIL
    )
    rep = parse_text(log, _rs().warn_patterns)
    assert _rs().taxonomy.classify(rep) == ("missing_file", "LGRcmr.fd")


# ─────────────────── install_file: when 派发 + .fd 候选桥 ───────────────────
def test_install_file_when_dispatch() -> None:
    """missing_file|<name>.fd 满足 install_file when (category+payload_required)。"""
    rule = _rule("install_file")
    ctx = _ctx(Path("/nonexistent"))
    assert actions._when_ok(  # noqa: SLF001 - when 原语直驱
        rule.when, "missing_file", "LGRcmr.fd", ctx
    )
    # payload_required: 无 payload 的 missing_file 不点火
    assert not actions._when_ok(  # noqa: SLF001
        rule.when, "missing_file", None, ctx
    )


def test_install_fd_lowercase_candidate_first(tmp_path: Path) -> None:
    """内核探测序桥: payload ``LGRcmr.fd`` → 先试小写 ``lgrcmr.fd`` 命中。

    filemap/kpsewhich 大小写敏感——实档键 ``lgrcmr.fd``→cbfonts-fd;
    原名 ``LGRcmr.fd`` 无键。小写候选排前 = 内核 ``\\lowercase`` 先探同序。
    """
    eng = _EngInstall(tmp_path / "texmf", {"lgrcmr.fd"})
    ok, note = _apply(_rule("install_file"), tmp_path, "LGRcmr.fd", eng)
    assert ok, note
    assert eng.install_calls == ["lgrcmr.fd"]
    assert eng.font_related_calls == [True]  # .fd ∈ font_related_exts
    assert "lgrcmr.fd" in note


def test_install_fd_verbatim_mixed_case_fallback(tmp_path: Path) -> None:
    """混档名 (``OT1Tempora-TLF.fd``→tempora) 小写 miss 后原名收。"""
    eng = _EngInstall(tmp_path / "texmf", {"OT1Tempora-TLF.fd"})
    ok, note = _apply(_rule("install_file"), tmp_path, "OT1Tempora-TLF.fd", eng)
    assert ok, note
    assert eng.install_calls == ["ot1tempora-tlf.fd", "OT1Tempora-TLF.fd"]
    assert "OT1Tempora-TLF.fd" in note


def test_install_fd_unpackaged_decline(tmp_path: Path) -> None:
    """OT2lmr.fd 双形皆无包 → 全候选 miss → decline + advisory 留档。"""
    ctx = _ctx(tmp_path)
    eng = _EngInstall(tmp_path / "texmf", set())
    ok, note = actions._apply(  # noqa: SLF001
        _rule("install_file"), ctx, eng, "OT2lmr.fd", ErrReport()
    )
    assert not ok
    assert "OT2lmr.fd" in note
    assert eng.install_calls == ["ot2lmr.fd", "OT2lmr.fd"]
    assert any("no package provides" in a for a in ctx.advisories)


def test_install_fd_already_present_lowercase(tmp_path: Path) -> None:
    """磁盘已有小写实档 (工程/texmf) → already-present 短路, 不重安装。"""
    (tmp_path / "lgrcmr.fd").write_text("", encoding="utf-8")
    eng = _EngInstall(tmp_path / "texmf", set())
    ok, note = _apply(_rule("install_file"), tmp_path, "LGRcmr.fd", eng)
    assert ok
    assert "already-present" in note
    assert eng.install_calls == []  # probe 先中, 零安装调用
