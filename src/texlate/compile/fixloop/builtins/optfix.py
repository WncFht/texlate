r"""builtins.optfix — env 选项组与排版参数外科 (builtins.misc C3 再拆叶)。

遮盖视图下 ``{..}``/``[..]`` 配对扫描 (``_skip_ws``/``_skip_bracket``
+ ``compile.mask.group_end``) 驱动的选项组编辑与参数注入:
``\begin{tcolorbox}``/``\newtcolorbox`` 补 ``breakable`` /
浮体 ``[H]`` 降级 ``float_h_demote`` / 浮体 opt cs 字面 spec 内联
``float_opt_cs_expand`` / preamble ``\emergencystretch``+``\tolerance``
松动 ``para_loosen``。前二者是 runaway_output (不可断盒 > ``\textheight``
→ ``\output`` 死循环) 修复臂。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from texlate.compile.fixloop.builtins.common import (
    _inject_before_begindoc,
    _live_matches,
    _map_tex_files,
    _splice,
)
from texlate.compile.mask import group_end
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# runaway_output 修复面：不可断盒 > \textheight → \output 空页死循环
# (killsem census 单机理族：sentry:page_flood SIGKILL 前泛洪签名)
# ════════════════════════════════════════════════════════════════


#: ``{``/``[`` 配对扫描统一走 ``texlate.compile.mask.group_end`` —— 转义/嵌套
#: 单源 (inject/layout/latex209/normalize 同口径); 本族在 raw 文本上跑，其
#: ``%`` 注释跳过是语义升级 (注释内 ``{``/``]`` 不再计入配对)。契约差两处：
#: unpaired 归一 ``len(t)`` (调用侧 ``e >= len(t)`` 判失配), 返回 after-index
#: (closer 位 = ``e - 1``)。


def _skip_ws(t: str, j: int) -> int:
    """空白/换行跳过 → 首个非空格位。"""
    while j < len(t) and t[j] in " \t\n":
        j += 1
    return j


def _skip_bracket(t: str, j: int) -> int | None:
    """``t[j] == "["`` → 配对组后空白归位; 非 ``[`` → ``j`` 原样; 未配对 → None。"""
    if j >= len(t) or t[j] != "[":
        return j
    e = group_end(t, j)
    return None if e >= len(t) else _skip_ws(t, e)


#: ``\begin{tcolorbox}`` env 站。
_TCB_BEGIN_RX = re.compile(r"\\begin\s*\{tcolorbox\}")
#: ``\newtcolorbox`` 定义站。
_TCB_DEF_RX = re.compile(r"\\newtcolorbox\b")
#: tcolorbox 装载点 (usepackage/RequirePackage; 选项组/包名单组)。
_TCB_LOAD_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\btcolorbox\b[^}]*\}"
)
#: ``\tcbuselibrary{…}`` 库声明点。
_TCB_LIB_RX = re.compile(r"\\tcbuselibrary\s*\{([^}]*)\}")
#: 含 breakable 的库名单 token——many/most/all 是 bundles
#: (tcolorbox.sty ``\tcb@add@library@style``: many→…breakable…, most/all→many)。
_TCB_BREAKABLE_LIBS = frozenset({"breakable", "many", "most", "all"})
#: 选项组内 breakable 键探测 (``unbreakable`` 前缀不沾——``\b`` 挡 ``n``)。
_TCB_BREAKABLE_KEY_RX = re.compile(r"\bbreakable\b")
#: 否定形键——``breakable=false``/``unbreakable`` 在泛洪格是肇事者，翻正。
_TCB_NEG_KEY_RX = re.compile(r"\bbreakable\s*=\s*false\b|\bunbreakable\b")


def _tcb_lib_state(ctx: LoopCtx) -> tuple[bool, tuple[Path, int] | None]:
    r"""``(breakable 库已载, tcolorbox 装载点 (file, match_end))`` —— 遮盖视图。

    装载点用于 ``\tcbuselibrary{breakable}`` 注入缝 (须在包载后);
    usepackage 选项组与 ``\tcbuselibrary`` 参数的逗号成员级 token 判定。
    """
    loaded = False
    site: tuple[Path, int] | None = None
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        for m in _TCB_LOAD_RX.finditer(masked):
            if site is None:
                site = (f, m.end())
            libs = {x.strip() for x in (m.group(1) or "").split(",")}
            if libs & _TCB_BREAKABLE_LIBS:
                loaded = True
        for m in _TCB_LIB_RX.finditer(masked):
            if site is None:
                site = (f, m.end())
            libs = {x.strip() for x in m.group(1).split(",")}
            if libs & _TCB_BREAKABLE_LIBS:
                loaded = True
    return loaded, site


def _tcb_opts_edits(start: int, inner: str) -> tuple[int, int, str] | None:
    """选项组 ``inner`` → breakable 化编辑 ``(s, e, new)``; 无需动 → None。"""
    new_inner = _TCB_NEG_KEY_RX.sub("breakable", inner)
    if new_inner != inner:
        return (start + 1, start + 1 + len(inner), new_inner)
    if _TCB_BREAKABLE_KEY_RX.search(inner):
        return None
    return (start + 1, start + 1, "breakable,")


def _tcb_def_opts_span(t: str, i: int) -> tuple[int, int] | None:
    r"""``\newtcolorbox`` 签名的末位 ``{options}`` 组 ``(start, end)``。

    形: ``\newtcolorbox[init]{name}[num][default]{options}`` —— 首个 ``[``
    组与 ``{name}`` 后零或多个 ``[`` 组跳过, 余下首个 ``{`` 即 options。
    """
    j = _skip_bracket(t, _skip_ws(t, i))  # [init]
    if j is None:
        return None
    if t[j : j + 1] != "{":  # {name}
        return None
    e = group_end(t, j)
    if e >= len(t):
        return None
    j = _skip_ws(t, e)
    while t[j : j + 1] == "[":  # [num][default]…
        j = _skip_bracket(t, j)
        if j is None:
            return None
    if t[j : j + 1] != "{":  # {options}
        return None
    e = group_end(t, j)
    return None if e >= len(t) else (j, e - 1)


def _tcb_edits(t: str) -> list[tuple[int, int, str]]:
    """单文件 tcolorbox env/def 选项组补 ``breakable`` 的编辑表 (遮盖视图定位)。"""
    edits: list[tuple[int, int, str]] = []
    for m in _live_matches(_TCB_BEGIN_RX, t):
        j = _skip_ws(t, m.end())
        if t[j : j + 1] == "[":
            e = group_end(t, j)
            if e >= len(t):
                continue
            if ed := _tcb_opts_edits(j, t[j + 1 : e - 1]):
                edits.append(ed)
        else:
            edits.append((m.end(), m.end(), "[breakable]"))
    for m in _live_matches(_TCB_DEF_RX, t):
        span = _tcb_def_opts_span(t, m.end())
        if span is None:
            continue
        s, e = span
        if ed := _tcb_opts_edits(s, t[s + 1 : e]):
            edits.append(ed)
    return edits


def _tcb_patch_text(t: str) -> tuple[str, int]:
    """``_map_tex_files`` 适配：``_tcb_edits`` 编辑表回放 → (新文本，编辑数)。"""
    edits = _tcb_edits(t)
    return _splice(t, edits), len(edits)


def tcolorbox_breakable_inject(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\begin{tcolorbox}``/``\newtcolorbox`` 选项组补 ``breakable`` (runaway_output 臂)。

    killsem census 双格实证 (2311.04163 zh→57p rc=0; 2504.11741 zh→47p):
    不可断 tcolorbox 超 ``\textheight`` 卡死 ``\output`` → page_flood。
    ``breakable`` 键把整盒翻为多页可断盒, 能放下的盒排版零变。

    键生效前提是 breakable 库已载——库探测按 ``_tcb_lib_state``:
    ``breakable``/``many``/``most``/``all`` 成员级 token (bundles 含
    breakable, texmf tcolorbox.sty 实证)。未载则须见 tcolorbox 装载点
    才能补 ``\tcbuselibrary{breakable}`` —— 无装载点 (cls 内载等)
    时补键会产 unknown-key 新错, 整体让位。已带 ``breakable`` 的站
    幂等跳过; ``breakable=false``/``unbreakable`` 否定形翻正
    (泛洪格否定键即肇事者)。遮盖视图定位——注释/verbatim 内
    ``\begin{tcolorbox}``/``\newtcolorbox`` 不算站。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    if not any(
        _tcb_edits(t) for f in ctx.tex_files(exts) if (t := ctx.read(f)) is not None
    ):
        return False, "no unbreakable tcolorbox env/def sites"
    lib_loaded, site = _tcb_lib_state(ctx)
    if not lib_loaded and site is None:
        return False, "breakable lib absent and no tcolorbox load site to attach"
    lib_note = ""
    if not lib_loaded:
        f, pos = cast("tuple[Path, int]", site)  # 上闸已排 site=None
        t = ctx.read(f) or ""
        ctx.write(f, t[:pos] + "\n\\tcbuselibrary{breakable} % fixloop\n" + t[pos:])
        lib_note = f" +\\tcbuselibrary{{breakable}} in {f.name}"
    n = _map_tex_files(ctx, exts, _tcb_patch_text)
    return True, f"breakable opts in {n} file(s){lib_note}"


#: ``[H]`` 降级的默认浮体 env 面 (params.envs 可扩)——kernel 浮体
#: figure/table (+星形) 与常见具名浮体 algorithm (algorithm/algorithm2e
#: 包)/listing (minted); ``H`` 是 float 宏包给一切浮体的锚。
_FLOAT_H_ENVS = (
    "figure",
    "table",
    "figure*",
    "table*",
    "algorithm",
    "algorithm*",
    "listing",
)
#: 合法浮体 placement 字符集——组内出现他字符即非纯 placement 表，不动。
_FLOAT_OPT_CHARS = frozenset("!htbpH")


def _float_demote_opts(inner: str) -> str | None:
    r"""浮体选项组 ``inner`` 含 ``H`` → 降级形; 非纯 placement 表/无 H → None。

    ``H`` = float 宏包绝对锚 (退化为非浮体盒, 超高即卡 page builder)。
    降级 = 去 ``H`` + ``!`` 前缀 (放宽浮体参数限——超高盒靠它才进
    float page) + 保证 ``p`` (超高盒唯一可靠落点) + 无 h/t/b 时补
    ``ht`` 保近位意图。``[H]``→``[!htp]``, ``[H!tbp]``→``[!tbp]``,
    ``[Hb]``→``[!bp]``。
    """
    if "H" not in inner or any(c not in _FLOAT_OPT_CHARS for c in inner):
        return None
    body = inner.replace("H", "").replace("!", "")
    if not any(c in body for c in "htb"):
        body += "ht"
    if "p" not in body:
        body += "p"
    return "!" + body


def _float_h_edits(t: str, rx: re.Pattern[str]) -> list[tuple[int, int, str]]:
    r"""单文件 ``\begin{<env>}[<opts 含 H>]`` 降级编辑表 (遮盖视图定位)。"""
    edits: list[tuple[int, int, str]] = []
    for m in _live_matches(rx, t):
        j = _skip_ws(t, m.end())
        if t[j : j + 1] != "[":
            continue
        e = group_end(t, j)
        if e >= len(t):
            continue
        if (new := _float_demote_opts(t[j + 1 : e - 1])) is not None:
            edits.append((j, e, "[" + new + "]"))
    return edits


def float_h_demote(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""浮体 ``[H]`` 系选项组降级为 ``!``+placement (runaway_output 臂)。

    与 ``float_opt_h_pkgload`` (70-pkgopt, float_opt|H 签名补
    ``\usepackage{float}``) 零重叠: 该格 float 已载, 失败模态是
    ``[H]`` 把超高内容钉成非浮体不可断盒 → page builder 死循环
    (2608.09867 base: figure[H]+~755pt 图 > ~731pt \textheight)。
    降级翻回真浮体即交给 float page 出盒 (超限也落 overfull 而非死循环)。

    遮盖视图定位 ``\begin{<env>}\s*[`` 站, 组内容限 ``!htbpH`` 字符
    (placement 表白名单——含他字符的括号组非浮体选项, 不动); 无 H
    即幂等跳过。env 面默认 ``_FLOAT_H_ENVS``, ``params.envs`` 可扩。
    """
    del eng, payload
    envs = tuple(str(x) for x in (params.get("envs") or _FLOAT_H_ENVS))
    rx = re.compile(r"\\begin\s*\{(?:" + "|".join(re.escape(x) for x in envs) + r")\}")
    exts = tuple(params.get("exts") or (".tex",))
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        edits = _float_h_edits(t, rx)
        if edits:
            ctx.write(f, _splice(t, edits))
            changed += 1
    if not changed:
        return False, "no [H] float option sites"
    return True, f"[H] demoted in {changed} file(s)"


#: 浮体 opt 字面 spec 白名单——``!htbpH`` 外字符的 def 值不是 placement
#: (含 H: 展开后落 float_opt|H → float_opt_h_pkgload 已覆盖路径)。
_FLOATOPT_SPEC_RE = re.compile(r"[!htbpH]+")

#: 无参 cs 字面定义面：``\def``/``\gdef``/``\edef``/``\xdef`` 与
#: ``\new``/``\renew``/``\providecommand`` 裸形。带参宏 (``[n]`` 计数)
#: 结构不含 {spec} 紧邻位 → 天然排除。
_FLOATOPT_CS_DEF_RE = re.compile(
    r"\\[gex]?def\s*\\([A-Za-z@]+)\s*\{([^{}\n]*)\}"
    r"|\\(?:new|renew|provide)command\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*\{([^{}\n]*)\}"
)

#: 浮体 opt 括号单 cs 站位三形——env 默认参 (``\newenvironment{env}[n][\cs]``)、
#: ``\@float`` 族直调 (``\@float{env}[\cs]``/``\@dblfloat``/``\@rotfloat``/``\@xfloat``)、
#: ``\begin{env}[\cs]`` 显式值。组 1/3/5 = 站前缀，组 2/4/6 = cs。
_FLOATOPT_CS_SITE_RE = re.compile(
    r"(\\(?:new|renew)environment\*?\s*\{[A-Za-z@* ]+\}\s*\[\d+\]\s*)\[\s*\\([A-Za-z@]+)\s*\]"
    r"|(\\@(?:dbl|x|rot)?float\s*\{[A-Za-z*]+\}\s*)\[\s*\\([A-Za-z@]+)\s*\]"
    r"|(\\begin\s*\{[A-Za-z*]+\}\s*)\[\s*\\([A-Za-z@]+)\s*\]"
)


def float_opt_cs_expand(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""浮体 opt cs 值 → ``\def`` 字面 spec 内联 (sanitize cs 名逐字炸)。

    死因 (0712.0315 cimento.cls 实证): ``\newenvironment{table}[1][\fps@table]``
    类 cs 默认 opt 经 ``\@xfloat`` ``\@onelevel@sanitize`` 展开成 cs 名字符
    (``\fps@table``→``\fps@table`` 逐字) —— ``p/t/b`` 静默过, ``\``/``f``/``s``/``@``/
    ``a``/``l``/``e`` 每字一报 ``Unknown float option`` (单 cell 21 错)。
    ``[\cs]`` 站与 ``\def\cs{spec}`` 同工程可解且 spec 纯 ``!htbpH`` 字符时
    内联字面 spec —— 非浮体语境亦语义恒等 (cs 本展开同串), 零语义改写。
    多重定义/非 spec 值/cs 不可解 → 保守不动。
    """
    del eng, payload
    defs: dict[str, list[str]] = {}
    for m in _live_matches(_FLOATOPT_CS_DEF_RE, ctx.source_blob()):
        name = m.group(1) or m.group(3)
        spec = (m.group(2) or m.group(4) or "").strip()
        defs.setdefault(name, []).append(spec)
    specs = {
        n: s[0]
        for n, s in defs.items()
        if len(s) == 1 and _FLOATOPT_SPEC_RE.fullmatch(s[0])
    }
    if not specs:
        return False, "no resolvable float-spec cs defs"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if not t:
            continue

        def _sub(m: re.Match[str]) -> str:
            prefix = m.group(1) or m.group(3) or m.group(5)
            cs = m.group(2) or m.group(4) or m.group(6) or ""
            spec = specs.get(cs)
            if spec is None:
                return m.group(0)
            return (prefix or "") + "[" + spec + "]"

        nt = _FLOATOPT_CS_SITE_RE.sub(_sub, t)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    if not changed:
        return False, "no cs-valued float option sites resolved"
    return True, f"expanded cs float opts in {changed} file(s)"


#: ``para_loosen`` 注入块——TeX 三遍排版真修复面：``\tolerance`` 抬第
#: 二遍坏度阈、``\emergencystretch>0`` 开第三遍以额外 stretch 重排
#: 断不开的段落。不设 ``\hfuzz``——放宽 overfull 报告阈值是把
#: qc 证据面吃掉而非修复 (埋/放行边界：只动排版参数，不动警告面)。
_LOOSEN_SNIPPET = (
    "% texlate-fixloop: overfull-hbox mitigation\n"
    "\\emergencystretch=1.5em\\relax\n"
    "\\tolerance=2000\\relax"
)


def para_loosen(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 修复: preamble 尾注 ``\emergencystretch``+``\tolerance``。

    Overfull ``\\hbox`` 多出自不可断内联物 (长行内数学/URL/CJK-拉丁
    混排段) 把词间 glue 拉竭——emergencystretch 给第三遍额外可伸
    缩量是真排版修复, 不改文本不遮警告。注点在 ``\begin{document}``
    前 (晚于 cls/包的字距初值, 早于 ``\AtBeginDocument`` 钩); 无锚
    退文件头 (仍先于一切 cls 执行体)。snippet 内含标记行, 重复命中
    幂等——已注入报 applied 让修复环收敛, 不叠注。

    ``params.snippet`` 可换注入体 (测试/族系特调面); 默认
    ``_LOOSEN_SNIPPET``。
    """
    del eng, payload
    snippet = str(params.get("snippet") or _LOOSEN_SNIPPET)
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main)
    if t is not None and snippet in t:
        return True, "loosen block already present"
    if not _inject_before_begindoc(ctx, snippet, fallback="head"):
        return False, "no injectable site"
    return True, "injected \\emergencystretch+\\tolerance at preamble end"
