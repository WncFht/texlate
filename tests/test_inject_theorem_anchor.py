"""THEOREM_ANCHOR_SHIM 回归测试（B7 锚点对齐：共享计数器 theorem 双 dest）。

机理：`\newtheorem{lemma}[definition]` 在 <2026-06 内核上锚点记到根计数器
（`definition.N`），新内核 alias 计数器记 env 名（`lemma.N`）——en/zh 两臂
工具链不一致即丢一半锚点（2410.17902）。shim 挂
`cmd/@begintheorem/before` + `cmd/@opargbegintheorem/before`，按
`alias@ctr@<env>`/`the<env>` 存在性补发另一侧名字的孪生 dest。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.align import extract_landmarks
from texlate.compile.inject import THEOREM_ANCHOR_SHIM, inject_cjk

DOC = (
    "\\documentclass{amsart}\n"
    "\\usepackage{amsmath,amsthm,amssymb}\n"
    "\\usepackage{hyperref}\n"
    "\\usepackage[capitalize,noabbrev]{cleveref}\n"
    "\\theoremstyle{definition}\n"
    "\\newtheorem{definition}{Definition}[section]\n"
    "\\theoremstyle{plain}\n"
    "\\newtheorem{lemma}[definition]{Lemma}\n"
    "\\newtheorem{theorem}[definition]{Theorem}\n"
    "\\newtheorem{own}{Standalone}\n"
    "\\begin{document}\n"
    "\\section{S}\n"
    "\\begin{definition}\\label{d1}A def.\\end{definition}\n"
    "\\begin{lemma}\\label{l1}A lemma.\\end{lemma}\n"
    "\\begin{lemma}[named]\\label{l2}Noted.\\end{lemma}\n"
    "\\begin{theorem}\\label{t1}A thm.\\end{theorem}\n"
    "\\begin{own}\\label{o1}Own.\\end{own}\n"
    "See \\cref{l1}, \\ref{t1}.\n"
    "\\end{document}\n"
)


def test_shim_injected_both_modes() -> None:
    """ctex 与 xecjk 两条注入路径都带 shim（锚点分叉是工具链差异，与 CJK 引擎无关）。"""
    tex = "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    for mode in ("ctex", "xecjk"):
        out, info = inject_cjk(tex, mode=mode)
        assert info["status"] == "injected"
        assert "cmd/@begintheorem/before" in out
        assert "cmd/@opargbegintheorem/before" in out
        assert "MakeLinkTarget" in out


def test_shim_no_hardcoded_env_names() -> None:
    """shim 必须泛化：不允许出现具体 env 名（lemma/definition/theorem 等）。"""
    for name in ("lemma", "definition", "theorem", "corollary", "proposition"):
        assert not re.search(rf"\b{name}\b", THEOREM_ANCHOR_SHIM)


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_shim_emits_twin_dests(tmp_path: Path) -> None:
    """真编译验证：共享计数器 env 同时得到 env 名与计数器名两个 dest。

    旧内核（本机 <2026-06）原生出 `definition.N`，shim 补 `lemma.N`；
    `own` 自有计数器 env 不得出孪生（`own.1` 唯一锚）。
    """
    out, info = inject_cjk(DOC, mode="ctex")
    assert info["status"] == "injected"
    main = tmp_path / "main.tex"
    main.write_text(out, encoding="utf-8")
    xelatex = shutil.which("xelatex")
    assert xelatex is not None
    for _ in range(2):
        proc = subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [xelatex, "-interaction=nonstopmode", "main.tex"],
            cwd=tmp_path,
            capture_output=True,
            timeout=120,
            check=False,
        )
    assert proc.returncode == 0, proc.stdout[-2000:]
    dests = extract_landmarks(tmp_path / "main.pdf")["dests"]
    # 原生（根计数器名）锚点仍在
    assert "definition.1.2" in dests
    assert "definition.1.3" in dests
    assert "definition.1.4" in dests
    # shim 补的 env 名孪生（含带 [note] 的 \@begintheorem 路径）
    assert "lemma.1.2" in dests
    assert "lemma.1.3" in dests
    assert "theorem.1.4" in dests
    # 自有计数器 env 不出孪生
    assert "own.1" in dests
    assert not any(d.startswith("own.") and d != "own.1" for d in dests)
