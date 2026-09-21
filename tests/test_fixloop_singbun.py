r"""singbun lane (2026-09-20): failmine6+gapmine 八格 singles bundle 修复面钉。

每格 diagnose 自 verbatim 签名, 钉 classify → when+condition 派发 →
apply → decline/幂等 四层 (aux_eof 同口径)。格↔臂映射:

- 0812.1022 ``Extra }, or forgotten \endgroup`` ×99: emulateapj.cls 陈旧
  ``\LT@endpbox`` 缺 ``\color@endgroup`` → ``lt_endpbox_color_fix``
  (75-syntax 199.77, exts [.cls,.sty])。
- 2602.09664 ``Argument of \@citex has an extra }``: cite+natbib 并载
  arity 冲突 → ``cite_natbib_clash_retire`` (70-pkgopt 203) cite 装载行
  注释中和。
- 2609.19872 ``Missing { inserted``/``\__um_group_begin:``: um 下
  ``^\mathcal{P}`` 裸 field → ``um_script_alphabet_brace``
  (95-targeted 191.6) 组化。
- astro-ph/0605352 ``Misplaced \noalign``/``\crcr``: 行间 ``\input``
  (\protect 化不可展) 毒化扫描 → ``input_noalign_primitive``
  (75-syntax 199.75) ``\csname @@input\endcsname`` 可展化。
- 2505.08102 ``Missing delimiter (. inserted)``: zh 全角 （） 泄入
  ``\big`` 族操作位 → ``big_fullwidth_delim_fix`` (75-syntax 199.76)。
- 2512.05247 ``Package svg Error: File `X.svg' is missing``: taxonomy
  新 missing_graphic 行 (10-taxonomy ~423, .svg 后缀锚定) +
  ``svg_missing_demote`` (45-graphics 17.65) → 次轮 placeholder 补桩。
- 2606.18573 ``File ended while scanning use of \redactcite``: zh 吞
  外层 ``}`` → ``redactcite_brace_close`` (75-syntax 199.78) doc 级修;
  指派表 ``aux_purge_regen`` (b) 臂表列名已补 ``redactcite``
  (65-encoding:92) —— 实机非 aux 回读, 健康 aux 上 builtin decline
  钉死 (真修归 doc 级臂)。
- 0712.0823 ``File `mncite.sty' not found``: 全位缺席 →
  ``mncite_absent_retire`` (70-pkgopt 202) 装载行注释中和。
"""

from pathlib import Path

from _fixloopkit import apply, mk_ctx, rs, when_cond_ok

from texlate.compile.logparse import parse_text


def _write(tmp_path: Path, body: str, name: str = "main.tex") -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


def _apply(rid: str, tmp_path: Path, pay: str | None = None) -> tuple[bool, str]:
    """action 直驱 (when/cond 由 when_cond_ok 钉)。"""
    return apply(rid, mk_ctx(tmp_path), pay)


# ════════════════════════════════════════════════════════════════
# 2512.05247: ``Package svg Error: File `X.svg' is missing`` ——
# taxonomy missing_graphic 行 + svg_missing_demote → placeholder 链
# ════════════════════════════════════════════════════════════════

_SVG_LOG = (
    "main.tex:579: Package svg Error: File `modified-recoverability.svg'"
    " is missing.\nl.579 \\end{figure}\n"
)


def test_svg_missing_classifies_graphic_with_payload() -> None:
    """svg 包 ``is missing`` 措辞 → missing_graphic|.svg 名 (新 taxonomy 行)。"""
    rep = parse_text(_SVG_LOG)
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("missing_graphic", "modified-recoverability.svg")


def test_svg_tex_pdf_intermediate_not_graphic() -> None:
    """``*_svg-tex.pdf`` 包自产中间件缺席不抢 —— 行 pattern 限 .svg 后缀。

    svg_prepare (45-graphics:9) 固有域; 现状该签名落 syntax catchall,
    唯不变量 = 不派 missing_graphic (否则 demote 臂会把转换中间件
    当源件降级)。
    """
    rep = parse_text(
        "main.tex:579: Package svg Error: File `x_svg-tex.pdf' is missing.\nl.1 x\n"
    )
    cat, _ = rs().taxonomy.classify(rep)
    assert cat != "missing_graphic"


def test_svg_demote_dispatch_apply(tmp_path: Path) -> None:
    """\\includesvg[opts]{X.svg} → \\includegraphics[opts]{X.pdf}。"""
    head = parse_text(_SVG_LOG).first or ""
    _write(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{svg}\n\\begin{document}\n"
        "\\includesvg[width=\\textwidth]{modified-recoverability.svg}\n"
        "\\includesvg{fig2.svg}\n\\end{document}\n",
    )
    assert when_cond_ok(
        "svg_missing_demote",
        "missing_graphic",
        "modified-recoverability.svg",
        head,
        tmp_path,
    )
    ok, note = _apply("svg_missing_demote", tmp_path, "modified-recoverability.svg")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\includegraphics[width=\\textwidth]{modified-recoverability.pdf}" in t
    assert "\\includegraphics{fig2.pdf}" in t
    assert "\\includesvg" not in t


def test_svg_demote_declines_no_includesvg(tmp_path: Path) -> None:
    """无 \\includesvg 站 → source_contains 闸拒 + apply 空转。"""
    head = parse_text(_SVG_LOG).first or ""
    _write(tmp_path, "\\documentclass{article}\n\\begin{document}x\\end{document}\n")
    assert not when_cond_ok(
        "svg_missing_demote", "missing_graphic", "x.svg", head, tmp_path
    )
    ok, _ = _apply("svg_missing_demote", tmp_path, "x.svg")
    assert not ok


def test_svg_demote_idempotent(tmp_path: Path) -> None:
    """降级稿无 \\includesvg → 重放 decline (与 dedup 双保险)。"""
    _write(tmp_path, "\\includesvg{a.svg}\n")
    ok, _ = _apply("svg_missing_demote", tmp_path, "a.svg")
    assert ok
    ok, _ = _apply("svg_missing_demote", tmp_path, "a.svg")
    assert not ok
    assert "\\includegraphics{a.pdf}" in (tmp_path / "main.tex").read_text()


def test_svg_demoted_ref_next_round_reaches_placeholder(tmp_path: Path) -> None:
    """降级后次轮 xetex ``Unable to load picture or PDF file 'X.pdf'`` →
    missing_graphic|X.pdf → graphic_missing_placeholder when+cond 均过
    (源侧枚举补桩链路就位, 同格缺 png 一并收)。"""
    rep = parse_text(
        "main.tex:10: Unable to load picture or PDF file 'modified-recoverability.pdf'\n"
        "l.10 x\n"
    )
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("missing_graphic", "modified-recoverability.pdf")
    head = (rep.first or "") + "\n" + (rep.ctx or "")
    assert when_cond_ok("graphic_missing_placeholder", cat, pay, head, tmp_path)


# ════════════════════════════════════════════════════════════════
# 0712.0823: mncite.sty 全位缺席 → 装载行注释中和
# ════════════════════════════════════════════════════════════════

_MNCITE_HEAD = "! LaTeX Error: File `mncite.sty' not found.\nl.164 \\usepackage{mncite}"


def test_mncite_classifies_missing_file() -> None:
    rep = parse_text(_MNCITE_HEAD)
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("missing_file", "mncite.sty")


def test_mncite_retire_dispatch_apply(tmp_path: Path) -> None:
    """mn2e→mnras 链 natbib 已担 \\citep/\\citet —— 装载行 ``%`` 中和。"""
    _write(
        tmp_path,
        "\\documentclass[useAMS,usenatbib]{mn2e}\n\\usepackage{mncite}\n"
        "\\begin{document}\n\\citep{a}\n\\end{document}\n",
    )
    assert when_cond_ok(
        "mncite_absent_retire", "missing_file", "mncite.sty", _MNCITE_HEAD, tmp_path
    )
    ok, note = _apply("mncite_absent_retire", tmp_path, "mncite.sty")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "%\\usepackage{mncite}" in t
    assert "%%" not in t


def test_mncite_retire_declines_other_missing(tmp_path: Path) -> None:
    """ctx 无 mncite.sty 签名 → cond 拒 (其他 missing_file 不抢)。"""
    _write(tmp_path, "\\usepackage{mncite}\n")
    head = "! LaTeX Error: File `foo.sty' not found.\nl.1 x"
    assert not when_cond_ok(
        "mncite_absent_retire", "missing_file", "foo.sty", head, tmp_path
    )


def test_mncite_retire_masked_idempotent(tmp_path: Path) -> None:
    """已注释装载行 masked 面不可见 → apply decline 原文不动 (天然幂等)。

    source_contains 非遮盖面仍见 ``mncite`` 字面 → cond 过, 权威在
    masked apply。
    """
    src = (
        "\\documentclass{mn2e}\n%\\usepackage{mncite}\n"
        "\\begin{document}x\\end{document}\n"
    )
    _write(tmp_path, src)
    assert when_cond_ok(
        "mncite_absent_retire", "missing_file", "mncite.sty", _MNCITE_HEAD, tmp_path
    )
    ok, _ = _apply("mncite_absent_retire", tmp_path, "mncite.sty")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_mncite_group_load_out_of_scope(tmp_path: Path) -> None:
    """组载 {mncite,other} 形不收 (known_gap) —— apply 空转原文不动。"""
    src = "\\usepackage{mncite,url}\n"
    _write(tmp_path, src)
    ok, _ = _apply("mncite_absent_retire", tmp_path, "mncite.sty")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


# ════════════════════════════════════════════════════════════════
# 2602.09664: cite.sty+natbib 并载 \@citex arity 冲突 → cite 退役
# ════════════════════════════════════════════════════════════════

_CITEX_HEAD = "draft_bos.tex:380: Argument of \\@citex has an extra }.\nl.380 \\cite{x}"

_CITE_DOC = (
    "\\documentclass{article}\n"
    "\\usepackage[numbers,sort&compress]{natbib}\n"
    "\\ifx\\pdfoutput\\undefined\n\\usepackage{cite}\n\\else\n\\fi\n"
    "\\begin{document}\n\\cite{a}\n\\end{document}\n"
)


def test_citex_clash_classifies_syntax() -> None:
    rep = parse_text(_CITEX_HEAD)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_cite_clash_dispatch_apply(tmp_path: Path) -> None:
    """\\ifx 死支内活装载行注释中和; natbib 行不动。"""
    _write(tmp_path, _CITE_DOC)
    assert when_cond_ok("cite_natbib_clash_retire", "syntax", None, _CITEX_HEAD, tmp_path)
    ok, note = _apply("cite_natbib_clash_retire", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "%\\usepackage{cite}" in t
    assert "\\usepackage[numbers,sort&compress]{natbib}" in t


def test_cite_clash_declines_cite_only(tmp_path: Path) -> None:
    """单载 cite 无 natbib → 双前瞻闸拒 (无 arity 冲突不退役)。"""
    _write(tmp_path, "\\usepackage{cite}\n\\begin{document}x\\end{document}\n")
    assert not when_cond_ok(
        "cite_natbib_clash_retire", "syntax", None, _CITEX_HEAD, tmp_path
    )


def test_cite_clash_masked_no_double_comment(tmp_path: Path) -> None:
    """已注释 cite 装载行不产 ``%%`` 双注释 —— cond 过 apply decline。"""
    src = (
        "\\usepackage{natbib}\n%\\usepackage{cite}\n\\begin{document}x\\end{document}\n"
    )
    _write(tmp_path, src)
    assert when_cond_ok("cite_natbib_clash_retire", "syntax", None, _CITEX_HEAD, tmp_path)
    ok, _ = _apply("cite_natbib_clash_retire", tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


# ════════════════════════════════════════════════════════════════
# astro-ph/0605352: 行间 \input 毒化 \noalign → @@input 可展化
# ════════════════════════════════════════════════════════════════

_NOALIGN_HEAD = "WOM33varsearchV4.tex:673: Misplaced \\noalign.\nl.673 \\hline"


def test_noalign_classifies_syntax() -> None:
    rep = parse_text(_NOALIGN_HEAD)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_noalign_dispatch_apply(tmp_path: Path) -> None:
    """\\hline 邻位 \\input{X} → \\csname @@input\\endcsname{X}。"""
    _write(
        tmp_path,
        "\\begin{tabular}{l}\n\\hline\na\n\\hline\n"
        "\\input{ebaslist.tex}\n\\hline\n\\end{tabular}\n",
    )
    (tmp_path / "ebaslist.tex").write_text("b \\\\\n", encoding="utf-8")
    assert when_cond_ok("input_noalign_primitive", "syntax", None, _NOALIGN_HEAD, tmp_path)
    ok, note = _apply("input_noalign_primitive", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\hline\n\\csname @@input\\endcsname{ebaslist.tex}" in t


def test_noalign_rule_family_variants(tmp_path: Path) -> None:
    """\\midrule/\\cline 族前驱同收 (pattern 家族面)。"""
    _write(tmp_path, "\\midrule\n\\input{a.tex}\n\\cline{1-2}\n\\input{b.tex}\n")
    ok, _ = _apply("input_noalign_primitive", tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\midrule\n\\csname @@input\\endcsname{a.tex}" in t
    assert "\\cline{1-2}\n\\csname @@input\\endcsname{b.tex}" in t


def test_noalign_declines_text_input(tmp_path: Path) -> None:
    """文本域 \\input (无 \\hline 族前驱) 不动。"""
    _write(tmp_path, "\\section{a}\n\\input{intro}\n")
    ok, _ = _apply("input_noalign_primitive", tmp_path)
    assert not ok
    assert "\\input{intro}" in (tmp_path / "main.tex").read_text()


def test_noalign_idempotent(tmp_path: Path) -> None:
    """改写后 ``\\csname @@input\\endcsname`` 形不再命中。"""
    _write(tmp_path, "\\hline\n\\input{a.tex}\n")
    ok, _ = _apply("input_noalign_primitive", tmp_path)
    assert ok
    ok, _ = _apply("input_noalign_primitive", tmp_path)
    assert not ok
    assert "\\csname @@input\\endcsname{a.tex}" in (tmp_path / "main.tex").read_text()


# ════════════════════════════════════════════════════════════════
# 2505.08102: zh 全角 （） 泄入 \big 族定界符操作位 → ASCII
# ════════════════════════════════════════════════════════════════

_DELIM_HEAD = "main.tex:359: Missing delimiter (. inserted).\nl.359 $x$"


def test_fullwidth_delim_classifies_syntax() -> None:
    rep = parse_text(_DELIM_HEAD)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_fullwidth_delim_dispatch_apply(tmp_path: Path) -> None:
    """\\big（/\\big）/\\left（/\\right） 全收。"""
    _write(
        tmp_path,
        "\\begin{document}\n$\\big（x+y\\big）$ and $\\left（z\\right）$\n\\end{document}\n",
    )
    assert when_cond_ok("big_fullwidth_delim_fix", "syntax", None, _DELIM_HEAD, tmp_path)
    ok, note = _apply("big_fullwidth_delim_fix", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "$\\big(x+y\\big)$" in t
    assert "$\\left(z\\right)$" in t


def test_fullwidth_delim_declines_ascii(tmp_path: Path) -> None:
    """ASCII () 原稿形 → cond 拒 + apply 空转 (幂等面)。"""
    _write(tmp_path, "$\\big(x\\big)$\n")
    assert not when_cond_ok(
        "big_fullwidth_delim_fix", "syntax", None, _DELIM_HEAD, tmp_path
    )
    ok, _ = _apply("big_fullwidth_delim_fix", tmp_path)
    assert not ok


def test_fullwidth_delim_non_big_adjacent_untouched(tmp_path: Path) -> None:
    """裸 （） 非 \\big 邻位不动 (missing_char 域, 非本臂)。"""
    _write(tmp_path, "（x）\n")
    ok, _ = _apply("big_fullwidth_delim_fix", tmp_path)
    assert not ok
    assert "（x）" in (tmp_path / "main.tex").read_text()


# ════════════════════════════════════════════════════════════════
# 0812.1022: emulateapj \LT@endpbox 缺 \color@endgroup → \egroup 前补
# ════════════════════════════════════════════════════════════════

_ENDBOX_HEAD = "ms.tex:506: Extra }, or forgotten \\endgroup.\nl.506 x"

_CLS_STALE = "\\def\\LT@endpbox{%\n  \\@finalstrut\\@arstrutbox\\egroup\n}\n"


def test_endpbox_classifies_syntax() -> None:
    rep = parse_text(_ENDBOX_HEAD)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_endpbox_dispatch_apply_cls(tmp_path: Path) -> None:
    """\\@finalstrut\\@arstrutbox↔\\egroup 间插 \\color@endgroup。"""
    _write(tmp_path, _CLS_STALE, name="emulateapj.cls")
    _write(tmp_path, "\\documentclass{emulateapj}\n\\begin{document}x\\end{document}\n")
    assert when_cond_ok("lt_endpbox_color_fix", "syntax", None, _ENDBOX_HEAD, tmp_path)
    ok, note = _apply("lt_endpbox_color_fix", tmp_path)
    assert ok, note
    t = (tmp_path / "emulateapj.cls").read_text()
    assert "\\@arstrutbox\\color@endgroup\\egroup" in t


def test_endpbox_declines_tex_site(tmp_path: Path) -> None:
    """同名 def 落 .tex 不收 (exts [.cls,.sty] cls 域专属) —— cond 过
    (source_contains 全域见字面) apply decline。"""
    _write(tmp_path, _CLS_STALE)
    assert when_cond_ok("lt_endpbox_color_fix", "syntax", None, _ENDBOX_HEAD, tmp_path)
    ok, _ = _apply("lt_endpbox_color_fix", tmp_path)
    assert not ok
    assert "\\color@endgroup" not in (tmp_path / "main.tex").read_text()


def test_endpbox_idempotent_fixed_form(tmp_path: Path) -> None:
    """已补齐形 (\\color@endgroup 在) 签名位不再紧邻 → 天然幂等。"""
    src = "\\def\\LT@endpbox{\\@finalstrut\\@arstrutbox\\color@endgroup\\egroup}\n"
    _write(tmp_path, src, name="x.cls")
    ok, _ = _apply("lt_endpbox_color_fix", tmp_path)
    assert not ok
    assert (tmp_path / "x.cls").read_text() == src


# ════════════════════════════════════════════════════════════════
# 2606.18573: zh 吞 \redactcite 外层 } (doc 级 runaway, 非 aux 回读)
# ════════════════════════════════════════════════════════════════

_REDACT_HEAD = "! File ended while scanning use of \\redactcite.\nl.562 x"


def test_redactcite_classifies_runaway_payload() -> None:
    rep = parse_text(_REDACT_HEAD)
    cat, pay = rs().taxonomy.classify(rep)
    assert (cat, pay) == ("runaway_scan", "\\redactcite")


def test_redactcite_brace_close_dispatch_apply(tmp_path: Path) -> None:
    """\\redactcite{\\cite{key}。 → \\redactcite{\\cite{key}}。"""
    _write(tmp_path, "正文 \\redactcite{\\cite{thompson_ssl_cv_dataset_2026}。 下段\n")
    assert when_cond_ok(
        "redactcite_brace_close",
        "runaway_scan",
        "\\redactcite",
        _REDACT_HEAD,
        tmp_path,
    )
    ok, note = _apply("redactcite_brace_close", tmp_path, "\\redactcite")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\redactcite{\\cite{thompson_ssl_cv_dataset_2026}}。" in t


def test_redactcite_declines_healthy(tmp_path: Path) -> None:
    """双括健康稿前瞻 ``(?![ \\t\\n]*\\})`` 拒中 —— 原文不动 (天然幂等)。"""
    src = "x \\redactcite{\\cite{a}} y\n"
    _write(tmp_path, src)
    assert when_cond_ok(
        "redactcite_brace_close",
        "runaway_scan",
        "\\redactcite",
        _REDACT_HEAD,
        tmp_path,
    )
    ok, _ = _apply("redactcite_brace_close", tmp_path, "\\redactcite")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_aux_purge_redactcite_arm_dispatches(tmp_path: Path) -> None:
    """指派表侧: aux_purge_regen (b) 臂 ctx_suggests 已含 redactcite —
    runaway_scan|\\redactcite when+cond 均过 (65-encoding:92 表列名)。"""
    assert when_cond_ok(
        "aux_purge_regen", "runaway_scan", "\\redactcite", _REDACT_HEAD, tmp_path
    )


def test_aux_purge_redactcite_declines_healthy_aux(tmp_path: Path) -> None:
    """该格实机非 aux 回读 (main.aux 0 redactcite 写件) —— 健康 aux 上
    aux_purge_regen 全链 (kind 派发→params→purge_corrupt_intermediates)
    decline 钉死: 指派表臂语义一致族表列名补全, 真修归
    redactcite_brace_close doc 级臂。"""
    (tmp_path / "main.aux").write_bytes(b"\\relax\n\\newlabel{a}{{1}{1}{ok}}\n")
    ok, _ = _apply("aux_purge_regen", tmp_path, "\\redactcite")
    assert not ok
    assert (tmp_path / "main.aux").exists()


# ════════════════════════════════════════════════════════════════
# 2609.19872: um ^\mathcal 裸 field token → 组化
# ════════════════════════════════════════════════════════════════

_UM_HEAD = "method.tex:7: Missing { inserted.\n<to be read again> \\__um_group_begin:"


def test_um_script_classifies_syntax() -> None:
    rep = parse_text(_UM_HEAD)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_um_script_dispatch_apply(tmp_path: Path) -> None:
    """^\\mathcal{P}/_\\mathcal{C}/^\\mathcal P (bare arg) 全收。"""
    _write(
        tmp_path,
        "\\begin{document}\n$f^\\mathcal{P}$ and $g_\\mathcal{C}$ "
        "and $h^\\mathcal P$\n\\end{document}\n",
    )
    assert when_cond_ok("um_script_alphabet_brace", "syntax", None, _UM_HEAD, tmp_path)
    ok, note = _apply("um_script_alphabet_brace", tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "$f^{\\mathcal{P}}$" in t
    assert "$g_{\\mathcal{C}}$" in t
    assert "$h^{\\mathcal P}$" in t


def test_um_script_declines_grouped(tmp_path: Path) -> None:
    """已组化 ^{\\mathcal{P}} 不命中 —— 天然幂等。"""
    src = "$f^{\\mathcal{P}}$\n"
    _write(tmp_path, src)
    ok, _ = _apply("um_script_alphabet_brace", tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_um_script_escaped_caret_rejected(tmp_path: Path) -> None:
    """``\\^`` 转义 accent 位 alphabet cs 不动 (lookbehind 拒)。"""
    src = "\\^\\mathcal{P}\n"
    _write(tmp_path, src)
    ok, _ = _apply("um_script_alphabet_brace", tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_um_script_verbatim_masked(tmp_path: Path) -> None:
    """verbatim 内 ``^\\mathcal`` 字面不改 (masked 面)。"""
    src = "\\begin{verbatim}\n$f^\\mathcal{P}$\n\\end{verbatim}\n"
    _write(tmp_path, src)
    ok, _ = _apply("um_script_alphabet_brace", tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src
