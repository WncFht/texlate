r"""builtins._csfix_sites — already_def 站点前置清位臂 (csfix 拆分)。

撞名站点 (``\newcommand`` 族/"名必须未定义"命令面) 所在文件前置
csname-let 清位串: ``_SITE_DEF_CMDS``/``_PROVIDE_SITE_CMDS`` 站点面,
``_endstar_name`` 恒拒名判 + ``_site_clear_line`` 分流
(end*×``\@ifdefinable`` 路由 → ``\@rc@ifdefinable`` 单发旁路),
``_redef_site_map``/``_undefine_sites`` 站点簇扩改写。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.common import (
    _let_cs,
    _live_matches,
    _splice,
    _undefine_cs,
)

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx


__all__ = [
    "_IFN_ROUTED_CMDS",
    "_PROVIDE_SITE_CMDS",
    "_RESERVED_UNDEFINABLE",
    "_SITE_DEF_CMDS",
    "_endstar_name",
    "_let_cs",
    "_live_matches",
    "_prepend_sites_in_text",
    "_redef_site_map",
    "_site_clear_line",
    "_splice",
    "_undefine_cs",
    "_undefine_sites",
]


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
#: ``\newfont{\X}{spec}`` (2.09/AMS 字体绑名, ``\@ifdefinable`` 恒拒
#: 产 Command 签; astro-ph/0307459 ``\Bbb`` 实证) 亦收 —— 裸形
#: ``\newfont\X`` 仍由 ``_ALLOC_CS_RE`` 分配名护栏剔出, 只花括号形入站点面。
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
    "newfont",
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
        "newfont",
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
    r"""站点前置串 (csname-let 形 —— 免 ``\makeatletter`` 对, 全宿主 catcode 安全)。

    None = 该 (命令, 名形) 组合不收站点 (``\providecommand`` 族非恒拒名)。
    ``\@ifdefinable`` 路由命令 × end* 名 → ``\@rc@ifdefinable`` 单发旁路;
    其余 → ``\let\X\@undefined`` 等价 csname 形 (名可含 ``@``)。
    """
    if cmd in _PROVIDE_SITE_CMDS and not _endstar_name(name):
        return None
    if _endstar_name(name) and cmd in _IFN_ROUTED_CMDS:
        return _let_cs("@ifdefinable", "@rc@ifdefinable")
    return _undefine_cs(name)


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
    # .bbl 亦收: 用户件 shipped .bbl 内的 \newcommand 站是同款"名必须
    # undefined"面 —— revtex4-1 rtx@thebibliography env-end \auto@bib@innerbib
    # 把 \jobname.bbl 二次 input, bbl 自体双 input 撞名 (1907.10621 \enquote
    # 实证); 锚在 \bibliography/\input 外侧的清位够不到 bbl 内互撞。
    for f in ctx.tex_files((".tex", ".sty", ".cls", ".bbl")):
        t = ctx.read(f) or ""
        names = (
            {
                m.group(2)
                for m in _live_matches(site_re, t)
                if _site_clear_line(m.group(1), m.group(2)) is not None
            }
            - allocated
            - _RESERVED_UNDEFINABLE
        )
        if names:
            out[f] = names
    return out


def _prepend_sites_in_text(
    t: str,
    site_re: re.Pattern[str],
    targets: set[str],
) -> tuple[str, int]:
    r"""单文件内 ``targets`` 站点前置清位串 → (新文本, 前置数)。

    前置形态由 ``_site_clear_line`` 按 (命令, 名形) 分流; 遮盖命中文本
    逐字节复核剔死区 (``\iffalse``/verbatim), 上轮已 prepend 的站点按
    128 字前缀窗幂等跳过 (新 csname 形与旧 ``\let\X\@undefined`` 形双查)。
    """
    edits: list[tuple[int, int, str]] = []
    for m in _live_matches(site_re, t):  # 跨遮盖区命中已剔 —— 死代码内站点不数不动
        name = m.group(2)
        if name not in targets:
            continue
        ins = _site_clear_line(m.group(1), name)
        if ins is None:
            continue  # 非恒拒名 provide 站点 —— 同 _redef_site_map 过滤
        window = t[max(0, m.start() - 128) : m.start()]
        if (
            ins in window
            or f"\\let\\{name}\\@undefined" in window  # 上轮旧形 emit
            or (
                _endstar_name(name) and "\\let\\@ifdefinable\\@rc@ifdefinable" in window
            )
        ):
            continue  # 上轮已 prepend 过的站点
        edits.append((m.start(), m.start(), ins + "\n"))  # 零宽插入 = prepend
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _undefine_sites(
    ctx: LoopCtx,
    guilty: Iterable[Any],
    site_re: re.Pattern[str],
    targets: set[str],
) -> int:
    r"""Guilty 文件内 ``targets`` 站点前置清位 → 改写文件数。

    前置形态按 (命令, 名形) 分流: ``\@ifdefinable`` 路由命令
    (``_IFN_ROUTED_CMDS``) × end* 恒拒名 → ``\@rc@ifdefinable`` 单发旁路
    (``\let\X\@undefined`` 对恒拒名是徒劳: 重定义侧仍过 ``\@ifdefinable``
    炸同一 already_def 签名, W151); 其余站点 → undefine 等价 csname 形
    (ltcmd ``\cs_if_exist`` 与 mathalphabet ``\csname``-freeze 检查均认
    其为 undefined)。

    csname 形零字面 ``@``, 全文件类统一裸前置 —— ``.cls``/``.sty`` 宿主
    @=letter、``.tex``/``.bbl`` 宿主 @=other、doc 自带 ``\makeatletter``
    区三语境同写; 旧 ``\makeatletter`` 对在 @=letter 宿主内会把尾段强翻
    回 12 (1803.02902 ``\widebar`` 体 ``\@ne`` 级联实证), 已退役。
    """
    n_files = 0
    for f in guilty:
        t = ctx.read(f)
        if t is None:
            continue
        nt, _n = _prepend_sites_in_text(t, site_re, targets)
        if nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files
