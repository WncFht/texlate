r"""_builtins_csfix — undefined_cs/already_def 按 cs 名打靶修复原语 (C3 拆分)。

``cs_targeted_fix``: cs→修复表 (strip_pkg/usepackage/cs_map/polyfill 组合序,
``engines.{eng}`` 子表覆盖) + glue-残骸前缀拆分兜底; ``undefine_for_redef``:
already_def ``\\let\\X\\@undefined`` 让位注入 (寄存器/盒型分配名护栏)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    PDFTEX_PRIMS,
    _drop_pkg_loads,
    _fixloop_log,
    _inject_after_docclass,
    _map_tex_files,
)
from texlate.compile.inject import find_docclass_ends
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
#: 不产 Command 签。DeclareMath{Symbol,Delimiter,Accent,Radical} 四件
#: 与 DeclareMathAlphabet 同走 ``\ifx\csname X\endcsname\relax`` 自有
#: 守卫 (latex.ltx:13462/13511/13594/13696 ``Command `\X' already
#: defined``, 非 ``\@ifdefinable``) —— ``\let\X\@undefined`` 清位有效。
#: DeclareSymbolFontAlphabet 不收: 其守卫查的是 space-后缀伴生名
#: ``\X␣`` (latex.ltx:13753-13763), 清 ``\X`` 本体是徒劳。
_SITE_DEF_CMDS: tuple[str, ...] = (
    "newcommand",
    "DeclareRobustCommand",
    "NewDocumentCommand",
    "DeclareDocumentCommand",
    "DeclareMathAlphabet",
    "newmathalphabet",
    "NewMathAlphabet",
    "DeclareMathSymbol",
    "DeclareMathDelimiter",
    "DeclareMathAccent",
    "DeclareMathRadical",
    "DeclareMathOperator",
)
#: ``\providecommand`` 族只收 end* 名站点: 非恒拒名撞名静默不产
#: already_def (前置清位反夺 cls 先定义 —— 不入 _SITE_DEF_CMDS 之理);
#: 但 undefined 态对 end* 名必走 ``\new@command`` → ``\@ifdefinable``
#: 恒炸 already_def (W151 ``\providecommand{\endproof}`` r1→r2 死循环
#: 实证), 此时 rc@ 前置恰保留 provide 语义 (defined→skip/undefined→define)。
_PROVIDE_SITE_CMDS: tuple[str, ...] = ("providecommand",)
#: ``\@ifdefinable`` 路由命令 —— end* 名站点前置换 ``\let\@ifdefinable
#: \@rc@ifdefinable`` 单发旁路 (kernel 内建同款, latex.ltx:1294
#: ``\renew@command`` / :1402 ``\declare@robustcommand@auxii``: rc@ 被
#: 消费时先还原 ``\@@ifdefinable`` 再续定义体 —— 恰放行紧邻一次
#: ``\@ifdefinable`` 调用后自愈, defined/undefined 两态皆过, 不泄检查面)。
#: ltcmd ``\NewDocumentCommand``/``\DeclareDocumentCommand`` 走
#: ``\cs_if_exist`` 无 end 守卫 (``\__cmd_check_end`` 只服务 env copy/show);
#: ``\DeclareMathAlphabet`` 族走自有 ``\ifx\csname X\endcsname\relax``
#: (``\csname`` 把 undefined 名冻结成 ``\relax`` → ``\let\X\@undefined``
#: 对其本就有效, fixprobe 实证) —— DeclareMath{Symbol,Delimiter,Accent,
#: Radical} 同此守卫 (latex.ltx:13505/13585/13455/13652 ``\expandafter
#: \ifx\csname\@gobble\string#1\endcsname\relax`` 形), 且 end* 名无
#: ``\@qend`` 拒径 (非 ``\@ifdefinable`` → 不查 ``\@qend``) —— 均不食
#: ``\@ifdefinable``, 前置 rc@ 会泄给下个用户 → 不入列。
_IFN_ROUTED_CMDS: frozenset[str] = frozenset(
    {
        "newcommand",
        "providecommand",
        "DeclareRobustCommand",
        "DeclareMathOperator",
    }
)
#: ``\@ifdefinable`` 双恒拒名形之二 (latex.ltx:1301 ``\@qrelax`` 全名形):
#: ``\relax`` 是 primitive —— ``\let\relax\@undefined`` 注毁其义, rc@ 旁路
#: 真把它重定义掉, 皆全局灾难 → 无安全清位路径, 与寄存器分配名同列弃修。
_RESERVED_UNDEFINABLE: frozenset[str] = frozenset({"relax"})


def _endstar_name(name: str) -> bool:
    r"""Cs 名 ``\@ifdefinable`` 恒拒形判定 (end* 前缀)。

    ``\@carcube`` 取名前 3 字符 = ``\@qend``("end") 即 ``\@notdefinable``
    (latex.ltx:1296-1305), 与该名是否已定义无关 —— ``\let\X\@undefined``
    清位后 ``\newcommand`` 族仍炸同一 already_def 签名。
    """
    return name.startswith("end")


def _site_clear_line(cmd: str, name: str) -> str | None:
    r"""站点前置串 (裸 ``\let`` 形, ``\makeatletter`` 包裹由调用方按文件类加)。

    None = 该 (命令, 名形) 组合不收站点 (``\providecommand`` 族非恒拒名)。
    ``\@ifdefinable`` 路由命令 × end* 名 → ``\@rc@ifdefinable`` 单发旁路;
    其余 → ``\let\X\@undefined``。
    """
    if cmd in _PROVIDE_SITE_CMDS and not _endstar_name(name):
        return None
    if _endstar_name(name) and cmd in _IFN_ROUTED_CMDS:
        return r"\let\@ifdefinable\@rc@ifdefinable"
    return f"\\let\\{name}\\@undefined"


def _redef_site_map(
    ctx: LoopCtx,
    site_re: re.Pattern[str],
    allocated: frozenset[str],
) -> dict[Any, set[str]]:
    r"""逐文件 live 站点名集 (遮罩复核剔死区, 剔寄存器/``\@qrelax`` 保留名)。

    ``site_re`` group(1)=命令名, group(2)=cs 名; ``\providecommand`` 族
    只收 ``_endstar_name`` 恒拒名形 (非恒拒名撞名静默, 前置清位反夺
    cls 先定义)。
    """
    out: dict[Any, set[str]] = {}
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f) or ""
        masked = mask_tex(t)
        names = (
            {
                m.group(2)
                for m in site_re.finditer(masked)
                if masked[m.start() : m.end()] == t[m.start() : m.end()]
                and _site_clear_line(m.group(1), m.group(2)) is not None
            }
            - allocated
            - _RESERVED_UNDEFINABLE
        )
        if names:
            out[f] = names
    return out


def _prepend_sites_in_text(
    t: str,
    masked: str,
    site_re: re.Pattern[str],
    targets: set[str],
    *,
    wrap: bool,
) -> tuple[str, int]:
    r"""单文件内 ``targets`` 站点前置清位串 → (新文本, 前置数)。

    前置形态由 ``_site_clear_line`` 按 (命令, 名形) 分流; 遮盖命中文本
    逐字节复核剔死区 (``\iffalse``/verbatim), 上轮已 prepend 的站点按
    64 字前缀窗幂等跳过。``wrap`` = ``.tex`` 面需 ``\makeatletter`` 对。
    """
    out: list[str] = []
    prev, n = 0, 0
    for m in site_re.finditer(masked):
        name = m.group(2)
        if name not in targets:
            continue
        ins = _site_clear_line(m.group(1), name)
        if ins is None:
            continue  # 非恒拒名 provide 站点 —— 同 _redef_site_map 过滤
        if masked[m.start() : m.end()] != t[m.start() : m.end()]:
            continue  # 跨遮盖区命中 —— 死代码内站点不数不动
        if ins in t[max(0, m.start() - 64) : m.start()]:
            continue  # 上轮已 prepend 过的站点
        out.append(t[prev : m.start()])
        out.append((f"\\makeatletter{ins}\\makeatother" if wrap else ins) + "\n")
        prev = m.start()
        n += 1
    if not n:
        return t, 0
    out.append(t[prev:])
    return "".join(out), n


def _undefine_sites(
    ctx: LoopCtx,
    guilty: Iterable[Any],
    site_re: re.Pattern[str],
    targets: set[str],
) -> int:
    r"""Guilty 文件内 ``targets`` 站点前置清位 → 改写文件数。

    前置形态按 (命令, 名形) 分流: ``\@ifdefinable`` 路由命令
    (``_IFN_ROUTED_CMDS``) × end* 恒拒名 → ``\let\@ifdefinable
    \@rc@ifdefinable`` 单发旁路 (``\let\X\@undefined`` 对恒拒名是徒劳:
    重定义侧仍过 ``\@ifdefinable`` 炸同一 already_def 签名, W151);
    其余站点 → ``\let\X\@undefined`` (ltcmd ``\cs_if_exist`` 与
    mathalphabet ``\csname``-freeze 检查均认其为 undefined)。

    catcode 包裹按文件类分: ``.cls``/``.sty`` 内 ``@`` 本是 letter ——
    尾部 ``\makeatother`` 会把 @ 翻回 catcode-12, 插入点后全部 @-cs
    烂掉 (1706.00221 ``\define@key``→``\define``+``@key`` 级联实证) ——
    裸 ``\let`` 不包裹; ``.tex`` 面才需 ``\makeatletter`` 对。
    """
    n_files = 0
    for f in guilty:
        t = ctx.read(f)
        if t is None:
            continue
        nt, _n = _prepend_sites_in_text(
            t,
            mask_tex(t),
            site_re,
            targets,
            wrap=getattr(f, "suffix", "") == ".tex",
        )
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
         end* 恒拒名形 (``\@ifdefinable`` ``\@qend`` 前缀拒, 与定义态
         无关) 在 ``\@ifdefinable`` 路由命令站点换 ``\@rc@ifdefinable``
         单发旁路; ``\providecommand`` 族站点只收该名形。
      2. docclass 块 —— 只对证实撞名集 (payload∪log 扫描, 不扩站点
         兄弟) 早清位, 兜无站点可指的撞名 (包内互撞等)。end* 名不入
         此块: 无站点可指时 ``\let\endX\@undefined`` 纯徒劳 (重定义侧
         仍恒拒) 且毁既有义 —— 弃修交下位规则。

    ``params.min_batch`` (缺省 1) 门批量下限, 计数 = 撞名 ∪ guilty 文件
    站点名 (halt_on_error 下单撞名证据 + 同文件多站点即达批): order
    110.5 批规则传 2, 孤站单撞名格 (文件仅一处 ``\newcommand``) 让位
    renew(111) 已验证路径 —— 但撞名集含 end* 名时恒按 1 (renew 对
    undefined-end* 的 ``\@ifundefined`` 报错在 halt_on_error 下同样
    卡死, 该名形不能让位); payload=None (``other`` 类反引号签,
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
    offenders -= _RESERVED_UNDEFINABLE
    if not offenders:
        return False, (
            "all collided cs are allocated/reserved names — abstain"
            if had_names
            else "no collided cs to clear"
        )

    site_cmds = tuple(str(c) for c in (params.get("site_cmds") or _SITE_DEF_CMDS))
    site_re = re.compile(
        r"\\("
        + "|".join((*site_cmds, *_PROVIDE_SITE_CMDS))
        + r")\s*\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
    )
    site_map = _redef_site_map(ctx, site_re, allocated)
    guilty = [f for f, names in site_map.items() if names & offenders]
    expanded = set().union(*(site_map[f] for f in guilty)) if guilty else set()
    fire_set = offenders | expanded
    min_batch = (
        1
        if payload is None or any(map(_endstar_name, fire_set))
        else int(params.get("min_batch") or 1)
    )
    if len(fire_set) < min_batch:
        return False, f"<{min_batch} collided+site-sibling cs — single path owns it"

    done: list[str] = []
    if guilty and expanded:
        n_sites = _undefine_sites(ctx, guilty, site_re, expanded)
        if n_sites:
            done.append(
                f"site-prepend guards in {n_sites} file(s) for {len(expanded)} cs"
            )

    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    fresh = [
        n
        for n in sorted(offenders)
        if not _endstar_name(n) and f"\\let\\{n}\\@undefined" not in main_t
    ]
    if fresh:
        block = (
            "% fixloop: batch undefine for redefinition\n\\makeatletter\n"
            + "\n".join(f"\\let\\{n}\\@undefined" for n in fresh)
            + "\n\\makeatother"
        )
        if _inject_after_docclass(ctx, block):
            done.append(f"docclass block clears {len(fresh)} cs")
    if not done:
        endstar = sorted(n for n in offenders if _endstar_name(n))
        if endstar:
            return False, (
                f"end*-name offenders {', '.join(endstar)} have no "
                "\\@ifdefinable-routed site — \\let\\X\\@undefined is futile "
                "for always-rejected names, defer"
            )
        return False, "all offenders already cleared"
    return True, "; ".join(done) + f" — {', '.join(sorted(fire_set))}"


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
    fresh = [n for n in sorted(names) if f"\\let\\{n}\\@undefined" not in main_t]
    if not fresh:
        return False, "all offenders already cleared"
    block = (
        "% fixloop: ctlseq undefine before CJK block\n\\makeatletter\n"
        + "\n".join(f"\\let\\{n}\\@undefined" for n in fresh)
        + "\n\\makeatother"
    )
    if not _inject_after_docclass(ctx, block):
        return False, "docclass seam injection failed"
    return True, f"seam-clear {', '.join(fresh)} (files: {', '.join(sorted(files))})"


# ═══ pdfstring 字母常量扫描肇事 cs 空降格 (W165, 2607.10569) ═══

#: ``Improper alphabetic constant`` 行后紧随的 ``<to be read again>``
#: 展示行给出肇事 token——pdfstring/书签域 `` `\cs `` 字母常量扫描只炸
#: 多字符 cs (`` `\x `` 单字符是合法字母常量形, TeX 不报)。
_ALPHA_BAD_CS_RE = re.compile(
    r"Improper alphabetic constant\.\s*\n<to be read again>\s*\n? *(\\[A-Za-z@]+)"
)


def pdfstring_cs_disarm(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""`` `\cs `` pdfstring 字母常量扫描炸 → 肇事 cs 书签域 ``\def`` 空降格。

    触发面: ``$\\times$``/``$\\pdo$`` 类数学进 ``\title``/``\section``/
    ``\author`` 等 moving-arg——hyperref ``\pdfstringdef`` 展开书签时
    `` `\cs `` 扫描撞多字符 cs + intcalc 级联 (acmart+hyperref+xelatex
    上游脆面, 与类无关; tmp/lane-pdo 最小复现 ``$\times$`` in ``\title``)。
    上游文档化逃生舱 ``\pdfstringdefDisableCommands`` 只动书签域——
    正文排版零接触, 比 ``\texorpdfstring`` 逐处包源干净一个量级;
    ``\def\cs{}`` 空降格顺带消掉 "removing `\cs'" 警告 (cs 在展开期
    已消失)。注入走 docclass 缝+``\ifdefined`` 双闸: hyperref 缺席稿
    整件死文本不炸。
    """
    del eng, payload, params
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names = sorted(
        {
            n
            for n in _ALPHA_BAD_CS_RE.findall(blob)
            if len(n) > 2  # noqa: PLR2004 - 2 = 反斜杠+单字符合法形 (\x) 滤界
        }
    )
    if not names:
        return False, "no multi-char cs behind Improper alphabetic constant"
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main) or ""
    todo = [n for n in names if f"\\def{n}{{}}" not in t]
    if not todo:
        return False, "offenders already disarmed"
    defs = "".join(f"\\def{n}{{}}" for n in todo)
    snippet = (
        "\\ifdefined\\pdfstringdefDisableCommands\n"
        f"  \\pdfstringdefDisableCommands{{{defs}}}\n"
        "\\fi"
    )
    if not _inject_after_docclass(ctx, snippet):
        nt = t.replace("\\begin{document}", snippet + "\n\\begin{document}", 1)
        if nt == t:
            return False, "no injection point"
        ctx.write(main, nt)
    return True, f"pdfstring-disarm {', '.join(todo)}"


# ═══ phantom Incomplete \if — 脆弱前稿 cs 族 eTeX \protected 重定义 (B05 姊妹臂) ═══

#: 展开态 phantom 链的宿主面: frontmatter/moving-arg 里常被 ``\edef``/
#: ``\xdef``/``\MakeUppercase``/``\pdfstringdef`` 展开的 cs——``\footnote``/
#: ``\thanks`` (amsproc ``\shortauthors`` → ``\markboth`` edef 实证) +
#: 2.09 字体声明 ``\bf\it\rm\sf\tt\sc\sl`` (myectaart ``\xdef\@argi{#1}``
#: 实证)。保护后其 ``\newif``-setter 替换体里的 ``\if@X\iffalse`` 不再被
#: 执行——未定义名经 ``\ifdefined`` 闸跳过, 不造新坏定义。
_IFPROT_FAMILY: tuple[str, ...] = (
    "footnote",
    "thanks",
    "bf",
    "it",
    "rm",
    "sf",
    "tt",
    "sc",
    "sl",
)

#: 字面扫描器已跑过的凭据: ``unclosed_if_close`` (order 196) 的 run_tool
#: note 固定带 ``ifclose:`` 判词 (``noop``/``injected`` 皆证"本轮已查字面
#: 平衡")。该凭据缺席 = 扫描器 cond-skip (python3 缺位) 或 order 未达——
#: 字面亏格可能悬着, 本规则的 ``\protected`` 域不含它, 保守不收。
_IFPROT_SCANNER_RULE = "unclosed_if_close"


def if_phantom_protect(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Phantom ``Incomplete \if`` → 脆弱前稿 cs 族 ``\protected`` let-wrap 重定义。

    phantom 机制: ``\let\if@X\iffalse`` 形 ``\newif``-setter 的替换体含活
    conditional——``\edef``/``\xdef`` 展开扫描里 ``\let`` 惰性但 ``\if@X``
    (=\iffalse) 执行 → 假 open 吞 token 到 EOF。源件字面平衡 → 196 号
    字面扫描器 noop (applied 烧 dedup 位后下轮才轮到本规则)。eTeX
    ``\protected`` 属性钉在 cs 自身, 不受 ``\let\protect\relax`` 剥除影响
    (``\DeclareRobustCommand`` 的死穴) → 被护 cs 在 edef 扫描内整体带过,
    setter 链根本走不到。正文体正常展开域里 wrapper 逐跳还原旧义, 语义
    零变化 (min8 ``\protected\def\footnote`` / t2 ``\bf`` 双臂已实证出 PDF)。

    注入 ``\AtBeginDocument`` 块 (docclass 缝): 全 preamble+包重定义
    (hyperref 改 ``\footnote`` 等) 跑完才护, 不被反超; ``\maketitle`` 内
    edef 触发时保护已就位。逐 cs ``\ifdefined`` 闸。
    """
    del eng, payload
    fam = tuple(str(c).lstrip("\\") for c in (params.get("cs") or _IFPROT_FAMILY))
    if not fam:
        return False, "empty cs family"
    seen = any(
        a.get("rule") == _IFPROT_SCANNER_RULE and "ifclose:" in str(a.get("detail"))
        for a in ctx.actions
    )
    if not seen:
        return False, "literal if-scanner verdict not on ledger — abstain"
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    # 退文件头 = cls 加载前, \AtBeginDocument 未定义 → 必须有 docclass 缝
    if not find_docclass_ends(ctx.read(main) or ""):
        return False, "no docclass seam"
    lines = "".join(
        f"\\ifdefined\\{n}\\let\\TXLorig{n}\\{n}"
        f"\\protected\\def\\{n}{{\\TXLorig{n}}}\\fi\n"
        for n in fam
    )
    snippet = (
        "% fixloop: phantom Incomplete \\if — \\protected frontmatter cs\n"
        "\\AtBeginDocument{%\n" + lines + "}"
    )
    if not _inject_after_docclass(ctx, snippet):
        return False, "protected re-defs already injected"
    return True, f"protected {len(fam)} frontmatter cs ({', '.join(fam)})"
