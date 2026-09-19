r"""AAS 系 stub 书目区裸 `&` 宽容面回归钉 (aaspatch lane, 2026-09-19)。

实证背景 (envdiag 普查 tmp/lane-envdiag/report-diagrams.md 路由):
期稿 ``thebibliography``/``references`` 书目区存在裸 ``&`` 惯例 ——
``\bibitem[.. & ..]`` label 内未转义 ``&`` 是 catcode-4 alignment tab,
水平模式下炸 ``Misplaced alignment tab character &``:

- astro-ph/0111599 (aasms4): BenedictR7.tex ``\bibitem[Benedict, Smith,
  & Kenney 1996]`` + ``[Kenney, Carlstrom, & Young 1993]`` 2 处裸 ``&``,
  stagerun-rt1 fixloop 残盘 ``Misplaced alignment tab`` ×1
  (acceptable_pdf)。
- astro-ph/0104331 (aa.cls): ``\bibitem[de Thije & Katgert 1999]``
  1 处裸 ``&`` (同目录其余 6 处均为 ``\&`` 转义形 —— 作者漏转孤例)。

机制: catcode-4 ``&`` 在参数读入时已 tokenize, 宏内无法事后消毒 ——
唯一收法是让 ``&`` 在**读入时**就是 active char 再展开 ``\&``。
补丁三件套同构: 装载时 ``\begingroup\catcode`\&=\active\gdef&{\&}\endgroup``
把 active ``&`` 全局钉成 ``\&``; ``\AtBeginDocument`` 内
``\global\let`` 存 ``\thebibliography`` 终版 + ``\gdef`` 外套
``\catcode`\&=\active`` (hook 自带组, 非 global 定义作废;
延期捕获让后载 natbib ``\renewenvironment`` 版仍被罩到)。
``\begin..\end`` 自带组把激活域限在 env 内, 外部 tabular 不受影响。
aasms4/aaspp4 的 ``\references`` env 同机理在 ``\bgroup`` 后激活。

真件对照: 真 aasms4.sty/aa.cls (corpus_v3 shipped copies) 均无 ``&``
catcode 面 —— 原件原样也会炸 (期稿容错产物, PDF 照出), 本补丁是
stub 宽容面而非真件镜像; aastex61/62 的 ``&``-active 仅限其
deluxetable 机制内部, 与书目区无关。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")


def _run(wdir: Path, tex: str, passes: int = 1) -> str:
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    for _ in range(passes):
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [_XELATEX, "-interaction=nonstopmode", "main.tex"],
            cwd=wdir,
            capture_output=True,
            timeout=120,
            check=False,
        )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def _n_err(log: str) -> int:
    return len(re.findall(r"^! ", log, re.MULTILINE))


def _code(body: str) -> str:
    """滤 % 注释行 —— pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


# ------------------------------------------------------- 源码级 pin (免编译)


@pytest.mark.parametrize("name", ["aasms4.sty", "aaspp4.sty", "aa.cls"])
def test_amp_active_gdef_present(name: str) -> None:
    r"""三件同构: active ``&`` 全局钉 ``\&`` + env 外套激活。"""
    code = _code((STUBS / name).read_text(encoding="utf-8"))
    assert r"\begingroup\catcode`\&=\active\gdef&{\&}\endgroup" in code
    assert r"\gdef\thebibliography{\catcode`\&=\active" in code


@pytest.mark.parametrize("name", ["aasms4.sty", "aaspp4.sty"])
def test_aas4_references_env_activates_amp(name: str) -> None:
    r"""``\references`` env ``\bgroup`` 后即激活 ``&`` —— 裸用/`\begin` 两形通吃。"""
    code = _code((STUBS / name).read_text(encoding="utf-8"))
    assert r"\bgroup\catcode`\&=\active" in code


@pytest.mark.parametrize("name", ["aasms4.sty", "aaspp4.sty", "aa.cls"])
def test_wrapper_deferred_to_begin_document(name: str) -> None:
    r"""env 外套钉 ``\AtBeginDocument`` + ``\global\let``/``\gdef`` ——
    hook 自带组, 非 global 定义当场作废; 且 natbib 等后载包
    ``\renewenvironment{thebibliography}`` 后仍捕获最终版。"""
    code = _code((STUBS / name).read_text(encoding="utf-8"))
    assert r"\AtBeginDocument{\global\let" in code
    assert r"\gdef\thebibliography" in code


# ------------------------------------------------------- 真编译钉


@pytest.mark.integration
@_COMPILE
@pytest.mark.parametrize("sty", ["aasms4", "aaspp4"])
def test_aas4_raw_amp_in_bibitem_label(tmp_path: Path, sty: str) -> None:
    r"""0111599 型: ``\bibitem[.. & ..]`` 裸 ``&`` 不再 misplaced-&。"""
    shutil.copy(STUBS / f"{sty}.sty", tmp_path / f"{sty}.sty")
    log = _run(
        tmp_path,
        rf"""\documentclass{{article}}
\usepackage{{{sty}}}
\begin{{document}}
text
\begin{{thebibliography}}{{}}
\bibitem[Benedict, Smith, & Kenney 1996]{{k1}} Benedict et al. 1996
\bibitem[Buta \& Combes(1996)]{{k2}} Buta \& Combes 1996
\end{{thebibliography}}
after
\begin{{tabular}}{{ll}}
a & b
\end{{tabular}}
\end{{document}}
""",
        passes=2,
    )
    assert _n_err(log) == 0, f"{sty} 仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
    aux = (tmp_path / "main.aux").read_text(encoding="utf-8")
    # 裸 & label 落 aux 与 \& 转义形同构 —— 二轮回读不再炸
    assert r"\bibcite{k1}{Benedict, Smith, \& Kenney 1996}" in aux


@pytest.mark.integration
@_COMPILE
def test_aas4_bare_references_env_raw_amp(tmp_path: Path) -> None:
    r"""bare ``\references..\endreferences`` (2.09 裸用形) env 内裸 ``&`` 收。"""
    shutil.copy(STUBS / "aasms4.sty", tmp_path / "aasms4.sty")
    log = _run(
        tmp_path,
        r"""\documentclass{article}
\usepackage{aasms4}
\begin{document}
text
\references
\reference{k1} Smith & Jones 1995
\endreferences
\end{document}
""",
    )
    assert _n_err(log) == 0
    assert (tmp_path / "main.pdf").is_file()


@pytest.mark.integration
@_COMPILE
def test_aa_cls_raw_amp_in_bibitem_label(tmp_path: Path) -> None:
    r"""0104331 型: aa.cls + natbib ``\bibitem[de Thije & Katgert 1999]`` 裸 ``&``。"""
    shutil.copy(STUBS / "aa.cls", tmp_path / "aa.cls")
    log = _run(
        tmp_path,
        r"""\documentclass{aa}
\begin{document}
text \citep{dethije99}
\begin{thebibliography}{}
\bibitem[de Thije & Katgert 1999]{dethije99} de Thije \& Katgert 1999
\end{thebibliography}
after
\begin{tabular}{ll}
a & b
\end{tabular}
\end{document}
""",
        passes=2,
    )
    assert _n_err(log) == 0, f"aa.cls 仍 {_n_err(log)} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
    aux = (tmp_path / "main.aux").read_text(encoding="utf-8")
    # natbib label 槽内 \& 化 —— 与手写转义同构
    assert r"de Thije \& Katgert 1999" in aux
