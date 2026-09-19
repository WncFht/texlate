"""mnras.cls usegraphicx 选项 Options Section 炸修复回归钉 (vendored 真件补丁)。

实证背景 (cell 1206.0291): ``\\documentclass[usenatbib,usegraphicx]{mn2e}``
→ 老类名经 stub 桥到 mnras 面; mnras.cls v3.2 (2023/07/20, 上游 verbatim)
:79 ``\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}``
—— ``\\ds@`` 处理器在 ``\\ProcessOptions`` 内执行, kernel 对 Options
Section 内 ``\\usepackage``/``\\RequirePackage``/``\\LoadClass`` 直接炸
"LaTeX Error: \\RequirePackage or \\LoadClass in Options Section"。
上游同文件 :1335 usenatbib 已是「\\ds@ 只置 if → ProcessOptions 后
\\usepackage」正例, graphicx 系孤例漏改。补丁沿该文件自身惯用体例:
\\ds@usegraphicx 只置 ``\\@usegraphicxtrue``, ``\\ProcessOptions`` 后
``\\if@usegraphicx\\usepackage{graphicx}\\fi`` 补装, 语义等价零绕行。

旁证: vendor/shims/mn.cls + mn2e.cls (mn2e/mn → mnras 桥) 早已各自把
usegraphicx 从 ``\\@classoptionslist`` 剔除 —— 本钉位补丁让真件路径
(直书 ``\\documentclass[usegraphicx]{mnras}`` / stub 剔除面外) 同样免疫。
"""

from pathlib import Path

_VENDOR_DIR = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor"
)
_MNRAS_CLS = _VENDOR_DIR / "files/mnras.cls"


def _code_lines(text: str) -> list[str]:
    """逐行剥注释 (cls 内 \\% 转义只出现在 :1401, \\ProcessOptions 之下)。"""
    return [line.split("%", 1)[0] for line in text.splitlines()]


# ---------------------------------------------------------------- 补丁面
def test_ds_usegraphicx_flag_only() -> None:
    """\\ds@usegraphicx 处理器体只置 if —— Options Section 内零包装载。"""
    text = _MNRAS_CLS.read_text(encoding="utf-8")
    assert "\\def\\ds@usegraphicx{\\@usegraphicxtrue}" in text
    assert "\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage" not in text


def test_no_package_load_before_processoptions() -> None:
    """\\ProcessOptions 之上非注释代码不得出现 \\usepackage/\\RequirePackage/\\LoadClass。"""
    lines = _code_lines(_MNRAS_CLS.read_text(encoding="utf-8"))
    po_idx = next(i for i, line in enumerate(lines) if "\\ProcessOptions" in line)
    forbidden = ("\\usepackage", "\\RequirePackage", "\\LoadClass")
    for lineno, code in enumerate(lines[:po_idx], start=1):
        for cmd in forbidden:
            assert cmd not in code, f"mnras.cls:{lineno} {cmd} in options section"


def test_graphicx_deferred_after_processoptions() -> None:
    """usegraphicx 补装钉在 \\ProcessOptions 与 geometry 之间 (最早可装点)。"""
    text = _MNRAS_CLS.read_text(encoding="utf-8")
    po = text.index("\\ProcessOptions\\relax")
    gx = text.index("\\if@usegraphicx", po)  # 首个命中是 :80 \newif 声明
    geo = text.index("\\usepackage[a4paper]{geometry}")
    assert po < gx < geo
    assert "\\usepackage{graphicx}" in text[gx:geo]


def test_usenatbib_idiom_unchanged() -> None:
    """usenatbib 对照组惯用体例未动 —— 补丁向它对齐而非另起炉灶。"""
    text = _MNRAS_CLS.read_text(encoding="utf-8")
    assert "\\def\\ds@usenatbib{\\@usenatbibtrue}" in text
    assert "\\usepackage[authoryear]{natbib}" in text


# ---------------------------------------------------------------- 桥 stub 侧一致性
def test_mn_alias_stubs_still_strip_usegraphicx() -> None:
    """mn.cls/mn2e.cls stub 剔除面不变 —— 双路径免疫 (stub 剔除 + 真件补丁)。"""
    for name in ("mn.cls", "mn2e.cls"):
        body = (_VENDOR_DIR / "shims" / name).read_text(encoding="utf-8")
        assert "\\@classoptionslist" in body
        assert "usegraphicx" in body
        assert "\\LoadClassWithOptions{mnras}" in body
        assert "\\RequirePackage{graphicx}" in body
