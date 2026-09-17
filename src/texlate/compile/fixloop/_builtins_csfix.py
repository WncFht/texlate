r"""_builtins_csfix — undefined_cs/already_def 按 cs 名打靶修复原语 (C3 拆分)。

``cs_targeted_fix``: cs→修复表 (strip_pkg/usepackage/cs_map/polyfill 组合序,
``engines.{eng}`` 子表覆盖) + glue-残骸前缀拆分兜底; ``undefine_for_redef``:
already_def ``\\let\\X\\@undefined`` 让位注入 (寄存器/盒型分配名护栏)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _drop_pkg_loads,
    _inject_after_docclass,
    _map_tex_files,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: undefined_cs → 定向修复表 (cs_targeted_fix 的默认表, rules/
#: params.cs_table 可扩)。spec 键: strip_pkg / usepackage / cs_map /
#: polyfill / engines{eng: 覆盖 spec} —— 组合语义见 cs_targeted_fix。
_CS_FIX_TABLE: dict[str, dict[str, Any]] = {
    # 1909.05039: breakurl 的 shipout 钩调 \headerps@out —— 该宏只在
    # hyperref dvips/ps2pdf 驱动下有定义, xetex/tectonic 走 hdvipdfm →
    # 未定义即炸。breakurl 对 pdf 直出引擎本就无意义, 剥装载点是根修。
    "headerps@out": {"strip_pkg": "breakurl"},
    # 2301.01267: \mathbbm ← bbm。xelatex/TL2026 装 bbm-macros 即可;
    # tectonic 侧 bbm 是 MF-only 死路 (font_sub_shim 同族) → 换 dsfont\mathds。
    "mathbbm": {
        "usepackage": "bbm",
        "engines": {
            "tectonic": {
                "strip_pkg": "bbm",
                "usepackage": "dsfont",
                "cs_map": {"mathbbm": "mathds"},
            }
        },
    },
}


def _rewrite_cs_map(t: str, cmap: dict[str, str]) -> tuple[str, int]:
    r"""``\old``→``\new`` 逐对改写 (词边界定) → (新文本, 是否改动)。"""
    nt = t
    for old, new in cmap.items():
        nt = re.sub(rf"\\{old}\b", rf"\\{new}", nt)
    return nt, int(nt != t)


def _ensure_usepackage(ctx: LoopCtx, eng: Engine, pkg: str) -> list[str]:
    r"""主文件 ``\documentclass`` 后注入 ``\usepackage{pkg}`` + 装文件 → 已做事项。"""
    out = []
    if not re.search(
        rf"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(pkg)}\b",
        mask_tex(ctx.source_blob()),  # 注释掉的 %\usepackage 不算已装载
    ) and _inject_after_docclass(ctx, f"\\usepackage{{{pkg}}} % fixloop: cs-fix"):
        out.append(f"inject \\usepackage{{{pkg}}}")
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

    残余门: 大写起首或 ≤_SPLIT_REST_MAX 字符; ``@`` 含名是包内私有 cs
    (版本偏斜类), 非粘连残骸, 不拆。
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


def cs_targeted_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""undefined_cs 按 cs 修复表打靶 (handoff §2.2 cs→包表项)。

    spec 键组合序: ``strip_pkg`` 剥装载点 → ``usepackage`` 注入+装文件
    → ``cs_map`` ``\old``→``\new`` 逐文件改写 → ``polyfill`` 注原始 TeX body。
    ``engines.{eng_name}`` 子表整体覆盖顶层同名词 (引擎差异修, 如 bbm→dsfont)。
    payload 不在表 → 试 ``split_heads`` glue-残骸前缀拆分 (合成 cs_map 项);
    仍不中 → False 落 undefined_cs_guess。
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
    spec.update((base.get("engines") or {}).get(ctx.engine_name) or {})
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
    if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
        done.append("polyfill injected")
    if not done:
        return False, f"cs-fix spec for {cs} applied nothing"
    return True, "; ".join(done)


#: 寄存器/盒型分配的裸 cs 形 (plain/cls 内码常见): ``\newbox\splitbox``。
#: ``\newif\ifX`` 伴生 ``\Xtrue``/``\Xfalse``; ``*def`` 系 primitive 同把名
#: 绑进寄存器槽位——``\let\X\@undefined`` 后名被后载包抢占, 原 ``\setbox``/
#: ``\advance`` 点变 Missing number (2211.04482 aastex62 ``\splitbox`` 实证)。
_ALLOC_CS_RE = re.compile(
    r"\\(?:newbox|newcount|newdimen|newskip|newmuskip|newtoks|newread"
    r"|newwrite|newif|newinsert|newmarks|newfont|newlanguage"
    r"|chardef|mathchardef|countdef|dimendef|skipdef|muskipdef"
    r"|toksdef|font)\s*\\([A-Za-z@]+)"
)
#: LaTeX 花括号形: ``\newlength{\x}``/``\newsavebox{\x}`` 直给寄存器名;
#: ``\newcounter{c}`` 分配 ``\c@c``; ``\newboolean{b}`` 内部走 ``\newif\ifb``。
_ALLOC_BRACE_RE = re.compile(
    r"\\(newlength|newsavebox|newcounter|newboolean|provideboolean)"
    r"\s*\{\s*\\?([A-Za-z@]+)\s*\}"
)


def _allocated_cs_names(masked_blob: str) -> frozenset[str]:
    r"""遮盖视图上扫寄存器/盒型分配名集 (含 ``\newif``/``\newboolean`` 伴生)。"""
    names: set[str] = set()
    for m in _ALLOC_CS_RE.finditer(masked_blob):
        n = m.group(1)
        names.add(n)
        if n.startswith("if") and n[2:]:
            names.add(n[2:] + "true")
            names.add(n[2:] + "false")
    for m in _ALLOC_BRACE_RE.finditer(masked_blob):
        kind, n = m.group(1), m.group(2)
        if kind in ("newlength", "newsavebox"):
            names.add(n)
        elif kind == "newcounter":
            names.add("c@" + n)
        else:  # newboolean/provideboolean → \newif\ifn 同构
            names.add("if" + n)
            names.add(n + "true")
            names.add(n + "false")
    return frozenset(names)


def undefine_for_redef(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``already_def`` → ``\let\X\@undefined`` 让位注入 (寄存器护栏版)。

    原 regex_rewrite (order 113) 无脑 undefine——``\newbox\splitbox`` 被
    undefine 后 adjustbox 抢占名位, 类内后续 ``\setbox\splitbox`` 变
    Missing number (2211.04482 aastex62 实证)。payload cs 命中
    ``_ALLOC_CS_RE``/``_ALLOC_BRACE_RE`` 分配集 → abstain 交给后续规则
    /LLM; ``\newcommand``/``\def`` 形维持 ``\let\X\@undefined`` 原路径。
    """
    del eng, params
    cs = (payload or "").lstrip("\\")
    if not cs or not re.fullmatch(r"[A-Za-z@]+", cs):
        return False, "no usable cs payload"
    if cs in _allocated_cs_names(mask_tex(ctx.source_blob())):
        return False, f"\\{cs} is register/box-allocated, undefine unsafe"
    if _inject_after_docclass(
        ctx, f"\\makeatletter\\let\\{cs}\\@undefined\\makeatother"
    ):
        return True, f"undefine \\{cs} after documentclass"
    return False, "inject failed or already present"
