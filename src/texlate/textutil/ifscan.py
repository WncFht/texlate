r"""条件栈字面扫描器 —— ``unclosed_if_close``/``unclosed_if_close_eof`` 共用件。

修复面 (failmine item 4): doc 源件未闭合 ``\\if*`` → ``\\end{document}``/
``\\endinput``/EOF 前注入 ``\\fi``。扫描模型 = mask_tex 遮盖视图上的
token 栈: ``\\if*`` 族开、``\\fi``/``\\repeat`` 闭、``{}``/``\\bgroup``/
``\\egroup`` 成组、``\\def``/``\\newcommand``/``\\let``/分配系等吃掉
operand/名位 (冻结 token 非活开)。def 体 open 只计不注 (file-end ``\\fi``
够不到冻结 token, 注入反造 Extra ``\\fi``); 跨文件借用对由调用方全局
opens>closes 闸兜住。

phantom 判例 (loop4 批一 152 格实证): TeX 条件跳读扫描**按 token 计**
``\\if`` 族——``\\let`` 不执行 ⇒ ``\\let\\X\\iftrue`` 的第二 operand 在被跳
分支里仍是裸 ``\\if`` token → 假开臂吞 ``\\fi`` → ``Incomplete \\ifdefined``。
字面扫描对 operand 位恒按"非开"计, 与执行态一致但与跳读态分歧——凡
``\\if``/``\\fi`` token 落在非执行位 (operand/名位/def 参数位/skip 组) 且
外层有活条件帧 (live cond-depth>0), 即记 phantom: 字面平衡照常报, 但
verdict 带 ``phantom=N`` 供 ``if_phantom_protect`` 判别臂区分跳读形
(``\\protected`` 域不含) 与 edef 展开形 (本规则域)。

``\\let`` operand 扩展 (盲区修复): 名位接受 cs 名与单字符名两形
(``\\let\\X\\iftrue`` / ``\\let a=\\iftrue`` / ``\\let{\\iftrue``)——
旧版只认紧邻 cs 名, ``\\let a=\\iftrue`` 形漏吃 operand → ``\\iftrue``
误计活开 → 假亏格误注。

if-alias 追踪 (loop4 批一 事故形): ``\\let<cs><if族>`` 使 cs 得
if_test cmd —— ``\\let\\TeXlateCMUok\\iftrue`` 后 ``\\TeXlateCMUok`` 裸用
即开臂, 名不带 ``if`` 前缀旧版漏计。登记限 def 体外 (def 体内 ``\\let``
只在调用时执行, alias 存在性不可静态判), 经 ``pending_alias`` 在
operand 落定后补登 (名位/operand 按"前 ``\\let`` 态"判 phantom);
``\\let``/``\\def``/``\\newcommand`` 重定义即销 alias。``\\fi``/``\\repeat``
operand 同理记 close-alias。operand 预算 (``COND_OPS``): ``\\ifx``/
``\\ifnum``/``\\ifdefined`` 等其后 N cs 是 operand 位非开臂 (执行态),
走 cond_ops 位静默 + phantom 判 (跳读态按 token 计) —— 旧版把
``\\ifdefined\\iffoo`` 的 ``\\iffoo`` 误计开 → 假亏格误注。预算按
"下 N 个 token"计 (gap 字面字符逐枚抵, ``_NON_WS``): ``\\ifnum 1=1``
形 operand 是字面量直接占满, 否则 ``\\fi`` 被当 operand 吃掉 →
反造假亏格。
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Final

from texlate.textutil.decls import END_DOC_RX
from texlate.textutil.mask import mask_tex

#: if-prefixed cs that are NOT TeX conditionals (macro tests, never take ``\fi``)
NONCOND: Final = {
    "iff",
    "ifdef",
    "ifundef",
    "ifcsdef",
    "ifcsundef",
    "ifcsempty",
    "ifcsvoid",
    "ifdefequal",
    "ifdefstring",
    "ifdefempty",
    "ifdefvoid",
    "ifdefparam",
    "ifdefprotected",
    "ifdefexpandable",
    "ifdefcounter",
    "ifdeflength",
    "ifcsstring",
    "ifstrequal",
    "ifstrempty",
    "ifstrblank",
    "ifblank",
    "ifempty",
    "ifnumcomp",
    "ifnumequal",
    "ifnumgreater",
    "ifnumless",
    "ifnumodd",
    "ifdimcomp",
    "ifdimequal",
    "ifdimgreater",
    "ifdimless",
    "ifboolexpr",
    "ifboolexpe",
    "ifbool",
    "ifboollazy",
    "iftoggle",
    "ifinlist",
    "ifinlistcs",
    "ifthenelse",
    "ifnextchar",
}
#: cs whose next N cs-tokens are name/arg positions (not live opens)
#: —— "let" 不在此列：第二 token 是否为名取决于赋值对象形，
#: 由 _let_operands lookahead 特判 (\\let\\sep=, 形第二 cs 是 live)。
#: 预算按 token 计——operand 位花括号 (``\let\X{``/``\let\X}``) 亦抵一枚
#: 且不开闭组; ``\let{`` 名位花括号例外，仍开组不占预算。
CONSUME: Final = {
    "newif": 1,
    "futurelet": 3,
    "string": 1,
    "meaning": 1,
    "newcount": 1,
    "newdimen": 1,
    "newbox": 1,
    "newskip": 1,
    "newmuskip": 1,
    "newtoks": 1,
    "newread": 1,
    "newwrite": 1,
    "newfam": 1,
    "newinsert": 1,
    "newlanguage": 1,
    "chardef": 1,
    "countdef": 1,
    "dimendef": 1,
    "skipdef": 1,
    "muskipdef": 1,
    "toksdef": 1,
    "mathchardef": 1,
    "font": 1,
}
#: cs that scan name+params until {body}; body tokens are frozen (def-tag)
DEFCMD: Final = {
    "def",
    "gdef",
    "edef",
    "xdef",
    # aastex.cls 5.2 caller-supplies-\fi 习语：\@boole@def\@ifx#1{\ifx#1}
    # —— 内层 \ifx 在 def-参组内展开期平衡 (caller 供 \fi), 非 live open;
    # 走 def_params→def 组即按冻结计，消 5 连假开 (aastex61if census)
    "@boole@def",
    "everypar",
    "everymath",
    "everydisplay",
    "everyhbox",
    "everyvbox",
    "everyjob",
    "everycr",
    "everyeof",
    "output",
    "toks",
    "write",
    "special",
    "pdfliteral",
    "directlua",
    "uppercase",
    "lowercase",
    "detokenize",
    "unexpanded",
    "scantokens",
}
#: name (cs or {name}) then {body}
NCCMD: Final = {
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
    "DeclareMathOperator",
}
#: name then {spec} then {body}
SPECCMD: Final = {
    "DeclareDocumentCommand",
    "NewDocumentCommand",
    "RenewDocumentCommand",
    "ProvideDocumentCommand",
    "DeclareExpandableDocumentCommand",
}
#: {name} then {beg} then {end}
ENVCMD: Final = {"newenvironment", "renewenvironment", "provideenvironment"}
CLOSE: Final = {"fi", "repeat"}
#: operand-taking conditionals —— 紧随的 N 个 cs 是 operand 位非开臂
#: (``\ifx\a\b`` 比较 token; ``\ifnum\X=1`` 的 ``\X`` 是数字 operand;
#: ``\ifdefined\X`` 的 ``\X`` 是名)。预算按"下 N 个 token"计 —— gap
#: 字面字符逐枚抵扣 (``_NON_WS``), 花括号/cs token 各抵一枚; 抵扣中
#: 的 brace operand 不参与开闭组。数值测试只钉首枚 token —— 多 cs
#: 数字原子 (``\count@<\count@@``) 第二枚仍走字面 dispatch, 属残留盲区。
COND_OPS: Final = {
    "if": 2,
    "ifcat": 2,
    "ifx": 2,
    "iffontchar": 2,
    "ifdefined": 1,
    "ifnum": 1,
    "ifdim": 1,
    "ifodd": 1,
    "ifcase": 1,
    "ifeof": 1,
    "ifvoid": 1,
    "ifhbox": 1,
    "ifvbox": 1,
}
#: 控制符号 (``\\``/``\{``/``\%`` …) 整枚成 token——转义花括号非组
#: 开闭; group(1)/group(2) 皆 None, 由 dispatch 早跳 (operand 位仍占
#: 一枚 token 预算：``\ifx\{x`` 的 ``\{`` 是被比较 token)。
TOKEN: Final = re.compile(r"\\([a-zA-Z@]+)|\\.|([{}])")
#: 注入缝边界——``\end{document}`` 段与 decls.END_DOC_RX 同案源 (组
#: 合式拼接待 ``DECL_TAIL`` 族)。
STOP: Final = re.compile(
    END_DOC_RX.pattern + r"|\\endinput\b|\\stop\b|\\end\b(?!\s*\{)"
)
_WS1: Final = re.compile(r"[ \t]*\n?[ \t]*")
_WS_EQ: Final = re.compile(r"[ \t]*\n?[ \t]*=?[ \t]*\n?[ \t]*")
#: operand 位的字面字符 token —— 条件 operand 按"下 N 个 token"计，gap
#: 内每个非空白字符占一枚 operand (``\ifx a\b`` 的 ``a``; ``\ifnum 1=1``
#: 字面量直接占满预算，防 ``\fi`` 被当 operand 吃掉造假亏格)。
_NON_WS: Final = re.compile(r"\S")


def _let_operands(  # noqa: C901, PLR0911 -- <name>/<equals>/<tok> 形态枚举即返回面
    vis: str, pos: int
) -> tuple[int, str | None, str | None, bool]:
    r"""``\let`` 在 ``pos`` 起的 operand 布局 → (消费 token 数, 名 cs, operand cs, 名是 ``{``)。

    ``\let<name><sp*><=><sp*><tok>`` —— name 为紧邻 cs (``\let\X\iftrue``)
    或单字符 (``\let a=\iftrue``) 或 ``{`` (``\let{\iftrue``); operand 仅
    在 gap 纯空白+可选 ``=`` 时是其后 token —— ``\let\sep=,\fi`` 赋的是字符
    ``,``, 其后 ``\fi`` 是 live close 非名 (elsarticle/IEEEtran CONSUME=2
    假开实证); ``\let ab\iftrue`` 名 ``a`` 字符 operand ``b``, 远端 cs live。

    名 cs/operand cs 供调用方做 if-alias 登记 (``\let\ok\iftrue`` → ``\ok``
    得 if_test cmd, 裸用即开臂 —— loop4 批一 事故形); 字符名/``{`` 名
    返回 None (非 cs token, 无 alias 可言)。operand 是花括号 token 时计
    入消费数 (``\let\X{``/``\let\X}`` → 2)——主循环按 operand 位静默吃掉
    不开闭组; 名位本身是 ``{`` 时 flag=True, 该 ``{`` 仍走主循环开组
    (``\let{\iftrue`` 名位形), 不占 operand 预算。
    """
    nm = TOKEN.search(vis, pos)
    if nm is None:
        return (0, None, None, False)
    gap = vis[pos : nm.start()]
    if not _WS1.fullmatch(gap):
        # 非纯空白 gap → 首非空字符为名，余部须 ws+ 可选 ``=`` 才合 <equals>;
        # operand 是 nm 本身 (cs/花括号 token 均占 operand 位吃 1)。
        rest = gap.lstrip()[1:]
        if _WS_EQ.fullmatch(rest):
            if nm.group(1) is not None:
                return (1, None, nm.group(1), False)
            if nm.group(2) is not None:
                return (1, None, None, False)
        return (0, None, None, False)
    if nm.group(1) is not None:  # cs 名
        nm2 = TOKEN.search(vis, nm.end())
        if nm2 is not None and _WS_EQ.fullmatch(vis[nm.end() : nm2.start()]):
            if nm2.group(1) is not None:
                return (2, nm.group(1), nm2.group(1), False)
            if nm2.group(2) is not None:
                # operand 是花括号 token (``\let\X{``/``\let\X}``)——同占
                # operand 位 (预算 2), 主循环抵扣时不开闭组。
                return (2, nm.group(1), None, False)
        return (1, nm.group(1), None, False)
    if nm.group(2) == "{":
        # ``{`` 即名 (begin-group 是合法 \let 名); { 由主循环开组，
        # operand 是组内首个 cs —— ``\let{\iftrue`` 的 \iftrue 被吃。
        nm2 = TOKEN.search(vis, nm.end())
        if (
            nm2 is not None
            and nm2.group(1) is not None
            and _WS_EQ.fullmatch(vis[nm.end() : nm2.start()])
        ):
            return (1, None, nm2.group(1), True)
        return (0, None, None, True)
    return (0, None, None, False)  # ``}`` 不能为 \let 名


@dataclass
class IfScan:
    r"""``scan_ifs`` 结果。

    ``unclosed_live`` 活区亏格 open (name, line, region); ``live_opens``/
    ``live_closes`` 活区开闭计数 (调用方跨件汇总做借用对闸); ``boundary``
    = 最浅 STOP 位 (注入缝); ``phantoms`` 跳读形嫌疑 token
    (name, line, kind)——kind ∈ ``open`` (operand/名位/def 参位/skip 组内
    ``\\if``) / ``close`` (同位 ``\\fi``/``\\repeat``) / ``def-open``
    (活条件内 def 区 open, 已计入 opens 此处仅上报); ``def_unclosed``
    def 体冻结未闭数 (诊断, 不注)。
    """

    unclosed_live: list[tuple[str, int, int]] = field(default_factory=list)
    live_opens: int = 0
    live_closes: int = 0
    boundary: int = 0
    phantoms: list[tuple[str, int, str]] = field(default_factory=list)
    def_unclosed: int = 0


def scan_ifs(text: str) -> IfScan:  # noqa: C901, PLR0912, PLR0915 -- token 分派即分支表 (条件栈字面扫描)
    r"""字面条件栈扫描 —— 活区亏格 + phantom 跳读嫌疑。

    Live = outside frozen def bodies; opens inside def-family bodies are
    counted but never injected (a file-end ``\\fi`` cannot reach a token list).
    Phantom = ``\\if``/``\\fi`` token 在非执行位且外层有活条件帧 —— TeX 跳读
    扫描按其 token 计 (``\\let`` 不执行, operand 不隐身), 字面扫描按执行态
    计 —— 两模分歧位。
    """
    vis = mask_tex(text)
    nl_offs = [
        i for i, ch in enumerate(vis) if ch == "\n"
    ]  # 换行偏移表 —— 行号 bisect 查
    opens: list[tuple[str, int, int]] = []  # (name, line, region) region=0 live
    groups: list[str] = []  # per-{ kind: "grp"|"def"|"skip"
    def_idx: list[
        int
    ] = []  # groups 内 "def" 组的 1-based 位次栈 —— def_depth O(1) 口径
    skip_n = 0  # groups 内 "skip" 组现数 —— 逐 token 线性扫组的 O(1) 替代
    live_open_now = 0  # opens 内 r==0 现数 —— live_cond O(1) 口径
    let_brace_name = (
        False  # \let{ 名位形：紧邻下枚 ``{`` 是名 —— 仍开组不占 operand 预算
    )
    live_opens = live_closes = def_unclosed = 0
    consume = 0
    cond_ops = 0  # COND_OPS operand 预算 —— 下 N 个 token 是 operand 位
    prev_end = 0  # 上一 token 在 vis 的右端 —— cond_ops gap 字面计
    pending: list[str] | None = None  # brace-kind queue after NC/SPEC/ENV heads
    def_params = False
    stops: list[tuple[int, int]] = []  # (pos, live opens depth)
    phantoms: list[tuple[str, int, str]] = []
    # \let 别名表：\let<cs><if 族> → cs 得 if_test cmd, 裸用 = 开臂
    # (loop4 批一 事故形：\let\TeXlateCMUok\iftrue 后 \TeXlateCMUok 裸开
    # —— 名不带 "if" 前缀，字面规则漏计)。值 = 该 if 的 operand 预算
    # (\let\X\ifnum → \X 也吃 1 operand)。登记限 def 体外，但活条件内
    # 的 \let 也登记 (incident 形正是分支内 \let + 分支外裸用); operand
    # 消费完后经 pending_alias 补登 —— 名位/operand 自身须按"前 \let 态"
    # 判 phantom。
    if_alias_ops: dict[str, int] = {}
    close_aliases: set[str] = set()
    pending_alias: tuple[str, str] | None = None  # (name_cs, op_cs)
    def_name = False  # DEFCMD 后首个 cs 是名位 → 销 alias

    def line_at(pos: int) -> int:
        return bisect_left(nl_offs, pos) + 1

    def def_depth() -> int:
        return def_idx[-1] if def_idx else 0

    def live_cond() -> int:
        return live_open_now

    def check_phantom(cs: str, pos: int) -> None:
        # 非执行位 token 在活条件帧内 → 跳读扫描按其计 (phantom)。
        if live_cond() == 0:
            return
        line = line_at(pos)
        if (cs.startswith("if") and cs not in NONCOND) or cs in if_alias_ops:
            phantoms.append((cs, line, "open"))
        elif cs in CLOSE or cs in close_aliases:
            phantoms.append((cs, line, "close"))

    def close_group() -> None:
        nonlocal def_unclosed, skip_n
        kind = groups.pop() if groups else "grp"
        if kind == "def":
            while opens and opens[-1][2] == len(groups) + 1:
                opens.pop()
                def_unclosed += 1
            def_idx.pop()
        elif kind == "skip":
            skip_n -= 1

    def push_group() -> None:
        # ``{``/``\bgroup`` 共用开组分派：pending 列队优先，次 def_params
        # 体组，余皆普通组。
        nonlocal def_params, skip_n
        kind = "grp"
        if pending:
            kind = pending.pop(0)
        elif def_params:
            kind = "def"
            def_params = False
        if kind == "name":
            kind = "skip"  # \newcommand{\foo} name brace: content unscanned
        groups.append(kind)
        if kind == "def":
            def_idx.append(len(groups))
        elif kind == "skip":
            skip_n += 1

    for tm in TOKEN.finditer(vis):
        cs, brace = tm.group(1), tm.group(2)
        if cond_ops:
            # operand 预算按"下 N 个 token"计：gap 内字面字符逐枚抵
            # operand (\ifx a\b 的 a 占一位; \ifnum 1=1 字面量占满)——
            # 耗尽则本 token 回常规 dispatch; 未耗尽则本 token 是
            # operand: cs 静默+phantom 判，brace operand 亦不参与结构
            # (\ifx{ 的 { 是被比较 token 非开组)。
            ngap = len(_NON_WS.findall(vis[prev_end : tm.start()]))
            if ngap >= cond_ops:
                cond_ops = 0
            else:
                cond_ops -= ngap + 1
                if cs is not None:
                    check_phantom(cs, tm.start())
                prev_end = tm.end()
                continue
        prev_end = tm.end()
        if cs is None and brace is None:
            # 控制符号 token (``\\``/``\{``/``\%`` …)——非组非名不占结构位;
            # operand 预算内则同占一枚 (``\string\%`` 的 ``\%`` 是 operand)。
            if consume:
                consume -= 1
            continue
        if brace == "{":
            if let_brace_name:
                # ``\let{`` 名位花括号 (紧邻 \let 的下枚 token, 由
                # _let_operands 报位)——不占 operand 预算，仍按开组。
                let_brace_name = False
            elif consume:
                # operand 位 ``{`` (``\let\X{`` 等) 是被赋 value token——
                # 抵预算一枚，不开组 (cond_ops 同款口径)。
                consume -= 1
                continue
            push_group()
            continue
        if brace == "}":
            if consume:
                # operand 位 ``}`` (``\let\X}``) 同理——抵预算不闭组。
                consume -= 1
                continue
            close_group()
            if def_params and not pending:
                def_params = False
            continue
        # cs token
        if skip_n:
            check_phantom(cs, tm.start())
            continue
        if consume:
            consume -= 1
            check_phantom(cs, tm.start())
            if consume == 0 and pending_alias is not None:
                # \let operand 落定才登 alias —— 名位/operand 按前 \let 态判过。
                name_cs, op_cs = pending_alias
                pending_alias = None
                if_alias_ops.pop(name_cs, None)
                close_aliases.discard(name_cs)
                if (op_cs.startswith("if") and op_cs not in NONCOND) or (
                    op_cs in if_alias_ops
                ):
                    if_alias_ops[name_cs] = COND_OPS.get(
                        op_cs, if_alias_ops.get(op_cs, 0)
                    )
                elif op_cs in CLOSE or op_cs in close_aliases:
                    close_aliases.add(name_cs)
            continue
        if def_params:
            check_phantom(cs, tm.start())
            if def_name:  # \def<name> 名位 —— 重定义即销 alias
                def_name = False
                if_alias_ops.pop(cs, None)
                close_aliases.discard(cs)
            continue  # \def name/params position
        if pending and pending[0] == "name":
            pending.pop(0)  # \newcommand\foo bare cs name
            check_phantom(cs, tm.start())
            if_alias_ops.pop(cs, None)
            close_aliases.discard(cs)
            continue
        if cs == "let":
            consume, name_cs, op_cs, let_brace_name = _let_operands(vis, tm.end())
            if name_cs is not None and def_depth() == 0:
                if op_cs is not None:
                    pending_alias = (name_cs, op_cs)
                else:
                    # \let\X<非 cs operand> —— 重定义即销 alias。
                    if_alias_ops.pop(name_cs, None)
                    close_aliases.discard(name_cs)
            continue
        if cs in CONSUME:
            consume = CONSUME[cs]
            continue
        if cs in DEFCMD:
            def_params = True
            def_name = True
            continue
        if cs in NCCMD:
            pending = ["name", "def"]
            continue
        if cs in SPECCMD:
            pending = ["name", "skip", "def"]
            continue
        if cs in ENVCMD:
            pending = ["skip", "def", "def"]
            continue
        if cs == "bgroup":
            push_group()
            continue
        if cs == "egroup":
            close_group()
            if def_params and not pending:
                def_params = False
            continue
        if cs in ("end", "endinput", "stop") and STOP.match(vis, tm.start()):
            if def_depth() == 0:  # STOP inside a def body is dead text
                stops.append((tm.start(), len(opens)))
            continue
        d = def_depth()
        if (cs.startswith("if") and cs not in NONCOND) or cs in if_alias_ops:
            opens.append((cs, line_at(tm.start()), d))
            if d == 0:
                live_opens += 1
                live_open_now += 1
            elif live_cond() > 0:
                # 活条件内的 def 区 open: 跳读同样计开 (已计入 opens,
                # 此处仅上报 —— 不重复计 live/def 合计)。append 的是
                # def 区 open (r>0), 不影响 live_cond 读数。
                phantoms.append((cs, line_at(tm.start()), "def-open"))
            # operand 预算：\ifx/\ifnum/\ifdefined 等其后 N cs 是 operand
            # 位 —— 走 cond_ops 位静默 + phantom 判，不计开 (跳读扫描按
            # token 计，与 operand 位语义一致地落在 phantom 域)。
            cond_ops = COND_OPS.get(cs) or if_alias_ops.get(cs, 0)
        elif cs in CLOSE or cs in close_aliases:
            if d > 0:
                if opens and opens[-1][2] == d:
                    opens.pop()
            else:
                live_closes += 1
                if opens and opens[-1][2] == 0:
                    opens.pop()
                    live_open_now -= 1
    res = IfScan()
    res.unclosed_live = [o for o in opens if o[2] == 0]
    res.live_opens = live_opens
    res.live_closes = live_closes
    # boundary = min-depth STOP (depth 0 = live \end{document}; >0 = a STOP
    # swallowed inside an unclosed \if — injecting \fi before its line
    # closes the host conditional and lets the STOP execute)
    res.boundary = min(stops, key=lambda s: s[1])[0] if stops else len(text)
    res.phantoms = phantoms
    res.def_unclosed = def_unclosed
    return res
