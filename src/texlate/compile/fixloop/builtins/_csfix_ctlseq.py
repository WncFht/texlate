r"""builtins._csfix_ctlseq — expl3 ``Control sequence`` 撞名域 (csfix 拆分)。

``\cs_new`` 系 already-defined 签名 → docclass 缝顶 ``\let\X\@undefined``:
只收 file-line-error 行文件头落在注入 CJK 块装载树
(``_CTLSEQ_FILE_HEADS``) 的撞名 + texlate 注入块在档标记双证。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile._docseams import find_docclass_ends
from texlate.compile.fixloop.builtins._csfix_alloc import _allocated_cs_names
from texlate.compile.fixloop.builtins.common import (
    PDFTEX_PRIMS,
    _fixloop_log,
    _inject_after_docclass,
    _undefine_cs,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "PDFTEX_PRIMS",
    "_CJK_SEAM_MARKS",
    "_CTLSEQ_DEF_RE",
    "_CTLSEQ_ERRFILE_RE",
    "_CTLSEQ_FILE_HEADS",
    "_CTLSEQ_RESERVED",
    "_ctlseq_collided",
    "ctlseq_undefine",
]


# ═══ expl3 ``Control sequence`` 撞名缝顶清位格 (chineseclear, 2403.00013) ═══


#: ``Control sequence \X already defined`` —— expl3 ``\cs_new`` 系
#: ``\cs_if_exist`` 检查的 already-defined 签名 (Command 形 ``\@ifdefinable``
#: 报的姊妹签; taxonomy 只收 Command → 本签落 other 无 payload)。名字面
#: 纯字母类即闸: ``\c__fontspec_*``/``\ctex@*`` 内码名中 ``_``/``@`` 与
#: 紧跟的 `` already defined`` 邻接要求互斥, 天然排除 —— ``fontspec_
#: double_merge`` 的 ``\c__fontspec_shape_*`` 面与包内私有名都不进此格。
_CTLSEQ_DEF_RE = re.compile(r"Control sequence \\([A-Za-z]+) already defined")


#: file-line-error 行首 ``path/file.ext:NNN:`` 前缀 —— 第二定义者文件定位
#: (无此前缀的非 file-line-error log 不定界, 该名跳过)。``.cls`` 不收:
#: 类文件在 ``\documentclass`` 内执行, 其错必在缝前, 缝顶 ``\let`` 鞭长莫及。
_CTLSEQ_ERRFILE_RE = re.compile(
    r"^[ \t]*(\S+?\.(?:sty|def|cfg|clo|ltx)):[0-9]+:", re.IGNORECASE
)


#: 注入 CJK 块装载树的文件名头表 —— 错误文件落此才证第二定义者在缝位块内
#: (ctex 行 → ctexhook/ctexpatch/fix-cm/everysel/xeCJK → fontspec/zhnumber
#: 链; xecjk 模 fallback 块同树)。fontspec 恒在注入块装载树 (ctex/xeCJK
#: 双模都经其装载) → 其 ``\cs_new`` 撞名的第二定义者必在缝位。
_CTLSEQ_FILE_HEADS = (
    "ctex",
    "xecjk",
    "zhnum",
    "zhlineskip",
    "everysel",
    "fix-cm",
    "cjkfntef",
    "cjkulem",
    "fandol",
    "fontspec",
)


#: texlate 注入 CJK 块在档校验标记 (inject_cjk 只往 docclass 缝位写) ——
#: 缝顶 ``\let`` 只在注入块贴身缝位时保证第一定义者 ∈ cls 链 (块前零用户
#: preamble 行执行); 无标记 = 用户自备 ctex/未注入, 撞名机制不在本格。
_CJK_SEAM_MARKS = ("% [texlate injected]", "% texlate: CJK via xeCJK")


#: 清位禁区名表 —— ``Control sequence`` 签下 ``end*`` 形名义上可清
#: (``\cs_if_exist`` 无 ``\@qend`` 名拒, 与 ``\@ifdefinable`` 不同),
#: 但原语/内核命令被 ``\let\@undefined`` 即全局灾难, 与寄存器护栏并施。
_CTLSEQ_RESERVED = frozenset(
    {
        "relax",
        "end",
        "begin",
        "par",
        "input",
        "include",
        "endinput",
        "csname",
        "endcsname",
        "expandafter",
        "noexpand",
        "def",
        "gdef",
        "edef",
        "xdef",
        "let",
        "newcommand",
        "renewcommand",
        "providecommand",
        "newenvironment",
        "renewenvironment",
        "newtheorem",
        "documentclass",
        "documentstyle",
        "usepackage",
        "RequirePackage",
        "hbox",
        "vbox",
        "vtop",
        "vcenter",
        "font",
        "nullfont",
        "fi",
        "else",
        "or",
        "ifx",
        "ifnum",
        "ifdim",
        "ifcase",
        "ifeof",
        "iftrue",
        "iffalse",
        "ifmmode",
        "ifhmode",
        "ifvmode",
        "ifinner",
        "ifvoid",
        "ifhbox",
        "ifvbox",
        "ifcat",
        "ifdefined",
        "ifcsname",
        "ifpdf",
        "ifincsname",
        "iffontchar",
    }
    | set(PDFTEX_PRIMS)
)


def _ctlseq_collided(blob: str, heads: tuple[str, ...]) -> tuple[set[str], set[str]]:
    r"""逐行扫 ``Control sequence`` 撞名 → (CJK 块内撞名集, 肇事文件基名集)。

    双重定界: 签名行须带 ``file:N:`` 前缀 (非 file-line-error 形不定界
    不收), 且文件基名 ∈ 注入 CJK 块装载树头表 —— 非族文件的同名撞名
    (包间互撞) 不连坐。
    """
    names: set[str] = set()
    files: set[str] = set()
    for line in blob.splitlines():
        cm = _CTLSEQ_DEF_RE.search(line)
        if cm is None:
            continue
        fm = _CTLSEQ_ERRFILE_RE.match(line)
        if fm is None:
            continue  # 无 file:line 前缀不定界 —— 该名不收
        base = fm.group(1).rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if base.startswith(heads):
            names.add(cm.group(1))
            files.add(base)
    return names, files


def ctlseq_undefine(  # noqa: PLR0911 - 逐门 decline 注释即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Control sequence \X already defined`` → docclass 缝顶 ``\let\X\@undefined``。

    expl3 ``\cs_new`` 系撞名格, 与 ``undefine_for_redef`` 同教义 (清先定义
    位让后定义者赢) 但分域更窄: 只收 file-line-error 行文件头落在注入
    CJK 块装载树 (``_CTLSEQ_FILE_HEADS``) 内的撞名 —— 该约束同时保证
    第一定义者 ∈ ``\documentclass`` cls 链 (注入块贴身缝位, 块前零用户
    preamble 行), 缝顶 ``\let`` 序位正确 (cls 先定义已跑, ctex 后定义
    未跑)。非 CJK 块文件的 ``Control sequence`` 撞名 (包间互撞/包内
    互撞) 一律不碰 —— 缝顶清位对它们是错序白烧。

    撞名集扫描面 = err_head ∪ 本轮编译 log (``_fixloop_log``): halt_on_
    error 只见首错, best_effort 探针 log 内同文件簇连撞一轮批清。
    护栏: 纯字母名 (签名邻接天然排 ``_``/``@`` 内码) ∩ ``_allocated_
    cs_names`` 寄存器/盒型分配名 ∩ ``_CTLSEQ_RESERVED`` 原语名三滤;
    ``params.file_heads`` 可覆写文件头表。
    """
    del eng, payload
    heads = tuple(
        str(h).lower() for h in (params.get("file_heads") or _CTLSEQ_FILE_HEADS)
    )
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names, files = _ctlseq_collided(blob, heads)
    if not names:
        return False, "no Control-sequence collision in CJK-block files"
    names -= _allocated_cs_names(mask_tex(ctx.source_blob()))
    names -= _CTLSEQ_RESERVED
    if not names:
        return False, "all collided cs are allocated/reserved names — abstain"
    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    if not any(m in main_t for m in _CJK_SEAM_MARKS):
        return False, "no texlate CJK block at docclass seam"
    if not find_docclass_ends(main_t):
        return False, "no docclass seam"  # 退文件头 = cls 前清位, 错序
    fresh = [
        n
        for n in sorted(names)
        if f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if not fresh:
        return False, "all offenders already cleared"
    block = "% fixloop: ctlseq undefine before CJK block\n" + "\n".join(
        _undefine_cs(n) for n in fresh
    )
    if not _inject_after_docclass(ctx, block):
        return False, "docclass seam injection failed"
    return True, f"seam-clear {', '.join(fresh)} (files: {', '.join(sorted(files))})"
