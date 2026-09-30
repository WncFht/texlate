r"""builtins._csfix_target — undefined_cs 按 cs 名打靶域 (csfix 拆分)。

``cs_targeted_fix``: ``_CS_FIX_TABLE`` (``_csfix_table`` 叶) + params
cs_table 叠加 → spec 键序分派 (strip_pkg → usepackage → cs_map →
guard/guard_pre → polyfill/polyfill_pre); 表外 payload 走
``_SPLIT_HEADS`` glue-残骸前缀拆分兜底。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from texlate.compile.fixloop.builtins._csfix_alloc import (
    _inject_before_docclass,
)
from texlate.compile.fixloop.builtins._csfix_table import _CS_FIX_TABLE
from texlate.compile.fixloop.builtins.common import (
    _drop_pkg_loads,
    _inject_after_docclass,
    _map_tex_files,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_SPLIT_GUARD",
    "_SPLIT_HEADS",
    "_SPLIT_REST_MAX",
    "_drop_pkg_loads",
    "_ensure_usepackage",
    "_guard_snippet",
    "_inject_after_docclass",
    "_map_tex_files",
    "_rewrite_cs_map",
    "_split_glued_cs",
    "cs_targeted_fix",
    "mask_tex",
]


def _rewrite_cs_map(t: str, cmap: dict[str, str]) -> tuple[str, int]:
    r"""``\old``→``\new`` 逐对改写 (词边界定) → (新文本, 是否改动)。"""
    nt = t
    for old, new in cmap.items():
        nt = re.sub(rf"\\{old}\b", rf"\\{new}", nt)
    return nt, int(nt != t)


def _ensure_usepackage(ctx: LoopCtx, eng: Engine, pkg: str) -> list[str]:
    r"""主文件 ``\documentclass`` 后注入 ``\RequirePackage{pkg}`` + 装文件 → 已做事项。"""
    out = []
    if not re.search(
        rf"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(pkg)}\b",
        mask_tex(ctx.source_blob()),  # 注释掉的 %\usepackage 不算已装载
    ) and _inject_after_docclass(ctx, f"\\RequirePackage{{{pkg}}} % fixloop: cs-fix"):
        out.append(f"inject \\RequirePackage{{{pkg}}}")
    if eng.probe_file(f"{pkg}.sty") or eng.install_file(f"{pkg}.sty"):
        out.append(f"{pkg}.sty available")
    else:
        out.append(f"{pkg}.sty still missing")
    return out


#: cs_targeted_fix 的 glue-残骸前缀拆分默认头表 —— 只收语料实证过的
#: 粘连头 (n100 undefined_cs 24/24 均为 splice/join 合并残骸; ``in`` 头
#: 前缀面太热 (int/indent/input/index… 真宏云集), 留在 cs_table 显式条目)。
_SPLIT_HEADS: tuple[str, ...] = (
    "linebreak",
    "item",
    "nabla",
    "Delta",
    "hline",
    "frac",
    "par",
    "dd",
    "bf",
    "it",
    "rm",
)
#: 与头同前缀的真宏名守卫 —— 命中即不拆 (part/parbox/parskip 是 kernel
#: 命令; ddot/ddots 是 amsmath; itemize/fraction 同理)。残余门之外的双保险。


_SPLIT_GUARD: frozenset[str] = frozenset(
    {
        "part",
        "para",
        "parbox",
        "parskip",
        "itemize",
        "itemsep",
        "ddot",
        "ddots",
        "fraction",
    }
)
#: 拆分残余的长度门 (语料残余全 ≤4: FSU/Cd/i/and/r…; 更长残余的真宏名
#: 还有 guard 兜底)。


_SPLIT_REST_MAX = 4


def _split_glued_cs(cs: str, heads: Iterable[str], guard: Iterable[str]) -> str | None:
    """``cs`` = 已知粘连头 + 残余 → ``"head rest"``; 不可拆返回 None。

    残余门：大写起首或 ≤_SPLIT_REST_MAX 字符; ``@`` 含名是包内私有 cs
    (版本偏斜类), 非粘连残骸，不拆。
    """
    if "@" in cs or cs in guard:
        return None
    for head in sorted(heads, key=len, reverse=True):
        if not cs.startswith(head):
            continue
        rest = cs[len(head) :]
        if rest and (rest[0].isupper() or len(rest) <= _SPLIT_REST_MAX):
            return f"{head} {rest}"
    return None


#: cs_targeted_fix ``guard``/``guard_pre`` 值形归一 —— ``true`` → 零参空体;
#: ``"[1]"`` 串 → argspec (空 body); dict ``{args, body}`` → 全形。
#: emission 恒走 ``\csname`` 包裹：裸 ``\providecommand\foo@bar`` 在 @=other
#: 读面把名断成 ``\foo``+stray 字母 (静默错义 + ``Missing \begin{document}``
#: 级联), ``\providecommand\csname`` 直写又把 ``\csname`` 当已定义名而
#: 静默 no-op —— 双死形，``\expandafter`` 先行展开是唯一通解
#: (renewguard 车道 forms/forms3.tex 全形实证)。``Command \X undefined``
#: (renew-on-undefined 内核签) 与 ``\csname`` 派发/@-名 cs_table 条目
#: 的本键一并收 —— provide 预置，doc 侧 ``\renewcommand`` 合法接管;
#: body 即未 renew 时的 use-site 兜底，语义同 polyfill 但名自表键出。
def _guard_snippet(cs: str, guard: object) -> str | None:
    r"""``guard`` spec → csname 形 ``\providecommand`` 预置 snippet; 不合法返回 None。"""
    if guard is True:
        args, body = "", ""
    elif isinstance(guard, str):
        args, body = guard, ""
    elif isinstance(guard, dict):
        args, body = str(guard.get("args") or ""), str(guard.get("body") or "")
    else:
        return None
    if not cs or re.search(r"[\\{}\s]", cs):
        return None
    return (
        "\\expandafter\\providecommand\\expandafter"
        f"{{\\csname {cs}\\endcsname}}{args}{{{body}}}"
    )


def cs_targeted_fix(  # noqa: C901, PLR0912 - spec 键序分派表，每键一处
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""undefined_cs 按 cs 修复表打靶 (handoff §2.2 cs→包表项)。

    spec 键组合序: ``strip_pkg`` 剥装载点 → ``usepackage`` 注入+装文件
    → ``cs_map`` ``\old``→``\new`` 逐文件改写 → ``guard``/``guard_pre``
    csname 形 ``\providecommand`` 预置 (renew-on-undefined 与 @-名专用,
    语义见 ``_guard_snippet`` 头注) → ``polyfill`` 注原始 TeX body
    (docclass 缝后) → ``polyfill_pre`` 同形注 docclass 行前 (cls 执行期
    调用面专用, ``\reserveinserts`` 类)。``engines.{eng_name}`` 子表整体
    覆盖顶层同名词 (引擎差异修, 如 bbm→dsfont)。payload 不在表 → 试
    ``split_heads`` glue-残骸前缀拆分 (合成 cs_map 项); 仍不中 → False
    落 undefined_cs_guess。
    """
    table = dict(_CS_FIX_TABLE)
    table.update(params.get("cs_table") or {})
    cs = (payload or "").lstrip("\\")
    base = table.get(cs)
    if not base:
        split = _split_glued_cs(
            cs,
            params.get("split_heads") or _SPLIT_HEADS,
            params.get("split_guard") or _SPLIT_GUARD,
        )
        if split is None:
            return False, f"{payload} not in cs-fix table"
        base = {"cs_map": {cs: split}}
    spec = {k: v for k, v in base.items() if k != "engines"}
    spec.update(
        cast("dict[str, Any]", (base.get("engines") or {}).get(ctx.engine_name) or {})
    )
    done: list[str] = []
    if strip := spec.get("strip_pkg"):
        n = _map_tex_files(
            ctx,
            (".tex", ".sty", ".cls"),
            lambda t: _drop_pkg_loads(t, str(strip)),
        )
        if n:
            done.append(f"strip \\usepackage{{{strip}}} x{n}")
    if use := spec.get("usepackage"):
        done.extend(_ensure_usepackage(ctx, eng, str(use)))
    if cmap := spec.get("cs_map"):
        n = _map_tex_files(ctx, (".tex", ".sty"), lambda t: _rewrite_cs_map(t, cmap))
        if n:
            done.append(f"cs_map in {n} files")
    for gkey, pre in (("guard", False), ("guard_pre", True)):
        if g := spec.get(gkey):
            snip = _guard_snippet(cs, g)
            if snip and (
                _inject_before_docclass(ctx, snip)
                if pre
                else _inject_after_docclass(ctx, snip)
            ):
                done.append(
                    "pre-docclass guard injected" if pre else "guard seed injected"
                )
    if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
        done.append("polyfill injected")
    if spec.get("polyfill_pre") and _inject_before_docclass(
        ctx, str(spec["polyfill_pre"])
    ):
        done.append("pre-docclass polyfill injected")
    if not done:
        return False, f"cs-fix spec for {cs} applied nothing"
    return True, "; ".join(done)
