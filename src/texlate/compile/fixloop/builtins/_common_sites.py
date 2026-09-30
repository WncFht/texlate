r"""builtins._common_sites — 站点解析/遮盖命中/编辑回放原语 (common 拆分)。

``_safe_rel`` payload 拒收口 / ``_resolve_site`` kpathsea 落点 /
``_is_live``+``_live_matches`` 遮盖视图活命中 / ``_map_tex_files``
逐 tex 映射 / ``_splice`` 编辑表排序回放 —— 各注入/归位 builtin
共用的底层小件单源。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from texlate.textutil import mask_tex, safe_rel

if TYPE_CHECKING:
    import re
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import LoopCtx

__all__ = [
    "Path",
    "PurePosixPath",
    "_is_live",
    "_live_matches",
    "_map_tex_files",
    "_resolve_site",
    "_safe_rel",
    "_splice",
    "mask_tex",
    "safe_rel",
]


def _safe_rel(name: str) -> PurePosixPath | None:
    """``payload`` 名 → ``PurePosixPath``; 空名/绝对路径/``..`` 段/NUL → ``None``。

    各注入/归位 builtin 统一的 payload 拒收口——非相对安全名一律 decline,
    绝不把 ``../x``/``/etc/x`` 写进 wdir。词法单源
    ``texlate.textutil.osutil.safe_rel`` (自 builtins.shim 归位: misc/
    filefix/assetfix/tarblob 多叶共用以一收)。
    """
    return safe_rel(name)


def _resolve_site(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    """落点 = kpathsea 解析位 ``main_dir/<rel>``; main 未知退 wdir 根。

    编译 cwd = ``main_path().parent`` 且无 TEXINPUTS 根注入 —— 平铺
    wdir 根对嵌套 main (``templates/arxiv/main.tex``) 不可见
    (2609.19664 fired-unfixed 实证); fileset_relocate 同口径。
    ``main_rel`` 怪径致目标逃出 wdir → None。
    """
    mp = ctx.main_path()
    dst = (mp.parent if mp is not None else ctx.wdir) / Path(*rel.parts)
    try:
        dst.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return dst


def _is_live(m: re.Match[str], masked: str, t: str) -> bool:
    r"""遮盖视图命中体的原文保真判 —— 跨遮盖区 (注释/verbatim 死臂) 命中为假。

    ``_live_matches`` 的逐命中谓词形: 非 ``finditer`` 枚举源
    (``iter_depth0`` 等自带过滤的迭代器) 逐枚复核用。
    """
    return masked[m.start() : m.end()] == t[m.start() : m.end()]


def _live_matches(rx: re.Pattern[str], t: str) -> list[re.Match[str]]:
    r"""遮盖视图命中且匹配体完整未遮——``%`` 注释/verbatim 内假装载点不算。

    mask_tex 等长遮盖 → match 位置/group 对原文有效；跨遮盖区的命中
    （注释内 ``\documentclass``、comment 环境）span 与原文不一致，跳过。
    2211.04482 记档同族：锚正则把 ``%\documentclass`` 当活缝。
    """
    masked = mask_tex(t)
    return [
        m
        for m in rx.finditer(masked)
        if masked[m.start() : m.end()] == t[m.start() : m.end()]
    ]


def _map_tex_files(
    ctx: LoopCtx, exts: tuple[str, ...], fn: Callable[[str], tuple[str, int]]
) -> int:
    """逐 tex 文件应用 ``fn(t) -> (nt, n)``, n>0 且文本有变则写回 → 改动文件数。"""
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = fn(t)
        if n and nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files


def _splice(t: str, edits: list[tuple[int, int, str]]) -> str:
    r"""(start, end, rep) 编辑表 → 排序回放拼接 (站点改写通用骨架)。

    各 ``_*_fix_text``/站点改写器只产编辑表, 回放语义单源 —— 与
    ``compile/mask.py`` ``apply_edits`` 不同: 纯拼接, 不补 ``\\n`` 保行号。
    csfix 叶 prepend 形 = 零宽编辑同骨架。
    """
    edits.sort()
    out: list[str] = []
    prev = 0
    for s, e, r in edits:
        out.append(t[prev:s])
        out.append(r)
        prev = e
    out.append(t[prev:])
    return "".join(out)
