r"""builtins._csfix_clobber — 原语覆写改名域 (csfix 拆分)。

用户档 ``\def\<primitive>`` (era 稿 mymacros 族 ``\mag``) →
baseline 原件树内 def+用点同改 ``\<prefix><name>``, 原语名归位。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_CLOBBER_DEF_KINDS",
    "primitive_clobber_rename",
]


#: ``\def\mag`` 族原语覆写 —— era 稿宏件 (mymacros 族) 把 TeX 寄存器原语
#: 名当文本宏重定义 (astro-ph/0103205 ``\def\mag{{\rm\thinspace mag}}`` /
#: 0103349 ``\def\mag{\hbox{$^{\rm m}$}}`` 双实证)。``\mag`` 是 xetex.def
#: ``\Gin@setpagesize`` ``\ifnum\mag=\@m`` 的 begin-doc 读取位 → 读到宏
#: 展开文本 "Missing number, treated as zero" (cat=syntax)。
#: 修 = baseline 原件树内 def+用点同改 ``\<prefix><name>`` (单一边界正则
#: 通吃 def/let/newcommand 各种定义形与全部调用点), 原语名归位。
_CLOBBER_DEF_KINDS: tuple[str, ...] = (
    "def",
    "gdef",
    "edef",
    "xdef",
    "let",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
)


def primitive_clobber_rename(  # noqa: C901 - names 表 × 逐名分派, 每门 decline 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""用户档 ``\def\<primitive>`` 覆写原语 → 原件树内全站改名 ``\<prefix><name>``。

    ``params.names`` = 守护原语名表 (默认 ``["mag"]`` —— 只收实证过
    begin-doc 读取位的名, 扩表须配 provenance); ``params.prefix`` = 改名
    前缀 (默认 ``"texlateuser"``); ``params.exts`` = 扫面扩展名。
    只动 ``params.baseline_dir`` pristine 树内文件: fixloop 装入件/包件
    里的 ``\<name>`` 是合法原语读, 改名即破坏。baseline 缺席 → fail-safe。
    """
    del eng, payload
    base_dir = params.get("baseline_dir")
    if not base_dir:
        return False, "no baseline_dir param"
    base_root = Path(base_dir)
    if not base_root.is_dir():
        return False, f"baseline_dir not a directory: {base_root}"
    names = [str(n).lstrip("\\") for n in (params.get("names") or ("mag",))]
    if not names:
        return False, "empty names list"
    prefix = str(params.get("prefix") or "texlateuser")
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls", ".def", ".mac", ".ltx"))
    def_rx = re.compile(
        rf"\\(?:{'|'.join(_CLOBBER_DEF_KINDS)})\*?\s*\{{?\s*"
        rf"\\(?:{'|'.join(re.escape(n) for n in names)})(?![a-zA-Z@])"
    )
    user_files = [
        f
        for f in ctx.tex_files(exts)
        if (base_root / f.relative_to(ctx.wdir)).is_file()
    ]
    texts = {f: ctx.read(f) for f in user_files}
    if not any(t is not None and def_rx.search(mask_tex(t)) for t in texts.values()):
        return False, "no primitive-clobber def in baseline files"
    changed: list[str] = []
    for name in names:
        new_cs = f"{prefix}{name}"
        if any(
            t is not None
            and re.search(rf"\\{re.escape(new_cs)}(?![a-zA-Z@])", mask_tex(t))
            for t in texts.values()
        ):
            continue  # 改名目标名已占用 —— 套娃即双定义, 该名弃权
        site_rx = re.compile(rf"\\{re.escape(name)}(?![a-zA-Z@])")
        n_sites = 0
        for f, t in texts.items():
            if t is None:
                continue
            nt, k = site_rx.subn(rf"\\{new_cs}", t)
            if k:
                ctx.write(f, nt)
                texts[f] = nt
                n_sites += k
        if n_sites:
            changed.append(rf"\{name}→\{new_cs} x{n_sites}")
    if not changed:
        return False, "clobber def found but rename blocked (name collision)"
    return True, "; ".join(changed)
