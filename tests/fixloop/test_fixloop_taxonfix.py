r"""taxonfix 双项 —— ``\GenericError`` 顶行毒化 payload 排除 + tikz 库缺档臂。

项A (undefined_cs payload_scan): ``\GenericError``-led ctx 的顶行末位是内
核错误渲染宏 (真冒犯 cs 吞进 ``#N`` 参槽), 旧顶行抓取产出
``undefined_cs|GenericError`` 死 payload (0712.1016 ``\diagchar`` /
2105.03751 ``\footnote`` 实证)。``payload_scan: undefined_cs`` python 提
取器对内核宏族回退 ``l.N`` 行末位非内核字母 cs (``\(``/``\)`` 类
nonletter 回显噪声滤除) → 中间展开层末位 cs → None。

项B (tikz 库缺档): "I did not find the tikz library 'X'" 报**库名**非文
件名——新 missing_file taxonomy 签抓库名, ``tikz_library_install`` /
``pgf_library_install`` 两臂按内核双查找路径拼 ``tikzlibrary{lib}.code.tex``
/ ``pgflibrary{lib}.code.tex`` 走 filemap (旧恒归 other 永不进 install 面;
2308.00056 quantikz / 2609.20331+2609.20771 quantikz2 实证; ~40 库仅出
pgflibrary 形无 tikzlib 孪生故须双探)。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, classify, make_proj, rs

from texlate.compile.fixloop import fixloop

# ── 2105.03751 形: GenericError ctx + l.N 行末 \footnote ──
_UNDEF_FOOTNOTE_LOG = (
    "./gftphantomcosmology.tex:913: Undefined control sequence.\n"
    "\\GenericError  ...                                \n"
    "                                                    #4  \\errhelp \\@err@     ...\n"
    "l.913 ...是译文这是译文这是译文\\footnote{\n"
    "                                                  这是译文这是译文 $...\n"
    "The control sequence at the end of the top line\n"
    "of your error message was never \\def'ed. If you have\n"
)

# ── 0712.1016 形: GenericError ctx + l.N 行中段 \diagchar (nonletter 噪声夹带) ──
_UNDEF_DIAGCHAR_LOG = (
    "./snc.tex:625: Undefined control sequence.\n"
    "\\GenericError  ...                                \n"
    "                                                    #4  \\errhelp \\@err@     ...\n"
    "l.625  函数 \\(\\diagchar{'00}\\) 的示例。}\n"
    "                                  \n"
    "The control sequence at the end of the top line\n"
    "of your error message was never \\def'ed. If you have\n"
)

# ── 0712.1016 第四错形: 中间层末位 \endgroup 渲染机残片, l.N 行仍须胜 ──
_UNDEF_DIAGCHAR_ENDGROUP_LOG = (
    "./snc.tex:625: Undefined control sequence.\n"
    "\\GenericError  ...                                \n"
    "                                                     \\endgroup \n"
    "l.625  函数 \\(\\diagchar{'00}\\) 的示例。}\n"
    "                                  \n"
    "The control sequence at the end of the top line\n"
    "of your error message was never \\def'ed. If you have\n"
)

_UNDEF_PLAIN_LOG = (
    "! Undefined control sequence.\n"
    "\\foo ...ray}{c}\n"
    "l.12 \\bar baz\n"
    "The control sequence at the end of the top line\n"
    "of your error message was never \\def'ed. If you have\n"
)

_TIKZ_LIB_ERR = (
    "./main.tex:190: Package tikz Error: I did not find the tikz library "
    "'quantikz'. I looked for files named tikzlibraryquantikz.code.tex and "
    "pgflibraryquantikz.code.tex, but neither could be found in the current "
    "texmf trees..\n"
    "See the tikz package documentation for explanation.\n"
    "Type  H <return>  for immediate help.\n"
    " ...                                              \n"
    "                                                  \n"
    "l.190 \\usetikzlibrary{quantikz}\n"
)


def test_undef_scan_footnote_ln_tail() -> None:
    """2105.03751: 内核渲染宏排除 → l.N 行末位 ``footnote`` (旧抓 GenericError)。"""
    assert classify(_UNDEF_FOOTNOTE_LOG) == (
        "undefined_cs",
        "footnote",
    )


def test_undef_scan_diagchar_mid_ln_letter_only() -> None:
    r"""0712.1016: l.N 行中段冒犯 —— ``\diagchar`` 取到而 ``\)`` nonletter 噪声滤除。"""
    assert classify(_UNDEF_DIAGCHAR_LOG) == (
        "undefined_cs",
        "diagchar",
    )


def test_undef_scan_diagchar_endgroup_interior() -> None:
    r"""0712.1016 第四错: 中间层 ``\endgroup`` 残片不得抢 l.N 行的 ``\diagchar``。"""
    assert classify(_UNDEF_DIAGCHAR_ENDGROUP_LOG) == (
        "undefined_cs",
        "diagchar",
    )


def test_undef_scan_plain_topline_unchanged() -> None:
    """非 GenericError ctx: 顶行末位抓取与旧 regex 语义逐字节守恒。"""
    assert classify(_UNDEF_PLAIN_LOG) == (
        "undefined_cs",
        "foo",
    )


def test_tikz_library_missing_file_taxonomy() -> None:
    """tikz 库缺档 → missing_file|库名 (库名非文件名——裸装必 miss 的拦点)。"""
    assert classify(_TIKZ_LIB_ERR) == (
        "missing_file",
        "quantikz",
    )
    q2 = _TIKZ_LIB_ERR.replace("quantikz", "quantikz2")
    assert classify(q2) == (
        "missing_file",
        "quantikz2",
    )


def test_tikz_library_install_arms_shape() -> None:
    """两臂形态钉: order 居 install_file 前, ctx_suggests 签名闸, 命名约定 file。"""
    arms = {
        r.id: r
        for r in rs().rules
        if r.id in {"tikz_library_install", "pgf_library_install", "install_file"}
    }
    assert "install_file" in arms
    install_order = arms["install_file"].order
    for rid, tmpl in [
        ("tikz_library_install", "tikzlibrary{payload}.code.tex"),
        ("pgf_library_install", "pgflibrary{payload}.code.tex"),
    ]:
        arm = arms[rid]
        assert arm.phase == "loop"
        assert arm.order < install_order  # install_file 前截流
        assert arm.when == {"category": "missing_file", "payload_required": True}
        assert "did not find the tikz library" in arm.condition["ctx_suggests"]
        assert arm.action["kind"] == "install_file"
        assert arm.action["params"]["file"] == tmpl


def test_tikz_library_install_e2e(tmp_path: Path) -> None:
    """tikzlib 名命中 → 一轮 install_file 装 tikzlibraryX.code.tex 后 clean。"""
    eng = MockEngine(
        [{"log": _TIKZ_LIB_ERR}, {"log": CLEAN_LOG, "pdf": True}],
        installable={"tikzlibraryquantikz.code.tex"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "missing_file"
    assert cell["rounds"][0]["payload"] == "quantikz"
    # install_calls[0] 是编译层 docclass 自装 (article.cls), 本轮臂装在尾
    assert eng.install_calls[-1] == "tikzlibraryquantikz.code.tex"
    assert any(a["rule"] == "tikz_library_install" for a in cell["actions"])


def test_pgf_library_install_e2e_fallback(tmp_path: Path) -> None:
    """tikzlib 名 miss → 同轮落 pgf 臂装 pgflibraryX.code.tex (pgflibrary-only 库)。"""
    eng = MockEngine(
        [{"log": _TIKZ_LIB_ERR}, {"log": CLEAN_LOG, "pdf": True}],
        installable={"pgflibraryquantikz.code.tex"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert eng.install_calls[-2:] == [
        "tikzlibraryquantikz.code.tex",
        "pgflibraryquantikz.code.tex",
    ]
    assert any(a["rule"] == "pgf_library_install" for a in cell["actions"])
