r"""builtins.csfix.redef — ``undefine_for_redef`` utilisation (csfix 拆分)。

already_def ``\let\X\@undefined`` 让位批处理: log 全扫撞名 +
站点前置/装载点前置/钩臂/docclass 块四修形并施 (各臂在
``csfix.sites``/``csfix.pkg``/``csfix.abd`` 兄弟叶)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _inject_after_docclass,
    _undefine_cs,
)
from texlate.compile.fixloop.builtins.csfix.abd import _abd_hook_clear
from texlate.compile.fixloop.builtins.csfix.alloc import _allocated_cs_names
from texlate.compile.fixloop.builtins.csfix.pkg import (
    _pkg_err_stems,
    _undefine_pkg_sites,
)
from texlate.compile.fixloop.builtins.csfix.sites import (
    _PROVIDE_SITE_CMDS,
    _RESERVED_UNDEFINABLE,
    _SITE_DEF_CMDS,
    _endstar_name,
    _redef_site_map,
    _undefine_sites,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine


__all__ = [
    "_ALREADY_DEF_CS_RE",
    "_fixloop_log",
    "undefine_for_redef",
]


#: log 内 Command-形 already_def 撞名全扫 —— 三引号形同收：
#: ``Command \X already defined`` / ``Command `\X' already defined``
#: (老 ``\@ifdefinable`` 报错) / ``Command '\X' already defined`` (ltcmd)。
_ALREADY_DEF_CS_RE = re.compile(
    r"Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?\s+already\s+defined"
)


def undefine_for_redef(  # noqa: C901 - 四修形并施 + 护栏逐门，分派即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``already_def`` → ``\let\X\@undefined`` 让位 (批量化 + 站点前置版)。

    撞名集 = payload ∪ 本轮 log ``Command \X already defined`` 全扫
    (``_ALREADY_DEF_CS_RE`` 三引号形; 含 ``@`` 的包内名滤除 —— 寄存器
    内码险区, ``\c@X`` 类分配名由 ``_allocated_cs_names`` 护栏再兜)。
    payload 非 cs 形或不在 log 撞名集 (Theorem-style 等非 Command 标记
    的 already_def payload) → 丢弃只信 log。

    四修形并施:
      1. 站点前置 —— 撞名站点所在文件 (guilty file, 含 shipped .bbl) 内
         全部 ``_SITE_DEF_CMDS`` 站点前插 csname-let 清位串。halt_on_error
         每轮 log 只见首撞名, 站点簇扩
         才是一轮清场的机制 (1206.0299: 6 名连撞单轮全清); 未撞名站点
         前置是语义无操作 (undefine+define≡define)。盖 doc 内双定义与
         "包在 docclass 之后才定义"的窗口 (astro-ph/0408445
         ``\DeclareMathAlphabet{\mathbfit}`` 撞 bm 包定义) 与 .bbl 自体
         双 input 撞名 (revtex4-1 ``\auto@bib@innerbib`` 再 input
         ``\jobname.bbl``, 1907.10621 ``\enquote``)。end* 恒拒名形
         (``\@ifdefinable`` ``\@qend`` 前缀拒, 与定义态无关) 在
         ``\@ifdefinable`` 路由命令站点换 ``\@rc@ifdefinable`` 单发旁路;
         ``\providecommand`` 族站点只收该名形。
      2. 包装载点前置 —— file:line 形错误行抽肇事包茎, 其每个用户件
         ``\usepackage``/``\RequirePackage`` 装载点 (opts/逗号列/dup
         站全收) 前清位。报错包恒为后定义者 → 序恒正确, 修 docclass
         块鞭长莫及的 "preamble 包先定义, 后载包再定义" 互撞
         (bbkresid: newtxmath→amssymb ``\Bbbk`` 同型 4 格)。end* 名
         不入此臂: ``\let\X\@undefined`` 对恒拒名徒劳, rc@ 旁路又不能
         跨包体前置 (会被包内首个 ``\@ifdefinable`` 调用消费错目标)。
      3. ``\AtBeginDocument`` 钩臂 —— 错误归因行 = live ``\begin{document}``
         → 后定义者在 pkg/cls 注册的钩体内 (babel .ldf
         ``\DeclareMathOperator`` 族), 一切立即 ``\let`` 恒错序。声明点
         行前注 ``\AtBeginDocument{\let\X\@undefined}`` —— 钩 FIFO, 先注册
         先清位, 迟延定义者再定义赢 (1706.00033 ``\sh``)。无任何声明点
         → 不接管。
      4. docclass 块 —— 只对证实撞名集 (payload∪log 扫描, 不扩站点
         兄弟) 早清位, 兜无站点可指的撞名 (cls 内传递装载等)。装载点
         前置/钩臂已覆盖的名不入此块; end* 名亦不入: 无站点可指时
         ``\let\endX\@undefined`` 纯徒劳 (重定义侧仍恒拒) 且毁既有义 ——
         弃修交下位规则。

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

    cs_stems = {
        n: s
        for n, s in _pkg_err_stems(log).items()
        if n in offenders and not _endstar_name(n)
    }
    pkg_covered: set[str] = set()
    if cs_stems:
        n_load, pkg_covered = _undefine_pkg_sites(ctx, cs_stems)
        if n_load:
            done.append(
                f"pkg-load-site clears {len(pkg_covered)} cs "
                f"at {n_load} usepackage site(s)"
            )

    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    # \AtBeginDocument 迟延定义者臂 —— 机制见 _abd_hook_clear。
    abd = _abd_hook_clear(ctx, main_t, offenders, (ctx.err_head or "") + "\n" + log)
    if abd:
        done.append(f"AtBeginDocument hook clears {len(abd)} deferred cs")

    fresh = [
        n
        for n in sorted(offenders)
        if not _endstar_name(n)
        and n not in pkg_covered
        and n not in abd
        and f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if fresh:
        block = "% fixloop: batch undefine for redefinition\n" + "\n".join(
            _undefine_cs(n) for n in fresh
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
