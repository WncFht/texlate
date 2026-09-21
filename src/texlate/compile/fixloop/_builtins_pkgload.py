r"""_builtins_pkgload — ``\\usepackage``/``\\documentclass`` 装载点改写原语 (C3 拆分)。

既有文件内 package 装载面外科: option clash 选项合并 / inputenc 整包剥离 /
physics stub 脱注册续载 / MF-only 字体包换 Type1 近亲 shim。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _PKG_LOAD_RE,
    _USE_RE,
    _drop_pkg_loads,
    _exact_restore_wrap,
    _fixloop_log,
    _live_matches,
    _pkg_list_re,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# 装载命令骨架件已归位 ``_builtins_common`` (``_PKG_LOAD_*``/
# ``_pkg_list_re``/``_exact_restore_wrap``; ``_USE_RE``/``_AT_LETTER_*``
# 在彼侧同源 rebase) —— 本叶直引。
# ════════════════════════════════════════════════════════════════


def option_clash_merge(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Option clash: 同包两次 ``\\usepackage`` → 合并选项到首处, 注释后处 (spike L459-494)。"""
    del eng  # 签名面统一; 本变换不触引擎
    if not payload:
        return False, "no pkg payload"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        hits = [
            m
            for m in _live_matches(_USE_RE, t)
            if payload in [x.strip() for x in m["names"].split(",")]
        ]
        if len(hits) < 2:  # noqa: PLR2004 - 2 = 重复加载的最小命中数
            continue
        first = hits[0]
        merged = ",".join(
            dict.fromkeys(
                o for h in hits for o in (h["opts_inner"] or "").split(",") if o
            )
        )
        m0 = first.group(0)
        if first["opts"]:
            first_new = m0.replace(first["opts"], f"[{merged}]", 1)
        else:  # 首个加载无 [opts] → 在花括号前插 [merged]; spike L486
            # `str.replace("", ...)` 会逐位插入, 此处修掉该潜伏 bug
            brace = m0.rfind("{")
            first_new = m0[:brace] + f"[{merged}]" + m0[brace:]
        # 首处后所有重复装载点全注释 —— 编辑表交 ``_splice`` 排序回放
        edits = [
            (
                later.start(),
                later.end(),
                "% fixloop: merged into earlier \\usepackage\n% "
                + later.group(0).replace("\n", "\n% "),
            )
            for later in hits[1:]
        ]
        edits.append((first.start(), first.end(), first_new))
        t = _splice(t, edits)
        ctx.write(f, t)
        changed += 1
    return (changed > 0), f"merge \\usepackage{{{payload}}} opts in {changed} files"


_INPUTENCODING_RE = re.compile(r"\\inputencoding\s*\{[^}]*\}")


def strip_inputenc(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Unicode 引擎剥 inputenc: 装载点 + ``\inputencoding{}`` 调用 (compilebench-v3 缺口)。

    inputenc.sty 对 xetex/luatex 整包拒载 ("not designed for xetex or
    luatex"); 源真为非 UTF-8 时由 warn_utf8 → non_utf8_source 在后续轮
    接续转码, 两轮分工不混。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "inputenc" not in t:
            continue
        nt, n_load = _drop_pkg_loads(t, "inputenc")
        # 遮盖视图定位 —— 注释/verbatim 内的假装载调用不剥
        enc_edits = [
            (m.start(), m.end(), "") for m in _live_matches(_INPUTENCODING_RE, nt)
        ]
        nt = _splice(nt, enc_edits)
        n_enc = len(enc_edits)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f"{f.name}(-{n_load}load,-{n_enc}enc)")
    return (bool(changed)), f"strip inputenc in {', '.join(changed)}"


#: ``\\usepackage``/``\\RequirePackage`` 名单内的 ``physics`` 装载点
#: (``\\b`` 界只保证不以字母续名——``{physics-tools}`` 这类命中由成员判定滤掉)。
_PHYS_LOAD_RE = _pkg_list_re("physics")
#: 源侧既有 ``\\input{physics.sty}`` 裸载点 —— 只 ``.sty`` 显式形真载 stub:
#: ``\\input{physics}``/``\\input{physics.tex}`` 走 kpathsea tex 格式只解析
#: ``physics``/``physics.tex`` (章节文件, 1206.5202 ``\\input{physics}`` 即
#: section 件), 永远摸不到 ``physics.sty`` —— ``need_input`` 检测与
#: ``\\makeatletter`` 包裹双侧都按 ``.sty`` 形收窄。
_PHYS_INPUT_RE = re.compile(r"\\input\s*\{?\s*physics\.sty(?![\w.-])")
#: 随源件内 ``\\input X.sty`` 站收集用的通用名单形 —— 与 ``_PHYS_INPUT_RE``
#: 同骨架, 名位放开到任意 stem (允许路径前缀 ``sub/foo.sty``)。
#: ``(?![\w.-])`` 防 ``.styx`` 半名误中。
_SHIP_STY_INPUT_RE = re.compile(
    r"\\input\s*\{?\s*[A-Za-z][A-Za-z0-9_./-]*\.sty(?![\w.-])"
)
#: ambient @ 事件 —— ``\\makeatletter``/``\\makeatother``/``\\catcode`@=N``/
#: ``\\catcode 64=N``/``\\catcode"40=N``/``\\catcode'100=N`` + 本族 restore cs
#: (``_SHIP_WRAP_*``/``_AT_LETTER_*`` 的复元符; 只裹非 letter 站 → 复元恒
#: other)。遮盖视图组作用域走查用 —— ``_SHIP_WRAP_*`` 自注的
#: ``\\catcode 64=11`` 事件使域内站点天然 at_letter 跳过 (幂等)。
_AMBIENT_AT_RE = re.compile(
    r"\\makeat(letter|other)(?![a-zA-Z])"
    r"|\\catcode\s*(?:`@|64|\"40|'100)\s*=\s*(\d+)"
    r"|\\TeXlate(?:At|StyIn)Restore(?![a-zA-Z])"
)
#: stub 内 ``\\ProvidesPackage{physics}`` —— ``\\input`` 路径下它仍置
#: ``ver@physics.sty`` → siunitx 的 ``\\@ifpackageloaded{physics}`` 照中。
_PHYS_PROVIDES_RE = re.compile(r"(\\Provides(?:Expl)?Package\s*\{)physics(\s*\})")
_PHYS_GUARD_MARK = "txlatephysstub"
_PHYS_STUB_GUARD = (
    "% fixloop: physics stub detached (siunitx \\@ifpackageloaded evasion)\n"
    "\\ifdefined\\txlatephysstub\\expandafter\\endinput\\fi\n"
    "\\let\\txlatephysstub\\relax\n"
)


def _detach_physics_loads(
    t: str, *, add_input: bool, letter_wrap: bool = True
) -> tuple[str, int]:
    r"""剥 ``physics`` 装载点并原位换 ``\\input{physics.sty}`` 续载 → (新文本, 摘除数)。

    独载 → 整命令换成 ``\\input`` 行; 列表成员 → 摘除元素 + 行后挂 ``\\input``。
    ``\\input`` 不进 ``ver@`` 注册表, stub 的 ``\\abs``/``\\norm`` 等定义照常
    生效。命中位取自 ``mask_tex`` 遮盖视图——``%`` 注释内的假装载点不动
    (注释里拼 ``\\input`` 会把续行冲出注释)。

    ``letter_wrap`` (``.tex`` 宿主=True): 裸 ``\\input`` 不挂 ``\\makeatletter``,
    stub 内 ``\\@undefined``/``\\@ifpackageloaded`` 族在 @=other 下碎成
    ``\\@``+裸字母 → 排版文本泄进 preamble 炸 Missing ``\\begin{document}``
    (1706.00240 physics.sty:13 实证)。``.sty``/``.cls`` 宿主 @ 本即 letter,
    加 ``\\makeatother`` 反而坏外层——传 False 走裸 ``\\input``。
    """
    masked = mask_tex(t)
    hits = []
    for m in _PHYS_LOAD_RE.finditer(masked):
        # before+after 是不含 physics 本体的花括号残件——回填本体再做元素级
        # 判定 (``{physics-tools}`` 的 ``\b`` 误命中由此滤掉)。
        pkgs = [p.strip() for p in (m["before"] + "physics" + m["after"]).split(",")]
        if "physics" in pkgs:
            hits.append((m, [p for p in pkgs if p and p != "physics"]))
    if not hits:
        return t, 0
    edits: list[tuple[int, int, str]] = []
    last = len(hits) - 1
    for i, (m, keep) in enumerate(hits):
        # 续载 ``\input`` 挂在文件序末站原位 (``add_input`` 由末站消费——
        # 旧逆序遍历的首枚迭代位)。
        if i == last and add_input:
            input_line = (
                _SHIP_WRAP_PRE + "\\input{physics.sty}" + _SHIP_WRAP_POST
                if letter_wrap
                else "\\input{physics.sty}"
            )
            ins = f"% fixloop: physics stub detached\n{input_line}"
            repl = (
                f"\\{m['cmd']}{m['opts'] or ''}{{{','.join(keep)}}}\n{ins}"
                if keep
                else ins
            )
        elif keep:
            repl = f"\\{m['cmd']}{m['opts'] or ''}{{{','.join(keep)}}}"
        else:
            ls = t.rfind("\n", 0, m.start()) + 1
            repl = (
                ""
                if t[ls : m.start()].strip()
                else "% fixloop: stripped " + m.group(0).strip()
            )
        edits.append((m.start(), m.end(), repl))
    return _splice(t, edits), len(hits)


def _scope_step(vis: str, pos: int) -> tuple[int, str | None]:
    r"""单步组作用域事件 → ``(新 pos, open/close/letter/other/None)``。

    ``\\X`` 双字符跳过 (``\\{`` 等转义不计深度); ``\\makeatletter``/
    ``\\makeatother``/``\\catcode`@=N``/``\\catcode 64=N``/restore cs 是
    letter/other 事件, 余字符不算事件。
    """
    c = vis[pos]
    if c == "\\":
        mm = _AMBIENT_AT_RE.match(vis, pos)
        if mm is not None:
            ev = (
                ("letter" if mm.group(1) == "letter" else "other")
                if mm.group(1) is not None
                else (
                    ("letter" if mm.group(2) == "11" else "other")
                    if mm.group(2) is not None
                    # 本族 restore cs —— 只裹非 letter 站, 复元恒 other
                    else "other"
                )
            )
            return mm.end(), ev
        return pos + 2, None
    if c == "{":
        return pos + 1, "open"
    if c == "}":
        return pos + 1, "close"
    return pos + 1, None


def _input_cmd_end(vis: str, m: re.Match[str]) -> int:
    r"""``\\input{…}`` 的 ``{`` 形随尾闭合 ``}`` 扩展 end；无 ``{`` → ``m.end()``，未随尾闭合 → ``-1``。"""
    if "{" not in m.group(0):
        return m.end()
    j = m.end()
    while j < len(vis) and vis[j].isspace():
        j += 1
    return j + 1 if j < len(vis) and vis[j] == "}" else -1


def _match_end(_vis: str, m: re.Match[str]) -> int:
    r"""名单形命令的站点尾 —— ``{[^}]*}`` 已随 match 自闭, ``end`` 即 ``m.end()``。"""
    return m.end()


def _scoped_sites(
    t: str,
    rx: re.Pattern[str],
    *,
    end_fn: Callable[[str, re.Match[str]], int] = _input_cmd_end,
) -> list[tuple[re.Match[str], int, bool]]:
    r"""遮盖视图顶层 live 站收集 → ``[(match, end, at_letter)]``。

    注释/verbatim 内假装载点不算 (``mask_tex`` 已遮), 宏体等 ``{}`` 组内
    站点不算 (深度 0 限定——组内命令是延迟或局部执行, 非顶层载点)。
    ``\\makeatletter``/``\\makeatother`` 按组局部语义入栈, ``at_letter``
    = 站点处 @ 是否已是 letter。``end_fn(vis, m)`` 定站点尾位, 返 ``-1``
    丢弃该站 (``_input_cmd_end`` 的 ``{`` 形未随尾闭合情形)。匹配本体不
    推游标 —— 下个命中前的走查把它当普通字符消费, 内部 ``{``/``}`` 照常
    配对计深。``rx`` 决定哪些命令算装载点。
    """
    vis = mask_tex(t)
    depth = 0
    at_letter = False
    stack: list[bool] = []
    pos = 0
    out: list[tuple[re.Match[str], int, bool]] = []
    for m in rx.finditer(vis):
        while pos < m.start():
            pos, ev = _scope_step(vis, pos)
            if ev == "open":
                depth += 1
                stack.append(at_letter)
            elif ev == "close":
                depth -= 1
                if stack:
                    at_letter = stack.pop()
            elif ev is not None:
                at_letter = ev == "letter"
        if depth == 0 and vis[m.start() : m.end()] == t[m.start() : m.end()]:
            end = end_fn(vis, m)
            if end >= 0:
                out.append((m, end, at_letter))
    return out


def _sty_input_sites(t: str, input_re: re.Pattern[str]) -> list[tuple[int, int, bool]]:
    r"""``\\input`` 顶层 live 站收集 → ``[(start, end, at_letter)]``。

    ``_scoped_sites`` 的 ``\\input`` 包装: ``end`` 对 ``{`` 形含随尾闭合
    ``}`` (``_input_cmd_end``; 被注释隔断等未闭合的站点丢弃)。``input_re``
    决定哪些 ``\\input`` 目标算装载点。
    """
    return [
        (m.start(), end, at_letter) for m, end, at_letter in _scoped_sites(t, input_re)
    ]


def _phys_sty_input_sites(t: str) -> list[tuple[int, int, bool]]:
    r"""``\\input{physics.sty}`` 顶层 live 站 —— ``_sty_input_sites`` 的 phys 特例。"""
    return _sty_input_sites(t, _PHYS_INPUT_RE)


def _wrap_sites(
    t: str, sites: list[tuple[int, int, bool]], pre: str, post: str
) -> tuple[str, int]:
    r"""站点序列原位套 ``pre``/``post`` 包裹 → (新文本, 包裹数)。

    ``at_letter`` 站跳过 —— 外围 @ 已是 letter, 包裹纯负资产。
    """
    pieces: list[str] = []
    prev, n = 0, 0
    for start, end, at_letter in sites:
        if at_letter:
            continue
        pieces.append(t[prev:start])
        pieces.append(pre)
        pieces.append(t[start:end])
        pieces.append(post)
        prev = end
        n += 1
    if not n:
        return t, 0
    pieces.append(t[prev:])
    return "".join(pieces), n


def _wrap_phys_sty_inputs(t: str) -> tuple[str, int]:
    r"""``\\input{physics.sty}`` 裸载点补 @ 存复包裹 → (新文本, 包裹数)。

    doc-native ``\\input`` 不挂 @=letter: ``.tex`` 宿主 @ 是 catcode-12,
    stub 内 ``\\@undefined``/``\\@ifpackageloaded`` 族碎成 ``\\@``+裸字母
    → undefined_cs 级联 (``\\let\\Re\\@undefined`` 断签名)。只包
    ``_phys_sty_input_sites`` 里未处 ``\\makeatletter`` 组的站点 ——
    包裹用 ``_SHIP_WRAP_*`` exact-restore 形 (宿主直写 ``\\catcode`@=11``
    绕过 ``\\makeatletter`` 时裸对尾段会强翻回 12, 存复形恒回原位),
    宏体内站点 (延迟执行语境) 不动。包裹只罩 ``\\input`` 命令本体。
    """
    return _wrap_sites(t, _phys_sty_input_sites(t), _SHIP_WRAP_PRE, _SHIP_WRAP_POST)


#: ``TeXlateStyInRestore`` 存复裸段对 —— ``_SHIP_WRAP_*`` 与 ``_SIU_PEACE_*``
#: 内饰共用同一 restore cs, 字面量由 ``_exact_restore_wrap`` 单源产出。
_STYIN_SEG = _exact_restore_wrap("TeXlateStyInRestore")
#: shipwrap 存复包裹对 —— ``vendor/stubs/svglov3.clo`` 同款 exact-restore
#: idiom: ``\\edef`` 先存 ``\\catcode 64`` 现值, ``=11`` 读件, 尾段复元。
#: 宿主 @ 语境不可知 (``\\documentclass``/``\\usepackage`` 载是 11, 裸
#: ``\\input`` 载是 12) —— 存复形两语境皆回原位; 裸
#: ``\\makeatletter``/``\\makeatother`` 对会把 @=letter 宿主的后续 @-cs
#: 强翻回 12 (svglov3.clo 头注: 1608.06693 ``15\\p@`` 实证)。restore cs
#: 名纯字母 —— 宿主可能正处 @=other, 名里带 ``@`` 自断签名。
_SHIP_WRAP_PRE = _STYIN_SEG[0] + " "
_SHIP_WRAP_POST = " " + _STYIN_SEG[1]


def _wrap_shipped_sty_inputs(t: str) -> tuple[str, int]:
    r"""``\\input X.sty`` 顶层 live 站补 @ 存复包裹 → (新文本, 包裹数)。

    随源 ``.cls``/``.sty`` 宿主面: 裸 ``\\input`` 以宿主当前 @ catcode
    读件, @=other 下载入件内全部 @-cs 断名 → Missing ``\\begin{document}``
    级联 (shipclscen census 族; aipproc.cls:10 ``\\input{aipproc.sty}`` 型)。
    只包 ``_sty_input_sites`` 里未处 ``\\makeatletter`` 组的站点 ——
    已在 letter 区的不重包, 宏体内站点 (延迟执行) 不动。
    """
    return _wrap_sites(
        t,
        _sty_input_sites(t, _SHIP_STY_INPUT_RE),
        _SHIP_WRAP_PRE,
        _SHIP_WRAP_POST,
    )


def _detach_in_tex_files(
    ctx: LoopCtx, stub: Path, exts: tuple[str, ...], *, need_input: bool
) -> tuple[list[str], list[str]]:
    r"""逐 tex 文件剥 physics 装载点 + 裸 ``\\input{physics.sty}`` 补 @ 包裹。

    ``.tex`` 宿主面 doc-native ``\\input{physics.sty}`` 站补
    ``\\makeatletter`` 对 (``\\input`` 不挂 @=letter, stub @-cs 在
    catcode-12 下碎裂) → (摘除文件名, 包裹文件名)。
    """
    changed: list[str] = []
    wrapped: list[str] = []
    for f in ctx.tex_files(exts):
        if f == stub:
            continue
        t = ctx.read(f)
        if t is None or "physics" not in t:
            continue
        is_tex = f.suffix.lower() == ".tex"
        nt, n = _detach_physics_loads(t, add_input=need_input, letter_wrap=is_tex)
        n_wrap = 0
        if is_tex:
            nt, n_wrap = _wrap_phys_sty_inputs(nt)
        if not (n or n_wrap) or nt == t:
            continue
        ctx.write(f, nt)
        if n:
            changed.append(f.name)
            need_input = False
        if n_wrap:
            wrapped.append(f.name)
    return changed, wrapped


def physics_stub_detach(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Bundled ``physics.sty`` stub 撞 siunitx ``\\@ifpackageloaded{physics}`` → 脱注册续载。

    实证 (1706.00240 wall-3, fixer-apjbbx verification.txt): e-print 捆绑
    2012 手写 mini-physics (``\\dbar\\ord\\bra\\ket`` 族), siunitx v3
    ``\\AtBeginDocument`` 对 ``\\@ifpackageloaded{physics}`` 硬报错 →
    ``\\begin{document}`` 处 undefined_cs。四步: ``\\usepackage`` 名单剥
    physics 原位改 ``\\input{physics.sty}`` (``\\input`` 不进 ``ver@`` 注册)
    + doc-native ``\\input{physics.sty}`` 裸载点补 ``\\makeatletter`` 对
    + stub ``\\ProvidesPackage{physics}`` 更名 ``physics-stub`` + 双载守卫。
    真 CTAN physics (xparse ``\\DeclareDocumentCommand`` 形) 弃权——那与
    siunitx 是 ``\\qty`` 语义真冲突, 归 LLM。
    """
    del eng, payload
    stub = ctx.wdir / "physics.sty"
    st = ctx.read(stub) if stub.is_file() else None
    if st is None:
        return False, "no bundled physics.sty at wdir root"
    real_marker = str(params.get("real_marker") or r"\\DeclareDocumentCommand")
    if re.search(real_marker, st):
        return False, "physics.sty is xparse-form (real CTAN), not stub"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    # 顶层 live ``\\input{physics.sty}`` 站才算"已在载": 注释内/宏体内
    # (延迟执行, 未必触发) 命中不算 —— 漏载致命, 双载由 stub 守卫兜底。
    need_input = not _phys_sty_input_sites(ctx.source_blob())
    changed, wrapped = _detach_in_tex_files(ctx, stub, exts, need_input=need_input)
    renamed = _PHYS_PROVIDES_RE.sub(r"\g<1>physics-stub\g<2>", st)
    neut = renamed
    if (changed or wrapped or neut != st) and _PHYS_GUARD_MARK not in neut:
        neut = _PHYS_STUB_GUARD + neut
    if neut != st:
        ctx.write(stub, neut)
    if not changed and not wrapped and renamed == st:
        return False, "no physics load sites to detach"
    parts = []
    if changed:
        parts.append(f"\\input detach in {', '.join(changed)}")
    if wrapped:
        parts.append(f"@catcode wrap in {', '.join(wrapped)}")
    if renamed != st:
        parts.append("ProvidesPackage neutered")
    if neut != renamed:
        parts.append("reload guard")
    return True, "physics stub detached: " + "; ".join(parts)


#: ``\\usepackage``/``\\RequirePackage`` 名单装载点 (``_PKG_LOAD_RE`` 别名) —
#: siunitx 元素级判定在站点收集后做 (``{siunitx-blah}`` 这类误中由此滤掉)。
_SIU_LIST_RE = _PKG_LOAD_RE
#: siunitx v3 ``\\__siunitx_load_check:n`` 的不兼容名单 —— 装载时全查,
#: ``\\AtBeginDocument`` 复查前三 (SIunits/sistyle/units)。``ver@X.sty``
#: 置 ``\\relax`` 即从 ``\\@ifpackageloaded`` 注销 (physics_stub_detach
#: 同机理); 未载过的名 ``\\csname`` 展开本即 ``\\relax``, 幂等无害。
_SIU_INCOMPAT_PKGS = ("SIunits", "sistyle", "units", "unitsdef", "fancyunits")
#: 包裹对 —— exact-restore idiom 同 ``_SHIP_WRAP_*`` (内饰共用 ``_STYIN_SEG``
#: 裸段, 换行替空格作分隔): 宿主 @ 语境不可知, ``\\edef`` 存现值 ``=11``
#: 读本族 ``\\@ifundefined``, 尾段恒回原位 (裸 ``\\makeatother`` 会把
#: @=letter 宿主的后续 @-cs 强翻回 12)。
_SIU_PEACE_PRE = (
    "% fixloop: siunitx incompatible-pkg evasion shim\n"
    + _STYIN_SEG[0]
    + "\n"
    + "\\@ifundefined{TeXlateSavedUnit}"
    "{\\@ifundefined{unit}{}{\\let\\TeXlateSavedUnit\\unit\\let\\unit\\relax}}{}\n"
    + "".join(
        f"\\expandafter\\let\\csname ver@{p}.sty\\endcsname\\relax\n"
        for p in _SIU_INCOMPAT_PKGS
    )
    + _STYIN_SEG[1]
    + "\n"
)
#: 载后复元 ``\\unit`` —— siunitx ``\\NewDocumentCommand\\unit``(sty:9494)
#: 在 ``\\unit``=``\\relax`` 下当未定义处理正常落定义, 此处把 units 语义
#: 装回 (units 的 ``\\unit[value]{unit}`` 与 siunitx ``O{} m`` 签名不兼容,
#: 用 units 语法的文档必须复元, 2105.03729 ``\\unit[38]{mW}`` 实证)。
_SIU_PEACE_POST = (
    "\n" + _STYIN_SEG[0] + "\\@ifundefined{TeXlateSavedUnit}{}"
    "{\\let\\unit\\TeXlateSavedUnit\\let\\TeXlateSavedUnit\\relax}" + _STYIN_SEG[1]
)


def _siunitx_load_sites(t: str) -> list[tuple[int, int, bool]]:
    r"""Siunitx 装载命令顶层 live 站 → ``[(start, end, at_letter)]``。

    ``_scoped_sites`` 走查 (遮盖视图 + 深度 0 + ambient @ 栈), 宏体/组内
    ``\\usepackage`` 不算 (延迟执行语境, 注入文本会在定义点断 ``\\@`` 签名)。
    ``end`` 即 match 本体尾 (``_match_end``) —— 名单 ``[^}]*`` 不含 ``}``,
    命令括号已自闭。``at_letter`` 本 lane 不消费, 随统一三元组带回。
    """
    out: list[tuple[int, int, bool]] = []
    for m, end, at_letter in _scoped_sites(t, _SIU_LIST_RE, end_fn=_match_end):
        pkgs = [p.strip() for p in m["names"].split(",")]
        if "siunitx" in pkgs:
            out.append((m.start(), end, at_letter))
    return out


def siunitx_incompat_peace(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Siunitx v3 不兼容名单 (SIunits/sistyle/units/unitsdef/fancyunits) → 注销续载。

    实证 (2105.03729, stagerun-loop3): ``\\usepackage[loose]{units}`` 先于
    ``\\usepackage{siunitx}`` —— siunitx ``\\__siunitx_load_check:n`` 对
    ``\\@ifpackageloaded`` 硬报错 (装载时 + ``\\AtBeginDocument`` 双查),
    且 ``\\NewDocumentCommand\\unit`` 撞 units 已定义 → already_def。
    三步: 装载点前置 ``ver@X.sty=\\relax`` 注销全部不兼容名 + 存/摘
    ``\\unit`` (``\\NewDocumentCommand`` 把 ``\\relax`` 当未定义) + 载后
    复元 ``\\unit`` 为 units 语义。不兼容包本体仍载——只是对 siunitx
    检查隐身 (``\\nicefrac``/``\\unit`` 语义全留)。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "siunitx" not in t:
            continue
        sites = _siunitx_load_sites(t)
        if not sites:
            continue
        edits: list[tuple[int, int, str]] = []
        for start, end, _at_letter in sites:
            ls = t.rfind("\n", 0, start) + 1
            edits.append((ls, ls, _SIU_PEACE_PRE))
            edits.append((end, end, _SIU_PEACE_POST))
        ctx.write(f, _splice(t, edits))
        changed.append(f"{f.name}(x{len(sites)})")
    return (bool(changed)), f"siunitx evasion shim in {', '.join(changed)}"


def shipped_sty_input_wrap(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""随源 ``.cls``/``.sty``/``.tex`` 件内 ``\\input X.sty`` 站补 @ 存复包裹 (shipclscen)。

    input_sty_to_usepackage/input_sty_209_requirepkg 两臂只管 doc 侧
    ``.tex`` 导言区改写 —— 随源件内部裸 ``\\input`` 与前瞻闸够不着的
    站点 (``\\begin{document}`` 缺席的 fragment .tex 等) 归本 builtin
    补位。包裹是存复形 (``\\edef`` 存 ``\\catcode 64`` → ``=11`` 读件
    → 复元), @=letter 宿主下是恒等变换, 语义保持。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".cls", ".sty", ".tex"))
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "\\input" not in t:
            continue
        nt, n = _wrap_shipped_sty_inputs(t)
        if n and nt != t:
            ctx.write(f, nt)
            changed.append(f"{f.name}(x{n})")
    return (bool(changed)), f"@catcode exact-restore wrap in {', '.join(changed)}"


def font_sub_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""MF-only 字体包 → Type1 近亲 shim (docs/08:275, ctanfetch-probe §3.4)。

    ``\\usepackage{bbm}`` → ``\\usepackage{dsfont}`` + cs 族改写
    (``\\mathbbm``→``\\mathds`` 等)。物理字体投放对 tectonic xdvipdfmx
    是死路, 只能靠改写换 bundle 内字体族。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    shim_map: dict[str, dict[str, Any]] = params.get("shim_map") or {}
    changed = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for old_pkg, spec in shim_map.items():
            new_pkg = spec.get("usepackage")
            if not new_pkg:
                continue

            # 装载点: {bbm} 精确 / {a,bbm,c} 列表元素 (其余不动); 遮盖视图
            # 定位 —— 注释/verbatim 内的假装载点与假 cs 调用不改写。
            edits = [
                (
                    m.start(),
                    m.end(),
                    m["head"]
                    + "{"
                    + ",".join(
                        new_pkg if p == old_pkg else p
                        for p in [x.strip() for x in m["names"].split(",")]
                    )
                    + "}",
                )
                for m in _live_matches(_PKG_LOAD_RE, nt)
                if old_pkg in [x.strip() for x in m["names"].split(",")]
            ]
            if edits:
                nt = _splice(nt, edits)
            for old_cs, new_cs in (spec.get("cs_map") or {}).items():
                cs_rx = re.compile(rf"\\{re.escape(old_cs)}\b")
                edits = [
                    (m.start(), m.end(), "\\" + new_cs)
                    for m in _live_matches(cs_rx, nt)
                ]
                if edits:
                    nt = _splice(nt, edits)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f.name)
    return (bool(changed)), f"font shim applied in {', '.join(changed)}"


#: Xy-pic 扩展缺失句式 → 扩展名抽取 (err_head ∪ fixloop log 双扫面):
#: A ``only available when <ext> extension loaded`` —— xyarrow.tex:527
#:   curve/arrow 钩族 (``@/.../``/``@(...)``/``@`{...}`` 形);
#: B ``<word> feature not loaded`` —— xygraph.tex:163/182/186 的
#:   ``matrix``/``poly(gon)``/``(ellipse+)arc`` 形, 括号段是注释性修饰,
#:   真扩展名 = 剥 ``(...)`` 后的残余词 (poly/arc/matrix); 词首括号注释
#:   ``(ellipse+)`` 的 ``+`` 断捕获, 捕获从失衡 ``)`` 起 → 归一时再剥残余
#:   裸括号。
#: 词间 ``\s+``: TeX 日志 max_print_line=79 折行, "curve\nextension"
#: 跨行是常态 (2607.14648 实证 err_head 原文折行)。
_XY_EXT_ERR_RES = (
    re.compile(r"only available when ([A-Za-z]+)\s+extension\s+loaded"),
    re.compile(r"([A-Za-z()]+)\s+feature\s+not\s+loaded"),
)

#: ``\\usepackage``/``\\RequirePackage`` 名单装载点 (``_PKG_LOAD_RE`` 别名) ——
#: 元素级 xy/xypic 判定在站点收集后做 (``xypic.sty`` 是 ``\\input{xy.sty}``
#: +``\\xyoption{v2}`` 薄壳, ``xy`` 直载 ``xy.sty``)。
_XY_LOAD_RE = _PKG_LOAD_RE


def _xy_ext_names(ctx: LoopCtx) -> list[str]:
    r"""err_head → 全日志序扫缺失 Xy-pic 扩展名 (去重保序)。

    dedup 键 ``{rule}:None`` 全族共位 —— 一次应用必须把本轮日志里报
    出的扩展全收, 否则同签残错下轮重复点火。
    """
    out: list[str] = []
    for src in (ctx.err_head or "", _fixloop_log(ctx)):
        for rx in _XY_EXT_ERR_RES:
            for m in rx.finditer(src):
                ext = re.sub(r"\([^)]*\)", "", m.group(1))
                ext = re.sub(r"[()]", "", ext)
                if re.fullmatch(r"[a-z]+", ext) and ext not in out:
                    out.append(ext)
    return out


def _xy_missing_loads(t: str, exts: list[str]) -> tuple[str, int]:
    r"""文件内首个 live ``{..,xy|xypic,..}`` 装载点后插 ``\\xyoption{<ext>}``。

    遮盖视图命中 + span 回切 (``_live_matches``) —— 注释/verbatim 内假
    装载点不动。幂等只认 live ``\\xyoption{<ext>}``: 注释里躺着的同名
    死调用不挡活注入 (``_live_matches`` 同面收集已载扩展集)。
    """
    loaded = {
        m.group(1)
        for m in _live_matches(re.compile(r"\\xyoption\s*\{\s*([A-Za-z]+)\s*\}"), t)
    }
    need = [e for e in exts if e not in loaded]
    if not need:
        return t, 0
    for m in _live_matches(_XY_LOAD_RE, t):
        pkgs = [p.strip() for p in m["names"].split(",")]
        if not ({"xy", "xypic"} & set(pkgs)):
            continue
        ins = "".join(rf"\xyoption{{{e}}}" for e in need)
        return t[: m.end()] + "\n" + ins + t[m.end() :], len(need)
    return t, 0


def xy_option_load(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Xy-pic ``<ext> extension/feature not loaded`` → 装载点后插 ``\\xyoption{<ext>}``。

    实证 (2607.14648 zh+base, stagerun-m1k-2026-09-19): 群载
    ``\\usepackage{amsmath,...,xypic}`` 未开 curve 扩展, ``\\ar@/_1pc/[rr]``
    钩形炸 "only available when curve extension loaded" (file-line 归
    other)。``[curve]{xypic}`` 形加不上 —— 群载选项全包共享且元素不可
    拆 (per-pkg 选项无解); ``\\xyoption{<ext>}`` 是 xy.tex:1944 原生请求
    宏 (``\\xyinputorelse@{xy<ext>}`` → ``\\input{xy<ext>.tex}``), 装载点
    后任意 preamble 位调用即补载, 语义同官方 ``[curve]`` 选项通路
    (``\\DeclareOption*`` catch-all 落的也是它)。
    """
    del eng, payload
    exts = _xy_ext_names(ctx)
    if not exts:
        return False, "no xy extension names in err_head/log"
    file_exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed: list[str] = []
    for f in ctx.tex_files(file_exts):
        t = ctx.read(f)
        if t is None or "xy" not in t:
            continue
        nt, n = _xy_missing_loads(t, exts)
        if n and nt != t:
            ctx.write(f, nt)
            changed.append(f"{f.name}(+{','.join(exts)})")
    return (bool(changed)), f"xyoption inject in {', '.join(changed)}"
