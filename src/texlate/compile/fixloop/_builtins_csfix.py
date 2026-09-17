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


def _fixloop_log(ctx: LoopCtx) -> str:
    """本轮编译 log 定位 (通用版, 无内容过滤)。

    ``{stem}.log`` (xelatex) → ``_tect_out/{stem}.log`` (tectonic)
    → 兜底首个非空 ``*.log``。misschar 域的 ``_compile_log_text`` 有
    Missing character 内容门, 非缺字扫描不可复用。
    """
    main = ctx.main_path()
    if main is not None:
        stem = main.stem
        for p in (
            ctx.wdir / f"{stem}.log",
            ctx.wdir / "_tect_out" / f"{stem}.log",
        ):
            if p.is_file() and (t := ctx.read(p)):
                return t
    for p in sorted(ctx.wdir.rglob("*.log")):
        if t := ctx.read(p):
            return t
    return ""


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


#: log 内 Command-形 already_def 撞名全扫 —— 三引号形同收:
#: ``Command \X already defined`` / ``Command `\X' already defined``
#: (老 ``\@ifdefinable`` 报错) / ``Command '\X' already defined`` (ltcmd)。
_ALREADY_DEF_CS_RE = re.compile(
    r"Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?\s+already\s+defined"
)

#: 再定义命令站点面 (site-prepend 清位目标) —— 只收"名必须未定义"族
#: (撞名才产 already_def): renewcommand/RenewDocumentCommand 要名已定义,
#: 前置 ``\let\@undefined`` 反使其炸; providecommand 族撞名静默不报错,
#: 清位反夺 cls 既有定义 —— 均不入列; ``\def``/``\newtheorem`` 系亦
#: 不产 Command 签。
_SITE_DEF_CMDS: tuple[str, ...] = (
    "newcommand",
    "DeclareRobustCommand",
    "NewDocumentCommand",
    "DeclareDocumentCommand",
    "DeclareMathAlphabet",
    "newmathalphabet",
    "NewMathAlphabet",
    "DeclareMathOperator",
)


def _redef_site_map(
    ctx: LoopCtx,
    site_re: re.Pattern[str],
    allocated: frozenset[str],
) -> dict[Any, set[str]]:
    """逐文件 live ``_SITE_DEF_CMDS`` 站点名集 (遮罩复核剔死区, 剔寄存器名)。"""
    out: dict[Any, set[str]] = {}
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f) or ""
        masked = mask_tex(t)
        names = {
            m.group(1)
            for m in site_re.finditer(masked)
            if masked[m.start() : m.end()] == t[m.start() : m.end()]
        } - allocated
        if names:
            out[f] = names
    return out


def _undefine_sites(
    ctx: LoopCtx,
    guilty: Iterable[Any],
    site_re: re.Pattern[str],
    targets: set[str],
) -> int:
    r"""Guilty 文件内 ``targets`` 站点前置 ``\let\X\@undefined`` → 改写文件数。

    遮盖命中文本逐字节复核剔死区 (``\iffalse``/verbatim), 上轮已
    prepend 的站点按 64 字前缀窗幂等跳过。catcode 包裹按文件类分:
    ``.cls``/``.sty`` 内 ``@`` 本是 letter —— 尾部 ``\makeatother``
    会把 @ 翻回 catcode-12, 插入点后全部 @-cs 烂掉 (1706.00221
    ``\define@key``→``\define``+``@key`` 级联实证) —— 裸 ``\let``
    不包裹; ``.tex`` 面才需 ``\makeatletter`` 对。
    """
    n_files = 0
    for f in guilty:
        t = ctx.read(f)
        if t is None:
            continue
        wrap = getattr(f, "suffix", "") == ".tex"
        masked = mask_tex(t)
        out: list[str] = []
        prev, n = 0, 0
        for m in site_re.finditer(masked):
            name = m.group(1)
            if name not in targets:
                continue
            if masked[m.start() : m.end()] != t[m.start() : m.end()]:
                continue  # 跨遮盖区命中 —— 死代码内站点不数不动
            if f"\\let\\{name}\\@undefined" in t[max(0, m.start() - 64) : m.start()]:
                continue  # 上轮已 prepend 过的站点
            out.append(t[prev : m.start()])
            if wrap:
                out.append(f"\\makeatletter\\let\\{name}\\@undefined\\makeatother\n")
            else:
                out.append(f"\\let\\{name}\\@undefined\n")
            prev = m.start()
            n += 1
        if not n:
            continue
        out.append(t[prev:])
        nt = "".join(out)
        if nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files


def undefine_for_redef(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``already_def`` → ``\let\X\@undefined`` 让位 (批量化 + 站点前置版)。

    撞名集 = payload ∪ 本轮 log ``Command \X already defined`` 全扫
    (``_ALREADY_DEF_CS_RE`` 三引号形; 含 ``@`` 的包内名滤除 —— 寄存器
    内码险区, ``\c@X`` 类分配名由 ``_allocated_cs_names`` 护栏再兜)。
    payload 非 cs 形或不在 log 撞名集 (Theorem-style 等非 Command 签名
    的 already_def payload) → 丢弃只信 log。

    双修形并施:
      1. 站点前置 —— 撞名站点所在文件 (guilty file) 内全部
         ``_SITE_DEF_CMDS`` 站点前插 ``\makeatletter\let\X\@undefined
         \makeatother``。halt_on_error 每轮 log 只见首撞名, 站点簇扩
         才是一轮清场的机制 (1206.0299: 6 名连撞单轮全清); 未撞名站点
         前置是语义无操作 (undefine+define≡define)。盖 doc 内双定义与
         "包在 docclass 之后才定义"的窗口 (astro-ph/0408445
         ``\DeclareMathAlphabet{\mathbfit}`` 撞 bm 包定义)。
      2. docclass 块 —— 只对证实撞名集 (payload∪log 扫描, 不扩站点
         兄弟) 早清位, 兜无站点可指的撞名 (包内互撞等)。

    ``params.min_batch`` (缺省 1) 门批量下限, 计数 = 撞名 ∪ guilty 文件
    站点名 (halt_on_error 下单撞名证据 + 同文件多站点即达批): order
    110.5 批规则传 2, 孤站单撞名格 (文件仅一处 ``\newcommand``) 让位
    renew(111) 已验证路径; payload=None (``other`` 类反引号签,
    taxonomy 不产 payload) 恒按 1 —— 该面无其他规则接手。
    """
    del eng
    log = _fixloop_log(ctx)
    scanned = {n for n in _ALREADY_DEF_CS_RE.findall(log) if "@" not in n}
    offenders: set[str] = set()
    cs = (payload or "").lstrip("\\")
    if cs and re.fullmatch(r"[A-Za-z@]+", cs) and (not scanned or cs in scanned):
        offenders.add(cs)
    offenders |= scanned
    allocated = _allocated_cs_names(mask_tex(ctx.source_blob()))
    had_names = bool(offenders)
    offenders -= allocated
    if not offenders:
        return False, (
            "all collided cs are allocated-register names — abstain"
            if had_names
            else "no collided cs to clear"
        )

    site_cmds = tuple(str(c) for c in (params.get("site_cmds") or _SITE_DEF_CMDS))
    site_re = re.compile(
        r"\\(?:" + "|".join(site_cmds) + r")\s*\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
    )
    site_map = _redef_site_map(ctx, site_re, allocated)
    guilty = [f for f, names in site_map.items() if names & offenders]
    expanded = set().union(*(site_map[f] for f in guilty)) if guilty else set()
    fire_set = offenders | expanded
    min_batch = 1 if payload is None else int(params.get("min_batch") or 1)
    if len(fire_set) < min_batch:
        return False, f"<{min_batch} collided+site-sibling cs — single path owns it"

    done: list[str] = []
    if guilty and expanded:
        n_sites = _undefine_sites(ctx, guilty, site_re, expanded)
        if n_sites:
            done.append(
                f"site-prepend \\let in {n_sites} file(s) for {len(expanded)} cs"
            )

    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    fresh = [n for n in sorted(offenders) if f"\\let\\{n}\\@undefined" not in main_t]
    if fresh:
        block = (
            "% fixloop: batch undefine for redefinition\n\\makeatletter\n"
            + "\n".join(f"\\let\\{n}\\@undefined" for n in fresh)
            + "\n\\makeatother"
        )
        if _inject_after_docclass(ctx, block):
            done.append(f"docclass block clears {len(fresh)} cs")
    if not done:
        return False, "all offenders already cleared"
    return True, "; ".join(done) + f" — {', '.join(sorted(fire_set))}"
