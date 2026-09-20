"""fixloop 规则钉测试公共骨架——``EngStub``/``mk_ctx``/``rs``/``rule``/``classify``/``apply`` + 真 xelatex 臂。

``test_fixloop_*`` 簇逐文件复刻的同构脚手架归此一处（沿用
``_workerkit``/``_fuzzkit`` 抽取先例，只抽不写回——既有文件保持原样，
新批次规则钉文件只需 payloads + assertions）：

- ``EngStub``：builtin_transform/condition 直驱路径的最小引擎替身
  （``probe_file``→None / ``filemap``→[] / ``install_file``→False），
  ~70 文件同体；``EngInstall`` = 可装件子类（installable 集合内名落
  fake texmf，probe 复核命中，``install_calls`` 记账）。
- ``mk_ctx``：``LoopCtx(wdir=tmp_path, engine_name="xelatex",
  main_rel=..., err_head=...)`` 工厂——89 文件同体。
- ``rs``/``rule``/``classify``：ruleset 装载 / rid 查规则 / log 文本
  分类三通（``_rs`` 55 文件、``_rule`` 61 文件、``_classify`` ~19 文件）。
- ``apply``：``actions._apply`` 直驱集中点——``# noqa: SLF001``
  豁免一处收口（47 文件各自豁免的现状归此）。
- 真 xelatex 臂：``XELATEX`` 路径常量 + ``requires_xelatex`` skipif 钉
  （32 处同名散钉）+ ``run_xelatex``（写 main.tex → nonstopmode 编译 →
  回读 main.log；``extra`` 落侧车件、``passes`` 多轮）+ ``n_err``
  （``^! `` 计数）。
- ``DOC``：最小 article 文档壳（6 文件逐字节同体）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import ErrReport, parse_text

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine
    from texlate.compile.fixloop.ruleset import Rule, Ruleset


#: 最小 article 文档壳——``\\documentclass{article}`` + ``x`` 正文。
DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"

#: 宿主机 xelatex 绝对路径（缺席 → ``requires_xelatex`` 臂整体跳过）。
XELATEX = shutil.which("xelatex")

#: 真编译臂 skipif 钉——原 ``_COMPILE``/``_HAS_XELATEX``/内联 mark 归此一名。
requires_xelatex = pytest.mark.skipif(XELATEX is None, reason="xelatex not installed")


class EngStub:
    """builtin_transform/condition 直驱路径的最小引擎替身（不触真 texmf）。"""

    name = "xelatex"
    caps: frozenset[str] = frozenset()

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> None:
        """updmap noop。"""


class EngInstall(EngStub):
    """``EngStub`` + install_file：installable 集合内名落 fake texmf，probe 复核命中。"""

    def __init__(self, texmf: Path, installable: set[str]) -> None:
        self.texmf = texmf
        self.texmf.mkdir(parents=True, exist_ok=True)
        self.installable = set(installable)
        self.install_calls: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        hit = self.texmf / fname
        return str(hit) if hit.is_file() else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        if fname not in self.installable:
            return False
        (self.texmf / fname).write_text("", encoding="utf-8")
        return True


def mk_ctx(
    tmp_path: Path,
    main_rel: str | None = "main.tex",
    err_head: str = "",
) -> LoopCtx:
    """直驱面 ``LoopCtx`` 工厂——xelatex 名钉死；``err_head`` 透传条件评估。"""
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel=main_rel,
        err_head=err_head,
    )


def rs() -> Ruleset:
    """``load_ruleset()`` 直通。"""
    return load_ruleset()


def rule(rid: str) -> Rule:
    """按 rid 取规则行。"""
    return next(r for r in rs().rules if r.id == rid)


def classify(text: str) -> tuple[str | None, str | None]:
    """log 文本 → ``(category, payload)``——``parse_text`` + taxonomy 直通。"""
    return rs().taxonomy.classify(parse_text(text))


def apply(
    rule_or_rid: Rule | str,
    ctx: LoopCtx,
    pay: str | None,
    *,
    eng: Engine | None = None,
) -> tuple[bool, str]:
    """``actions._apply`` 直驱集中点——SLF001 豁免一处收口。

    ``rule_or_rid`` 收 ``Rule`` 或 rid 字符串；``eng`` 缺省 ``EngStub()``
    （需 ``EngInstall`` 记账的调用方传实例进来）。
    """
    r = rule(rule_or_rid) if isinstance(rule_or_rid, str) else rule_or_rid
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        r, ctx, eng or EngStub(), pay, ErrReport()
    )


def run_xelatex(
    wdir: Path,
    tex: str,
    *,
    extra: dict[str, str] | None = None,
    passes: int = 1,
) -> str:
    """写 ``main.tex``（+ ``extra`` 侧车件）→ nonstopmode 编译 ``passes`` 轮 → 回读 ``main.log``。"""
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    for name, body in (extra or {}).items():
        (wdir / name).write_text(body, encoding="utf-8")
    for _ in range(passes):
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [XELATEX, "-interaction=nonstopmode", "main.tex"],
            cwd=wdir,
            capture_output=True,
            timeout=120,
            check=False,
        )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def n_err(log: str) -> int:
    """``^! `` 行计数——硬错数。"""
    return len(re.findall(r"^! ", log, re.MULTILINE))
