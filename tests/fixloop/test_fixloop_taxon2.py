r"""taxon2 双格 —— missing_tfm ``scaled N`` 规格形 + fontspec 折行/TU-NFSS 派发面。

Cell A (2512.04896, stagerun-overnite-2026-09-20): vendored harmony.sty:62
``\newfont{\NOTEN}{musix13 scaled \value{notescl}}`` →
``Font \NOTEN=musix13 scaled 1200 not loadable`` —— missing_tfm 旧标记只认
``at Npt`` 规格形, ``scaled N`` 恒归 other|None (同格 :63 musix11 同标记)。
新标记 ``(?:at Npt|scaled -?N)`` 双形; filemap musix13.tfm→musixtex-fonts
已在索引, 无需 override。

Cell B (2609.19944, soak-2026-09-18): ``Package fontspec Error:`` 裸头首错
——标记在自身 ctx8 内但按 ~79 列折行、续行带 ``(fontspec)`` 前缀
(``cannot be\n(fontspec)                found;``), 旧直词
``cannot be found`` 跨不过折点恒归 other|None; 新标记三关节
(引号→cannot→be→found) 各容忍一个 ``(<pkg>)`` 续行前缀。同格
``Font TU/<fam>.otf(<i>)/m/n/<sz>=[<ext>]/OT at Npt not loadable`` NFSS
伴随错旧经 ``\S*?`` 膨胀+零宽 ``\s*`` 抓末段 ``/OT`` 得 missing_tfm|OT
死 payload (errs 12 条实证, install_tfm 恒 miss) —— TU 为 fontspec 专属
编码永不走 TFM, 新臂改归 fontspec_missing|去缀家族名 → install_sysfont
try_exts 复原扩展名投递; 排 missing_tfm 全臂之前 (评估序)。
"""

from _fixloopkit import rs

from texlate.compile.logparse import parse_text


def classify(text: str) -> tuple[str | None, str | None]:
    """warn-aware 分类——``warn_patterns`` 透传 ``parse_text`` (warn_* 伪类别面)。"""
    return rs().taxonomy.classify(parse_text(text, rs().warn_patterns))


def classify_errs(text: str) -> list[tuple[str | None, str | None]]:
    return rs().taxonomy.classify_errs(parse_text(text, rs().warn_patterns))


# ── Cell A 实证行 (stagerun-overnite-2026-09-20 2512.04896, harmony.sty:62/:63) ──
_SCALED_NOTEN_LOG = (
    "./harmony.sty:62: Font \\NOTEN=musix13 scaled 1200 not loadable: "
    "Metric (TFM) file or installed font not found.\n"
    "l.62 \\newfont{\\NOTEN}{musix13 scaled \\value{notescl}}\n"
)

_SCALED_NOTEN_LOWER_LOG = (
    "./harmony.sty:63: Font \\noten=musix11 scaled 1200 not loadable: "
    "Metric (TFM) file or installed font not found.\n"
    "l.63 \\newfont{\\noten}{musix11 scaled \\value{notescl}}\n"
)


def test_missing_tfm_scaled_spec() -> None:
    assert classify(_SCALED_NOTEN_LOG) == ("missing_tfm", "musix13")


def test_missing_tfm_scaled_spec_lowercase_cs() -> None:
    assert classify(_SCALED_NOTEN_LOWER_LOG) == ("missing_tfm", "musix11")


# ``at Npt`` 回归钉在 test_fixloop_taxrow.test_missing_tfm_spec_arms_regression
# (同字面 ``! Font \X=cmr10 at 10pt not loadable.`` + scaled 臂双钉)——不重复。


def test_missing_tfm_nfss_u_encoding_regression() -> None:
    # U/ 编码是合法 TFM 路由 (dmjhira 族), TU/ 臂不得误收
    log = (
        "./main.tex:9: Font U/dmjhira/m/n/12=dmjhira at 12.0pt not loadable: "
        "Metric (TFM) file not found.\n"
    )
    assert classify(log) == ("missing_tfm", "dmjhira")


# ── Cell B 实证块 (soak-2026-09-18 2609.19944 main.log:1003-1009) ──
_FONTSPEC_WRAPPED_LOG = (
    "./preamble.tex:85: Package fontspec Error: \n"
    '(fontspec)                The font "HaranoAjiMincho-Regular" cannot be\n'
    "(fontspec)                found; this may be but usually is not a fontspec\n"
    "(fontspec)                bug. Either there is a typo in the font name/file,\n"
    "(fontspec)                the font is not installed (correctly), or there is\n"
    "(fontspec)                a bug in the underlying font loading engine\n"
    "(fontspec)                (XeTeX/luaotfload).\n"
    "\n"
    "For immediate help type H <return>.\n"
)


def test_fontspec_missing_wrapped_be_found_joint() -> None:
    assert classify(_FONTSPEC_WRAPPED_LOG) == (
        "fontspec_missing",
        "HaranoAjiMincho-Regular",
    )


def test_fontspec_missing_wrapped_earlier_joints() -> None:
    # 折点随字体名长漂 —— 引号|cannot 与 cannot|be 关节同样容忍续行前缀
    log = (
        "./preamble.tex:85: Package fontspec Error: \n"
        '(fontspec)                The font "VeryLongFontName-Regular"\n'
        "(fontspec)                cannot\n"
        "(fontspec)                be found;\n"
    )
    assert classify(log) == ("fontspec_missing", "VeryLongFontName-Regular")


def test_fontspec_missing_unwrapped_regression() -> None:
    # 单行裸形 (2609.19582 Nimbus / 2609.20064 Tinos / 2609.20684 Amiri 实证已中)
    assert classify(
        '! Package fontspec Error: The font "Nimbus Roman" cannot be found.\n'
    ) == ("fontspec_missing", "Nimbus Roman")


# ── Cell B TU/ NFSS 伴随错 (main.log:1461+, 12 条同构) ──
_TU_NFSS_LOG = (
    "./main.tex:591: Font TU/HaranoAjiMincho-Regular.otf(0)/m/n/10.95="
    "[HaranoAjiMincho-Regular.otf]/OT at 10.95pt not loadable: Metric (TFM) "
    "file or installed font not found.\n"
)


def test_tu_nfss_routes_fontspec_not_tfm() -> None:
    # 去 .otf 扩展名与 (0) 实例缀 → install_sysfont try_exts 可复原投递
    assert classify(_TU_NFSS_LOG) == (
        "fontspec_missing",
        "HaranoAjiMincho-Regular",
    )


def test_tu_nfss_series_variant_payload() -> None:
    # b/n 系列 + 外部名与家族名相异 ([...-Bold.otf]) —— payload 取家族名
    log = (
        "./main.tex:591: Font TU/HaranoAjiMincho-Regular.otf(0)/b/n/14.4="
        "[HaranoAjiMincho-Bold.otf]/OT at 14.4pt not loadable: Metric (TFM) "
        "file or installed font not found.\n"
    )
    assert classify(log) == ("fontspec_missing", "HaranoAjiMincho-Regular")


def test_errs_full_cell_shape_dedup() -> None:
    # 2609.19944 全错误面：裸头 + Mincho/Gothic TU/ 伴随错 ——
    # 旧构成 {other:13, missing_tfm|OT:12}, 新全归 fontspec_missing 按
    # payload 去重保错误序
    log = (
        _FONTSPEC_WRAPPED_LOG
        + _TU_NFSS_LOG
        + (
            "./main.tex:591: Font TU/HaranoAjiGothic-Regular.otf(0)/m/n/10.95="
            "[HaranoAjiGothic-Regular.otf]/OT at 10.95pt not loadable: Metric (TFM) "
            "file or installed font not found.\n"
            "./main.tex:591: Font TU/HaranoAjiGothic-Regular.otf(1)/m/n/9="
            "[HaranoAjiGothic-Regular.otf]/OT at 9.0pt not loadable: Metric (TFM) "
            "file or installed font not found.\n"
        )
    )
    assert classify_errs(log) == [
        ("fontspec_missing", "HaranoAjiMincho-Regular"),
        ("fontspec_missing", "HaranoAjiGothic-Regular"),
    ]


# ── pdfex+gapmine 衍生：missing_file 扩展名类补 ``_`` (10-taxonomy 三位同补) ──


def test_missing_file_pdf_tex_ext_underscore_head() -> None:
    # ``File `figure2a.pdf_tex' not found`` —— 旧 ext 类 [a-zA-Z0-9] 无 ``_``,
    # head 全臂落空 → other → tail ``Enter file name`` 臂 (payload_group:null)
    # 抢成 missing_file|None 丢 payload; +_ 后 head 直签带全名。
    log = (
        "./main.tex:42: LaTeX Error: File `figure2a.pdf_tex' not found.\n"
        "l.42 \\input{figure2a.pdf_tex}\n"
    )
    assert classify(log) == ("missing_file", "figure2a.pdf_tex")


def test_missing_file_pdf_tex_tail_arm_payload() -> None:
    # 交互缺档形走 tail ``File`` 同款臂：guard ``Enter file name`` 在场时
    # 旧够不着 ``File`` 臂只能命中 payload_group:null 的 ``Enter file name``
    # 臂 → missing_file|None; +_ 后 ``File`` 臂先签，payload 保真。
    log = "File `figure2a.pdf_tex' not found.\nEnter file name: \n"
    assert classify(log) == ("missing_file", "figure2a.pdf_tex")


def test_missing_file_cannot_find_pdf_tex() -> None:
    # ``Cannot find the file`` 臂同洞：旧标记捕获截成 ``figure2a.pdf``。
    log = "./x.sty:39: Package x Error: Cannot find the file figure2a.pdf_tex.\n"
    assert classify(log) == ("missing_file", "figure2a.pdf_tex")


def test_missing_file_ext_class_regression() -> None:
    # .sty / 多段名 ``x.y.z.tex`` 捕获不受 ``_`` 补位影响 (pdfex 复核)
    assert classify("./m.tex:1: LaTeX Error: File `foo.sty' not found.\n") == (
        "missing_file",
        "foo.sty",
    )
    assert classify("./m.tex:1: LaTeX Error: File `x.y.z.tex' not found.\n") == (
        "missing_file",
        "x.y.z.tex",
    )
