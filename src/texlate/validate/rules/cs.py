r"""validate.rules.cs — 控制序列安全规则域叶 (validate.rules 域缝叶)。

五族 cs 级注入/丢失判定：``_check_macro`` 双向 diff（zh 新增全档
error——结构族/非 ASCII 融合 cs 同档；src 丢失方向脆弱间距命令
计数差 cs_dropped 升硬判据、其余 warn）、``_check_item_glue``
``\\item``+ASCII 字母粘合签名、``_check_ph_in_cs`` 占位符嵌 cs 名
双侧夹持签名、``_check_bare_cs`` 裸 cs 两子类（数学域外数学 cs +
前缀+大写后缀粘合，与 macro 泛条目有意分层双报）、
``_check_dangerous_cs`` ``DANGEROUS_CS`` 表名净差（IO/定义覆写/
catcode/装包逃逸族）。判定口径单源 ``textutil.*_net`` 与 pipeline
拦截副层逐字节一致。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Final

from texlate.textutil import (
    MATH_CS,
    bare_cs_net,
    dangerous_cs_net,
    ph_in_cs_net,
)
from texlate.validate.rules.lex import _lex
from texlate.validate.rules.report import Issue, Severity

if TYPE_CHECKING:
    from texlate.validate.rules.lex import _Ctx

#: 非 ASCII 控制序列名 = 融合产物（`\ `+中文 → `\和`，未定义 cs 编译炸弹）。
_NONASCII_RX: Final = re.compile(r"[^\x00-\x7f]")

#: 结构命令族：zh 新增命中 → error（幻觉结构）。
STRUCT_CMDS: Final = frozenset(
    {
        "appendix",
        "begin",
        "bibliography",
        "bibliographystyle",
        "def",
        "documentclass",
        "documentstyle",
        "edef",
        "end",
        "gdef",
        "include",
        "includegraphics",
        "input",
        "maketitle",
        "newcommand",
        "newcounter",
        "newenvironment",
        "newtheorem",
        "printbibliography",
        "providecommand",
        "renewcommand",
        "RequirePackage",
        "setcounter",
        "setlength",
        "tableofcontents",
        "usepackage",
        "xdef",
    }
)

#: 脆弱间距命令（E21/E22 cs_dropped 硬判据覆盖集）：
#: ``\<空格>`` ``\,`` ``\;`` ``\:`` ``\!`` 为词法层 bs token；``~`` 是活动字符。
FRAGILE_BS: Final = frozenset({"\\ ", "\\,", "\\;", "\\:", "\\!"})
FRAGILE_CHARS: Final = frozenset("~")


def _cs_names_toks(
    toks: list[tuple[str, str, int]],
) -> tuple[Counter[str], Counter[str]]:
    """``(cs 名 Counter, 脆弱间距 token Counter)``——``_lex`` token 流入参。脆弱集含 bs 五枚 + ``~``。"""
    cs: Counter[str] = Counter()
    frag: Counter[str] = Counter()
    for kind, text, _ in toks:
        if kind == "cs":
            cs[text] += 1
        elif kind == "bs":
            # ``\<newline>``/``\<tab>`` 与 ``\ `` 同义（TeX 控制空格）——
            # 归一后再比，否则等价形互换被误报 cs_dropped。
            tok = "\\ " if text[1:].isspace() else text
            if tok in FRAGILE_BS:
                frag[tok] += 1
        elif kind == "ch" and text in FRAGILE_CHARS:
            frag[text] += 1
    return cs, frag


def _cs_names(s: str) -> tuple[Counter[str], Counter[str]]:
    """``_cs_names_toks(_lex(s))``——fuzz oracle 用的字符串入口。"""
    return _cs_names_toks(_lex(s))


def _macro_new_issues(sn: Counter[str], zn: Counter[str], issues: list[Issue]) -> None:
    """zh−src 新增方向：E24 全档 error（新控制词即拒收，转义族 bs 天然豁免）。"""
    new = zn - sn
    for nme in sorted(new):
        if _NONASCII_RX.search(nme):
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文出现含非 ASCII 的控制序列 \\{nme} ×{new[nme]} "
                    f"(疑似 \\ + 中文熔合，未定义 cs 编译炸弹)",
                )
            )
        elif nme in STRUCT_CMDS:
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文新增结构命令 \\{nme} ×{new[nme]} (幻觉结构)",
                )
            )
        else:
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"译文新增控制序列 \\{nme} ×{new[nme]} "
                    f"(新控制词可携 prompt-injection 直进 .tex，拒收)",
                )
            )


def _check_macro(ctx: _Ctx) -> None:
    """控制序列双向 diff（E21/E22/E24 修订口径）。

    zh−src 新增：全档 error（结构族/非 ASCII 融合 cs 同档处理）。
    src−zh 丢失：脆弱间距命令计数差（cs_dropped）=error；其余丢失=warn。
    """
    issues = ctx.issues
    sn, sf = _cs_names_toks(ctx.lex_src)
    zn, zf = _cs_names_toks(ctx.lex_zh)
    _macro_new_issues(sn, zn, issues)

    # —— src 丢失方向（E22：脆弱命令计数差 cs_dropped 升硬判据）——
    for tok in sorted(FRAGILE_BS | {"~"}):
        dropped = sf.get(tok, 0) - zf.get(tok, 0)
        if dropped > 0:
            issues.append(
                Issue(
                    "macro",
                    Severity.ERROR,
                    f"脆弱间距命令 {tok!r} 丢失: src {sf[tok]} 处 → zh {zf.get(tok, 0)} 处 "
                    f"(cs_dropped，\\ +中文熔合/间距丢失高发)",
                )
            )
    issues.extend(
        Issue(
            "macro",
            Severity.WARN,
            f"控制序列 \\{nme} 未保留: src ×{sn[nme]} → zh ×{zn.get(nme, 0)}",
        )
        for nme in sorted(sn - zn)
        if nme not in STRUCT_CMDS  # 结构命令丢失已由 env/brace 覆盖，不重复报
    )


def _check_item_glue(ctx: _Ctx) -> None:
    r"""``\item``+ASCII 字母粘合签名（``\itemFSU`` 类，管线引入，编译炸弹）。

    走 ``_lex`` cs 流而非裸正则：``\\itemX``（``\\`` 断行 + 文本）不误判，
    注释区天然豁免。后缀须含大写字母——与 ``textutil.bare_cs_net`` 同口径，
    全小写延申按真实 cs 豁免（``\itemsep``/``\itemize``/``\itemindent``）。
    src 自带粘连靠 src↔zh 净差豁免；只报 zh 多出计数。
    """

    def glued(toks: list[tuple[str, str, int]]) -> Counter[str]:
        return Counter(
            t
            for k, t, _ in toks
            if k == "cs"
            and t != "item"
            and t.startswith("item")
            and any(c.isupper() for c in t[4:])
        )

    s, z = glued(ctx.lex_src), glued(ctx.lex_zh)
    extra = z - s
    if extra:
        toks = ", ".join(f"\\{t} ×{n}" for t, n in sorted(extra.items()))
        ctx.issues.append(
            Issue(
                "item_glue",
                Severity.WARN,
                f"\\item 与后随文本粘合成非法控制序列 ×{sum(extra.values())}: "
                f"{toks}（未定义 cs 编译炸弹，应拆回 \\item + 空格）",
                found=toks,
            )
        )


def _check_ph_in_cs(ctx: _Ctx) -> None:
    r"""``\cs名[..[[PH]]..]字母`` 双侧夹持签名（``\fo[[CMD_1]]o`` 类）。

    译文把占位符嵌进 cs 名中段 → splice 逐字节替换后断 cs
    （``\te[[PH]]xtbf``→``\te\cite{…}xtbf``、``\noind[[PH]]ent``→
    ``\noind\Cref{…}ent``——modec 两波实测签名）：未定义 cs 编译炸弹
    且断名 payload 不可复原，不进 fixloop、走重译/回退原文。

    双侧夹持是硬判据：``\cs[[PH]]`` 尾邻是合法高频形（corpus 271 处
    ——``\protect[[REF_n]]``/``\em[[CMD_n]]``/``\S[[REF_n]]``），只查
    前侧会灾难级误报；``\\`` 控制符号 + ``[[PH]]``（display-math 形）
    由 ``[a-zA-Z@]+`` 必需字母排除。注释区屏蔽豁免；src 自带同形
    （占位符本就贴命令名落位，实测 2/5413）按整串净差豁免。盲区
    记档：``\cs[[KEY_n]]`` 类尾邻载荷字母头也会融合，但 validator
    拿不到 ph_map 判不了类型——后续按 ph 类型白名单再补。
    """
    extra = ph_in_cs_net(ctx.src, ctx.zh)
    if extra:
        toks = ", ".join(f"{t} ×{n}" for t, n in sorted(extra.items()))
        ctx.issues.append(
            Issue(
                "ph_in_cs",
                Severity.ERROR,
                f"占位符嵌进控制序列名 ×{sum(extra.values())}: "
                f"{toks}（splice 后断 cs 成未定义命令，载荷不可复原——"
                f"应整体重译或回退原文）",
                found=toks,
            )
        )


def _check_bare_cs(ctx: _Ctx) -> None:
    r"""译文裸 cs 注入（realpostfix2 0905.4907 实证签名），两类编译炸弹。

    E24 起 ``macro`` 规则对**全部**新增 cs 已报泛 error——本规则把其中
    **编译即炸**的两个子类再以位置签名单列 error（命中名在 macro
    报表同现一条泛条目：有意分层而非重复缺陷——泛条目不带文本域/
    粘合前缀定位，corrector 反馈与子类聚类需要本条的诊断载荷；
    ``macro`` 的全名覆盖由 fuzz 分类 oracle 钉死，剔除会破坏钉面）。
    判定口径单源在 ``textutil.bare_cs_net``（pipeline ``_intercept_bare_cs``
    副层共用），``nme in MATH_CS`` 拆子类：

    - **数学域外数学 cs**：``\alpha``/``\to`` 类数学模式命令出现在 zh
      文本域（zh 自带 ``$..$``/``\\(\\)`` 内豁免——那是合法修正方向），
      净超出 src 文本域同计数 → ``Missing $`` 炸弹（``alpha emitters``
      被译成 ``\alpha 发射体``，caption 两处 → Missing $×4）。
    - **粘合 cs**：zh 新增名 = src 某 cs（≥3 字母）前缀 + **含大写**后缀
      ——``\itemOC``/``\linebreakGF``/``\csnamebibitemNoStop``（cs 吞掉
      间隔空格、后随词首字母粘上）→ 未定义 cs 炸弹。后缀须含大写：
      ``\citep``/``\refname``/``\textbf`` 类全小写延申是真实 cs 不炸。
    """
    net = bare_cs_net(ctx.src, ctx.zh)
    if not net:
        return
    issues = ctx.issues
    bombs = {nme: n for nme, n in net.items() if nme in MATH_CS}
    if bombs:
        toks = ", ".join(f"\\{nme} ×{n}" for nme, n in sorted(bombs.items()))
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文注入数学控制序列 ×{sum(bombs.values())}: {toks}"
                f"（文本域 Missing $ 编译炸弹——应为普通文字或 $…$ 包裹）",
                found=toks,
            )
        )
    fused = {nme: n for nme, n in net.items() if nme not in MATH_CS}
    if fused:
        # cs 名集与 ``_lex(mask_comments(src))`` 同集——注释区 ``\foo`` 在
        # 原始 token 流里本就裹在 cmt token 内不可见，无需再遮盖重扫。
        sn = {t for k, t, _ in ctx.lex_src if k == "cs"}
        parts = []
        for nme, n in sorted(fused.items()):
            pre = max((s for s in sn if nme.startswith(s)), key=len, default=None)
            parts.append(
                f"\\{nme}（\\{pre}+{nme[len(pre) :]} 粘合）×{n}"
                if pre is not None
                else f"\\{nme} ×{n}"
            )
        issues.append(
            Issue(
                "bare_cs",
                Severity.ERROR,
                f"译文出现粘合控制序列 ×{sum(fused.values())}: "
                f"{', '.join(parts)}"
                f"（未定义 cs 编译炸弹——应拆回 \\前缀 + 空格）",
                found=", ".join(parts),
            )
        )


def _check_dangerous_cs(ctx: _Ctx) -> None:
    r"""译文新增危险控制序列（``DANGEROUS_CS`` 表名净差）——注入签名。

    ``macro`` 泛条目同现属有意分层（见 ``_check_bare_cs`` 约定），本网兜
    ``bare_cs`` 未管的良形非数学危险 cs：``\input{/etc/passwd}``/
    ``\write18``（词法 ``write``+``18``）/``\def``/``\catcode``/
    ``\csname`` 逃逸族——数学域不豁免（``$\input$`` 照样执行）。判定口径
    单源在 ``textutil.dangerous_cs_net``（pipeline
    ``_intercept_dangerous_cs`` 副层共用）。已知盲区挂账：
    ``\begin{filecontents}`` 类 env 名参数写文件不产 cs 事件，归 env
    名面另网。
    """
    net = dangerous_cs_net(ctx.src, ctx.zh)
    if net:
        toks = ", ".join(f"\\{nme} ×{n}" for nme, n in sorted(net.items()))
        ctx.issues.append(
            Issue(
                "dangerous_cs",
                Severity.ERROR,
                f"译文注入危险控制序列 ×{sum(net.values())}: {toks}"
                f"（IO/定义覆写/catcode/装包逃逸族——应整体重译或回退原文）",
                found=toks,
            )
        )
