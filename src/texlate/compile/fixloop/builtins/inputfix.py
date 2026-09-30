r"""builtins.inputfix — input 族引用图上的源外科 (builtins.misc C3 再拆叶)。

``\input``/``\include``/``\subfile``/``\import`` 引用闭包驱动的三族
修复: 被引子文档 ``\documentclass`` 剥除 ``subfile_docclass_strip`` /
fragment 误判主档时 ``\input`` wrapper 提为 main
``main_wrapper_promote`` / input 族指向图形扩展名的命令位剥除
``graphics_include_strip``。引用图原语 (``_INPUT_EXEC*`` 执行面正则 /
``_input_targets`` / ``_exec_referenced_paths`` / ``_closure_scan``)
为族内共享件。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _splice
from texlate.compile.inject import _walk_inputs
from texlate.textutil import (
    DOCCLASS_RX,
    INPUT_BARE_RX,
    _tar_disguised,
    mask_tex,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# standalone/subfiles 子文档导言剥除 (failmine3 #164b)
# ════════════════════════════════════════════════════════════════

#: document 环境边界 —— ``\begin{document}``/``\end{document}`` (遮盖视图定位)。
_BEGIN_DOC_RE = re.compile(r"\\begin\s*\{document\}")
_END_DOC_RE = re.compile(r"\\end\s*\{document\}")

#: 单参 input 族执行面 —— 这些命令真把目标文件吸进编译流
#: (``\includegraphics`` 等非同族词干由 ``\s*\{`` 紧随约束排除)。
_INPUT_EXEC1_RX = re.compile(
    r"\\(?:input|include|subfile|subfileinclude|includestandalone"
    r"|InputIfFileExists)(?:\s*\[[^\]\n]*\])?\s*\{([^}]*)\}"
)
#: 双参 import 族 —— 第一参目录前缀，第二参文件名。
_INPUT_EXEC2_RX = re.compile(
    r"\\(?:import|subimport|includefrom|subincludefrom|inputfrom)"
    r"\s*\{([^}]*)\}\s*\{([^}]*)\}"
)


def _input_targets(arg: str) -> list[str]:
    r"""Input 族参数 → 候选相对路径 (空 = 构造名/宏名, 不可静态解析)。"""
    a = arg.strip().strip('"').strip()
    if not a or any(c in a for c in "{}\\"):
        return []
    if a.lower().endswith(".tex"):
        return [a]
    return [a, a + ".tex"]


def _exec_referenced_paths(ctx: LoopCtx) -> set[Path]:
    r"""全工程存活 input 族引用 → resolve 绝对路径集 (2409.00265 门)。

    遮盖视图扫描全 .tex/.sty/.cls: 注释/verbatim 内引用不算位; 宏体
    内引用过近似收 (宏可能永不被调 —— 宁多勿少, 漏引才是 2409.00265
    式灾难方向)。
    """
    refs: set[Path] = set()
    for src in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(src)
        if t is None:
            continue
        masked = mask_tex(t)
        for m in _INPUT_EXEC1_RX.finditer(masked):
            for cand in _input_targets(m.group(1)):
                refs.add((src.parent / cand).resolve())
        for m in _INPUT_EXEC2_RX.finditer(masked):
            d = m.group(1).strip().strip('"')
            if any(c in d for c in "{}\\"):
                continue  # 目录参含宏/构造 —— 不可静态解析，弃
            for cand in _input_targets(m.group(2)):
                refs.add((src.parent / d / cand).resolve())
        for m in INPUT_BARE_RX.finditer(masked):
            for cand in _input_targets(m.group("arg")):
                refs.add((src.parent / cand).resolve())
    return refs


def subfile_docclass_strip(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""被 input 族引用的非主 ``.tex`` 含存活 ``\documentclass`` → 剥至 body。

    inject 前导块 (``\PassOptionsToPackage{no-math}{fontspec}`` +
    ``\AddToHook`` 能力适配串) 逐文件打进全部 .tex —— 落在自带
    ``\documentclass`` 的 standalone/subfiles 类子文档头上时, 包的
    preamble-skip 机制 (``\includestandalone``/``\subfile``) 只中和
    ``\documentclass``..``\begin{document}`` 区间, 注入行在其前 = 正文区
    活代码 → ``Can be used only in preamble`` @子文件:1 (2410.00111/
    2003.03508/2310.16788 三格同机理, splice 面逐格核实)。

    剥至纯 body 区后语义: ``\subfile``/``\includestandalone`` 包机制
    本就跳过整个 preamble 区 (恒等); ``\subimport``/裸 ``\input`` 得
    唯一可编译形。子文档 preamble 里的 ``\usepackage``/``\newcommand``
    在载入语义下本就够不着 body, 剥离无功能损失。

    遮盖视图复核: 注释/verbatim 内的 ``\documentclass``/``\begin{document}``
    不算位; ``DOCCLASS_RX`` 兼收 ``\documentstyle`` (2.09 子文档同机理)。
    无 ``\begin{document}`` 的异形制不动 (无可剥区)。主档经
    ``ctx.main_path()`` 排除 —— resolve 双端比对防路径形态差。

    引用门 (2409.00265): 只剥被存活 input 族命令引用的文件 —— 无引用
    的 docclass 持件 (独立第二文档, 或 main 误判下的真主档) 永远进不了
    编译流, 剥它是纯害 (2409.00265: precheck 误选 Biography 为主档,
    真主档 Main 被剥成 body → env_undefined|frontmatter + 1326 错级联)。
    """
    del eng, payload
    main = ctx.main_path()
    main_res = main.resolve() if main is not None else None
    exts = tuple(params.get("exts") or (".tex",))
    cands: list[tuple[Path, str, re.Match[str], re.Match[str] | None]] = []
    for f in ctx.tex_files(exts):
        if main_res is not None and f.resolve() == main_res:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        if not DOCCLASS_RX.search(masked):
            continue  # 无存活 docclass —— 普通被 input 件，不动
        mb = _BEGIN_DOC_RE.search(masked)
        if mb is None:
            continue  # 无 body 区 —— 非输入式子文档，不动
        cands.append((f, t, mb, _END_DOC_RE.search(masked, mb.end())))
    if not cands:
        return False, "no docclass-bearing non-main .tex"
    referenced = _exec_referenced_paths(ctx)
    changed = 0
    for f, t, mb, me in cands:
        if f.resolve() not in referenced:
            continue  # 无存活引用 —— 独立第二文档/误判主档，剥了也进不了编译流
        body = t[mb.end() : me.start() if me is not None else len(t)]
        ctx.write(
            f,
            "% fixloop: stripped to body (docclass-bearing subfile)\n" + body,
        )
        changed += 1
    if not changed:
        return False, "no input-referenced docclass-bearing non-main .tex"
    return True, f"body-only strip in {changed} file(s)"


# ════════════════════════════════════════════════════════════════
# fragment 误判主档 → \input wrapper 提升 (2609.19170)
# ════════════════════════════════════════════════════════════════


def _closure_scan(ctx: LoopCtx, main: Path, masked_text: str) -> tuple[set[Path], bool]:
    r"""收集 ``(main, 遮盖文本)`` 的 ``\input`` 传递闭包成员与 ``\end{document}`` 可达性。

    inject ``_closure_has_document`` 的修复层镜像: 同一 ``_walk_inputs``
    口径 (声明目录→工程根两跳、tar 伪装闸、环引 visited、规模上界
    ``_MASS_FILE_CAP``); 种子本体计入成员集 (walk 只产下游目标)。
    """
    root = ctx.io.wdir.resolve()
    members = {main.resolve()}
    has_end = bool(_END_DOC_RE.search(masked_text))
    for tgt, sub in _walk_inputs(root, [(main.resolve(), masked_text)]):
        members.add(tgt)
        if not has_end and _END_DOC_RE.search(sub):
            has_end = True
    return members, has_end


def _wrapper_candidates(ctx: LoopCtx, main_res: Path) -> list[Path]:
    r"""合格 wrapper: ``\input`` 闭包吞 ``main_res`` 且闭包达 ``\end{document}``。

    候选种子的 tar 伪装闸 —— 成员字节可含 ``\input``/``\end{document}``
    假信号 (inject scanned 同闸); 现主档自身经 resolve 比对排除。
    """
    winners: list[Path] = []
    for f in ctx.tex_files((".tex", ".ltx")):
        if f.resolve() == main_res:
            continue
        try:
            if _tar_disguised(f.read_bytes()):
                continue
        except OSError:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        members, has_end = _closure_scan(ctx, f, mask_tex(t))
        if main_res in members and has_end:
            winners.append(f)
    return winners


def main_wrapper_promote(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Fragment 误判主档收容: 把吞进现主档且闭包达 ``\end{document}`` 的 wrapper 提为 main。

    ``find_main_tex`` pass-1 只收字面 ``\documentclass`` 件 —— 裸
    ``\input`` 编排壳永不入池; 池内若只剩 fragment (无 ``\end{document}``
    无 ``\input``) 即编译 ``*** (job aborted, no legal \end found)``
    (2609.19170: ``sections/00_preamble.tex`` 止于 ``\maketitle``, 真入口
    是根目录 9 行 ``\input`` 列表)。W99 闭包档因池非空被跳过 —— 修复层
    直接换 main 比动 inject 探测面爆炸半径小。

    提拨判据 (全经 ``_closure_scan`` 遮盖视图, 注释/verbatim 内不计):
    候选 ``\input`` 传递闭包含现主档 **且** 闭包任一文件见字面
    ``\end{document}``。守卫: 现主档自身闭包已达 ``\end{document}`` 时
    非 fragment 误判让位; 恰一个合格 wrapper 才动 —— 零个无救, 多个
    歧义让位。``ctx.io.main_rel`` 可变 (engine.py:611/1094 先例),
    编译面逐轮活读 ``main_rel`` 无派生缓存要失效; 翻转落
    ``ledger.advisories`` + 动作账本。
    """
    del eng, payload, params
    main = ctx.main_path()
    if main is None or not main.is_file():
        return False, "no main"
    text = ctx.read(main)
    if text is None:
        return False, "main unreadable"
    main_res = main.resolve()
    _, main_end = _closure_scan(ctx, main, mask_tex(text))
    if main_end:
        return False, "main closure already reaches \\end{document}"
    winners = _wrapper_candidates(ctx, main_res)
    if not winners:
        return False, "no \\end{document}-reaching wrapper inputs current main"
    if len(winners) > 1:
        names = ", ".join(f.relative_to(ctx.io.wdir).as_posix() for f in winners)
        return False, f"ambiguous wrappers: {names}"
    rel = winners[0].relative_to(ctx.io.wdir).as_posix()
    old = ctx.io.main_rel
    ctx.io.main_rel = rel
    ctx.ledger.advisories.append(
        f"main_wrapper_promote: main_rel {old} -> {rel} "
        "(fragment rescued by \\input wrapper)"
    )
    return True, f"main_rel {old} -> {rel}"


# ════════════════════════════════════════════════════════════════
# \include/\input{*.<gfx>} 非 TeX 目标剥除 (math/0501227)
# ════════════════════════════════════════════════════════════════

#: input 族把目标当 TeX 源吸进编译流——花括号目标落图形扩展名时必为
#: ``\include``↔``\includegraphics`` 类笔误 (math/0501227 preamble 期
#: ``\include{triangle_dots.eps}`` 把 EPS 头按 TeX 展开 → Missing
#: ``\begin{document}`` 爆流; 同位 ``\includegraphics{triangle_dots}``
#: 在 body 另有正解，剥除零语义损失)。
_GFX_INPUT_EXTS = frozenset(
    {
        ".eps",
        ".ps",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
    }
)


def graphics_include_strip(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\(include|input|InputIfFileExists){<name>.<gfxext>}`` → 剥除命令位。

    单参 input 族命令只可能吸 TeX 源; 目标扩展名落图形族时该行必错,
    剥掉命令 span (保行内其余内容)。遮盖视图定位——注释/verbatim 内
    同形串不算位。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("gfx_exts") or _GFX_INPUT_EXTS)}
    done: list[str] = []
    for f in ctx.tex_files((".tex",)):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        spans = [
            m.span()
            for m in _INPUT_EXEC1_RX.finditer(masked)
            if PurePosixPath(m.group(1).strip().strip('"')).suffix.lower() in exts
        ]
        if not spans:
            continue
        ctx.write(f, _splice(t, [(s, e, "") for s, e in spans]))
        done.append(f"{f.name}×{len(spans)}")
    return (bool(done)), f"gfx-target input sites stripped: {', '.join(done)}"
