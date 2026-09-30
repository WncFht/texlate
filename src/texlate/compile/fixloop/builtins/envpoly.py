r"""builtins.envpoly — undefined env 守卫式 noop 批注 (builtins.shim C3 再拆叶)。

``Environment X undefined`` → proven (payload ∪ log 全扫) 与
"``\begin`` 在用 ∧ 无 in-doc 定义证据" 批扩面一轮全清:
``\ifcsname`` 守卫 ``\newenvironment`` noop 在 ``\begin{document}``
前注入 (数学 env 给 ``\[\..\]`` 壳); 三附臂 —— ``params.pkg_map``
命中 env 装真包替 noop / live ``\renewenvironment`` 站点行首前置守卫 /
``_ENV_COMPANIONS`` 对偶件 (proof→``\QED``) 同块补。单入口
``undefined_env_polyfill``。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _inject_after_docclass,
    _inject_before_begindoc,
    _is_live,
)
from texlate.compile.fixloop.builtins.csfix import _ensure_usepackage
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# o2-builtin-cs 面 (m1b-residue-routes-2026-09-17): env_undefined
# polyfill / AMS 上古字体 cs shim / produced-by-cs 缺字 cs_rebind
# ════════════════════════════════════════════════════════════════

#: log 内 env_undefined 签名 —— ``LaTeX Error: Environment X undefined``。
_ENV_UNDEF_RE = re.compile(r"Environment\s+([A-Za-z@*]+)\s+undefined")

#: ``\begin/\end{env}`` 使用面扫 (单遍全取)。
_ENV_USE_RE = re.compile(r"\\(?:begin|end)\s*\{\s*([A-Za-z@*]+)\s*\}")

#: in-doc 环境定义证据 —— ``\newenvironment``/``\newtheorem``/xparse 族 +
#: ``\def\e``/``\def\ende``/``\let\e`` 裸绑。命中即不扩 (可能是活定义;
#: 死块证据最多迟一轮, 由 log-proven 路径接回)。
_ENV_DEF_RE = re.compile(
    r"\\(?:new|renew)environment\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\(?:newtheorem|declaretheorem)\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\(?:Declare|New|Renew|Provide)DocumentEnvironment\s*\{\s*([A-Za-z@*]+)\s*\}"
    r"|\\def\\(?:end)?([A-Za-z@*]+)\b|\\let\\(?:end)?([A-Za-z@*]+)\b"
)

#: 内核/近全类通用环境 —— 批扩 cosmetic 降噪表 (守卫行本就语义无操作,
#: 漏列只多一行守卫不坏事; 真缺时 log-proven 路径照样兜回)。amsmath
#: 数学环境故意不收 —— 缺 amsmath 正是要 ``\[..\]`` 壳救的面。
_KERNEL_ENVS: frozenset[str] = frozenset(
    {
        "abstract",
        "array",
        "center",
        "description",
        "displaymath",
        "document",
        "enumerate",
        "eqnarray",
        "eqnarray*",
        "equation",
        "equation*",
        "figure",
        "figure*",
        "filecontents",
        "filecontents*",
        "flushleft",
        "flushright",
        "itemize",
        "letter",
        "list",
        "math",
        "minipage",
        "picture",
        "quotation",
        "quote",
        "samepage",
        "tabular",
        "tabular*",
        "thebibliography",
        "theindex",
        "titlepage",
        "trivlist",
        "verbatim",
        "verbatim*",
        "verse",
    }
)


def _env_noop_line(env: str) -> str:
    r"""``\ifcsname`` 守卫的 noop ``\newenvironment`` 行; 数学 env 给 ``\[..\]`` 壳。"""
    pre, post = (r"\[", r"\]") if env in MATH_ENVS else ("", "")
    return (
        rf"\ifcsname {env}\endcsname\else"
        rf"\newenvironment{{{env}}}{{{pre}}}{{{post}}}\fi"
    )


#: env polyfill 对偶件表 —— env 名 → (源内使用证据 rx, 同补 stub 行)。
#: 缺 proof env 的稿多伴 ``\QED`` 收尾标记 (amsthm 对偶件; 0707.1588
#: IEEEtran 实证: proof noop 后 ``undefined_cs:QED`` 即浮面) —— polyfill
#: proof 同轮补 ``\providecommand{\QED}`` 省一轮。stub 形 = amsthm
#: ``\qedsymbol`` 纯原语开口盒, 不依赖 amssymb ``\square``。
_ENV_COMPANIONS: dict[str, tuple[str, str]] = {
    "proof": (
        r"\\QED\b",
        (
            r"\providecommand{\QED}{\leavevmode\hbox to.77778em{\hfil\vrule"
            r"\vbox to.675em{\hrule width.6em\vfil\hrule}\vrule}}"
        ),
    ),
}


#: renew 族环境再定义站点 —— ``\renewenvironment{X}`` 对未定义 env 报同一
#: ``Environment X undefined`` 签 (0806.0904/0806.2953 ``\renewenvironment{proof}``
#: 于 preamble :743 实证, pre-begindoc 注入 :1069 晚 325 行救不到);
#: 须在站点行首前置守卫 noop 让 renew 的 ``\@ifundefined`` 闸通过, renew 随
#: 即以稿自带定义覆盖 noop —— 比批扩位多保住 renew 语义。xparse
#: ``\RenewDocumentEnvironment`` 未定义时报 ``cmd Error`` 异签 (不产本类
#: payload), 同名站点同面顺手覆盖。
_RENEW_ENV_SITE_RE = re.compile(
    r"\\(?:renewenvironment|RenewDocumentEnvironment)"
    r"\s*\*?\s*\{\s*([A-Za-z@*]+)\s*\}"
)


def _live_renew_sites(t: str, envs: set[str]) -> dict[str, int]:
    r"""``envs`` 各名在 ``t`` 的首个 live renew 站点偏移 (env→pos)。

    遮盖 span 复核剔注释/verbatim 死区; 其后同名站点见到的 env 已被
    首站点 renew 定义, 无需再前置。
    """
    masked = mask_tex(t)
    sites: dict[str, int] = {}
    for m in _RENEW_ENV_SITE_RE.finditer(masked):
        name = m.group(1)
        if name not in envs or name in sites:
            continue
        if not _is_live(m, masked, t):
            continue  # 注释/verbatim 死区内站点不动
        sites[name] = m.start()
    return sites


def _prepend_env_renew_sites(
    ctx: LoopCtx, envs: set[str], companions: dict[str, str]
) -> set[str]:
    r"""``envs`` 的 live renew 站点行首前置 ``\ifcsname`` noop → 已处理 env 集。

    行首锚 —— 站点裹 ``\AtBeginDocument``/宏参死块时前置仍落活区且先于
    执行点; 站点在 body 内同样覆盖 (renew 合法出现在任何位置)。
    ``companions`` (env→stub 行, 调用方已按源内使用证据过滤) 随 noop
    同块下落 —— 站点多在 preamble, ``\QED`` 类对偶件若被序言调用
    同样够得着。``ins in nt[:pos]`` 幂等: 上轮前置或 pre-begindoc 批块
    行已先于站点者不再重复 (批块在 preamble 站点之后, 不误伤本轮需求)。
    """
    done: set[str] = set()
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        sites = _live_renew_sites(t, envs)
        if not sites:
            continue
        nt = t
        # 降序插 —— 先动高偏移站点, nt[:pos] 对已处理插入免疫
        for name, pos in sorted(sites.items(), key=lambda kv: -kv[1]):
            ins = _env_noop_line(name)
            if ins in nt[:pos]:
                continue
            block = ins + " % fixloop: pre-renew noop\n"
            if comp := companions.get(name):
                block += comp + "\n"
            at = nt.rfind("\n", 0, pos) + 1
            nt = nt[:at] + block + nt[at:]
            done.add(name)
        if nt != t:
            ctx.write(f, nt)
    return done


def _serve_env_pkg_map(
    ctx: LoopCtx,
    eng: Engine,
    proven: set[str],
    pkg_map: dict[str, Any],
) -> tuple[set[str], list[str]]:
    """env→pkg 臂: 表内 proven env 装真包/注 polyfill → (served, notes)。"""
    notes: list[str] = []
    served: set[str] = set()
    for e in sorted(proven & set(pkg_map)):
        spec = pkg_map.get(e) or {}
        dones: list[str] = []
        if use := spec.get("usepackage"):
            dones.extend(_ensure_usepackage(ctx, eng, str(use)))
        if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
            dones.append("pkg polyfill injected")
        if dones:
            notes.append(f"{e}→pkg {'; '.join(dones)}")
            served.add(e)
    return served, notes


def undefined_env_polyfill(  # noqa: C901  # pkg_map/站点/对偶件/批扩多臂 dispatcher
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Environment X undefined`` → ``\begin{document}`` 前 ``\newenvironment`` noop。

    proven = payload ∪ 本轮 log ``Environment X undefined`` 全扫。
    halt_on_error 每轮只见首缺 env (1012.1059 8 env 同缺实测) ——
    批扩到 "blob 内 ``\begin/\end`` 在用 ∪ 无 in-doc 定义证据" 的
    全 env 面, 一轮全清: ``\ifcsname`` 守卫在 pre-begindoc 注入位对
    包/类已定义名自动死化, 真缺名拿 noop (数学 env 给 ``\[..\]`` 壳)。
    修复面: svjour/siamltex/aasms4 等老类不产现内核定理环境, 或定义躺
    ``\\ifnfssone``/``\\doit{0}`` 死条件块 (math/0104275 tcilatex 族)。
    ``params.deny`` (缺省 ``document``) 排不可 noop 化的环境名。

    env→pkg 臂 (``params.pkg_map``, 1306.0281 tikzpicture 族): 表内
    proven env 装真包替代 noop —— noop 吞整个图体且体内 pgf cs
    (``\node``/``\draw``/``\addplot``) 连锁 undefined_cs 白烧轮次,
    cs_table 无对应条目者 (axis/tikzcd) 更是唯一活路。spec 复用
    cs_targeted_fix 键形: ``usepackage`` 走 ``_ensure_usepackage``
    (注入+装文件); ``polyfill`` 注 docclass 缝后且须自足
    ``\usepackage{pkg}`` 前缀 —— 注缝 LIFO 下裸 ``\usetikzlibrary``
    会落在臂注入 usepackage 行之前 → 新 undefined_cs (95-targeted
    cs_table tikz 族头注同机理)。命中 env 出 noop/站点/批扩全池:
    真包就位后 ``\ifcsname`` 守卫自然死化, 双份注入无谓。

    站点前置臂 (0806.0904/0806.2953): proven env 若带 live
    ``\renewenvironment{X}`` 站点 (序言或正文皆可), 在站点行首前置同款
    守卫 noop —— renew 报错点先于 pre-begindoc 位, 批扩够不到; 前置后
    renew 闸通过并以稿自带定义覆盖 noop。站点臂处理的 env 不再占
    ``\begin``-used 门 (renew 本身即消费点); 站点在主文件者自动出
    fresh 批块 (``\ifcsname`` 已落盘), 在他文件者批块照注兜底
    (站点文件可能不被 ``\input`` 抵达, 双保险不误伤)。

    对偶件臂 (``_ENV_COMPANIONS``, 0707.1588): proof 被 polyfill 且源内
    ``\QED`` 在用 → 同块补 ``\providecommand{\QED}`` (amsthm 对偶件,
    缺 proof env 的稿多伴此标记); 独立 ``undefined_cs:QED`` (proof 已
    定义稿) 由 cs_targeted_fix ``cs_table.QED`` polyfill 兜。
    """
    proven: set[str] = set()
    if payload and re.fullmatch(r"[A-Za-z@*]+", payload):
        proven.add(payload)
    proven.update(_ENV_UNDEF_RE.findall(_fixloop_log(ctx)))
    deny = {str(d) for d in (params.get("deny") or ())} | {"document"}
    proven -= deny
    if not proven:
        return False, "no undefined env to polyfill"
    # blob 须在注入前取 —— 对偶件证据 (``\QED`` 在用) 与 defined 判
    # 都不能看见自己即将注入的行 (stub 文本含 ``\QED`` 字面会自证)。
    blob = mask_tex(ctx.source_blob())
    served, notes = _serve_env_pkg_map(ctx, eng, proven, params.get("pkg_map") or {})
    proven -= served
    companions = {
        e: _ENV_COMPANIONS[e][1]
        for e in proven
        if e in _ENV_COMPANIONS and re.search(_ENV_COMPANIONS[e][0], blob)
    }
    # renew 站点前置先行 —— preamble ``\renewenvironment{X}`` 的报错点在
    # pre-begindoc 注入位之前, 批扩永远够不到 (0806.0904/0806.2953);
    # 站点消费点注入后 renew 以稿自带定义覆盖 noop, 语义优于批扩 noop。
    site_envs = _prepend_env_renew_sites(ctx, proven, companions)
    used = set(_ENV_USE_RE.findall(blob)) - deny
    if not (proven & used) and not site_envs:
        if notes:
            return True, "; ".join(notes)
        return False, f"env(s) {sorted(proven)} not \\begin-used in source"
    defined = {n for m in _ENV_DEF_RE.finditer(blob) for n in m.groups() if n}
    targets = (proven & used) | (used - defined - _KERNEL_ENVS) - served
    main = ctx.main_path()
    main_masked = mask_tex(ctx.read(main) or "") if main is not None else ""
    fresh = [
        e for e in sorted(targets) if f"\\ifcsname {e}\\endcsname" not in main_masked
    ]
    if site_envs:
        notes.append(f"pre-renew noop: {', '.join(sorted(site_envs))}")
    if fresh:
        lines = ["% fixloop: undefined env polyfill (noop env)"]
        for e in fresh:
            lines.append(_env_noop_line(e))
            if e in companions:
                lines.append(companions[e])
        if _inject_before_begindoc(
            ctx, "\n".join(lines), strict_first=True, fallback=_inject_after_docclass
        ):
            notes.append(f"env polyfill: {', '.join(fresh)}")
    if not notes:
        return False, "undefined envs already polyfilled"
    return True, "; ".join(notes)
