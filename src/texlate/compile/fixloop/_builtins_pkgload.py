r"""_builtins_pkgload — ``\\usepackage``/``\\documentclass`` 装载点改写原语 (C3 拆分)。

既有文件内 package 装载面外科: option clash 选项合并 / inputenc 整包剥离 /
physics stub 脱注册续载 / MF-only 字体包换 Type1 近亲 shim。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _USE_RE,
    _drop_pkg_loads,
    _live_matches,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx


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
            if payload in [x.strip() for x in m.group(5).split(",")]
        ]
        if len(hits) < 2:  # noqa: PLR2004 - 2 = 重复加载的最小命中数
            continue
        first, later = hits[0], hits[-1]
        opts1 = first.group(4) or ""
        opts2 = later.group(4) or ""
        merged = ",".join(
            dict.fromkeys(o for o in (opts1 + "," + opts2).split(",") if o)
        )
        m0 = first.group(0)
        if first.group(3):
            first_new = m0.replace(first.group(3), f"[{merged}]", 1)
        else:  # 首个加载无 [opts] → 在花括号前插 [merged]; spike L486
            # `str.replace("", ...)` 会逐位插入, 此处修掉该潜伏 bug
            brace = m0.rfind("{")
            first_new = m0[:brace] + f"[{merged}]" + m0[brace:]
        t = (
            t[: first.start()]
            + first_new
            + t[first.end() : later.start()]
            + "% fixloop: merged into earlier \\usepackage\n% "
            + later.group(0).replace("\n", "\n% ")
            + t[later.end() :]
        )
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
        nt, n_enc = _INPUTENCODING_RE.subn("", nt)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f"{f.name}(-{n_load}load,-{n_enc}enc)")
    return (bool(changed)), f"strip inputenc in {', '.join(changed)}"


#: ``\\usepackage``/``\\RequirePackage`` 名单内的 ``physics`` 装载点
#: (``\\b`` 界只保证不以字母续名——``{physics-tools}`` 这类命中由成员判定滤掉)。
_PHYS_LOAD_RE = re.compile(
    r"\\(usepackage|RequirePackage)(\s*\[[^\]\n]*\])?\s*\{([^}]*)\bphysics\b([^}]*)\}"
)
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
        # g3+g4 是不含 physics 本体的花括号残件——回填本体再做元素级判定
        # (``{physics-tools}`` 的 ``\b`` 误命中由此滤掉)。
        pkgs = [p.strip() for p in (m.group(3) + "physics" + m.group(4)).split(",")]
        if "physics" in pkgs:
            hits.append((m, [p for p in pkgs if p and p != "physics"]))
    if not hits:
        return t, 0
    out = t
    need = add_input
    for m, keep in reversed(hits):
        if need:
            need = False
            input_line = (
                _SHIP_WRAP_PRE + "\\input{physics.sty}" + _SHIP_WRAP_POST
                if letter_wrap
                else "\\input{physics.sty}"
            )
            ins = f"% fixloop: physics stub detached\n{input_line}"
            repl = (
                f"\\{m.group(1)}{m.group(2) or ''}{{{','.join(keep)}}}\n{ins}"
                if keep
                else ins
            )
        elif keep:
            repl = f"\\{m.group(1)}{m.group(2) or ''}{{{','.join(keep)}}}"
        else:
            ls = t.rfind("\n", 0, m.start()) + 1
            repl = (
                ""
                if t[ls : m.start()].strip()
                else "% fixloop: stripped " + m.group(0).strip()
            )
        out = out[: m.start()] + repl + out[m.end() :]
    return out, len(hits)


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


def _sty_input_sites(t: str, input_re: re.Pattern[str]) -> list[tuple[int, int, bool]]:
    r"""``\\input`` 顶层 live 站收集 → ``[(start, end, at_letter)]``。

    遮盖视图走查: 注释/verbatim 内假装载点不算 (``mask_tex`` 已遮),
    宏体等 ``{}`` 组内站点不算 (深度 0 限定——组内 ``\\input`` 是延迟或
    局部执行, 非顶层载点)。``\\makeatletter``/``\\makeatother`` 按组局部
    语义入栈, ``at_letter`` = 站点处 @ 是否已是 letter。``end`` 对 ``{``
    形含随尾闭合 ``}`` (被注释隔断等未闭合的站点丢弃)。匹配本体不推
    游标 —— 下个命中前的走查把它当普通字符消费, 内部 ``{``/``}`` 照常
    配对计深。``input_re`` 决定哪些 ``\\input`` 目标算装载点。
    """
    vis = mask_tex(t)
    depth = 0
    at_letter = False
    stack: list[bool] = []
    pos = 0
    out: list[tuple[int, int, bool]] = []
    for m in input_re.finditer(vis):
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
            end = _input_cmd_end(vis, m)
            if end >= 0:
                out.append((m.start(), end, at_letter))
    return out


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


#: shipwrap 存复包裹对 —— ``vendor/stubs/svglov3.clo`` 同款 exact-restore
#: idiom: ``\\edef`` 先存 ``\\catcode 64`` 现值, ``=11`` 读件, 尾段复元。
#: 宿主 @ 语境不可知 (``\\documentclass``/``\\usepackage`` 载是 11, 裸
#: ``\\input`` 载是 12) —— 存复形两语境皆回原位; 裸
#: ``\\makeatletter``/``\\makeatother`` 对会把 @=letter 宿主的后续 @-cs
#: 强翻回 12 (svglov3.clo 头注: 1608.06693 ``15\\p@`` 实证)。restore cs
#: 名纯字母 —— 宿主可能正处 @=other, 名里带 ``@`` 自断签名。
_SHIP_WRAP_PRE = (
    r"\edef\TeXlateStyInRestore{\catcode 64=\the\catcode 64\relax}"
    r"\catcode 64=11\relax "
)
_SHIP_WRAP_POST = r" \TeXlateStyInRestore"


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
    r"""MF-only 字体包 → Type1 近亲 shim (docs/08:275, ctanfetch-probe §3.5)。

    ``\\usepackage{bbm}`` → ``\\usepackage{dsfont}`` + cs 族改写
    (``\\mathbbm``→``\\mathds`` 等)。物理字体投放对 tectonic xdvipdfmx
    是死路, 只能靠改写换 bundle 内字体族。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    shim_map: dict[str, dict[str, Any]] = params.get("shim_map") or {}
    changed = []
    load_pat = re.compile(
        r"(\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*)\{([^}]*)\}"
    )
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for old_pkg, spec in shim_map.items():
            new_pkg = spec.get("usepackage")
            if not new_pkg:
                continue

            # 装载点: {bbm} 精确 / {a,bbm,c} 列表元素 (其余不动)
            def _sw(m: re.Match[str], _o: str = old_pkg, _n: str = new_pkg) -> str:
                parts = [x.strip() for x in m.group(2).split(",")]
                if _o not in parts:
                    return m.group(0)
                return (
                    m.group(1)
                    + "{"
                    + ",".join(_n if p == _o else p for p in parts)
                    + "}"
                )

            nt = load_pat.sub(_sw, nt)
            for old_cs, new_cs in (spec.get("cs_map") or {}).items():
                nt = re.sub(rf"\\{old_cs}\b", rf"\\{new_cs}", nt)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f.name)
    return (bool(changed)), f"font shim applied in {', '.join(changed)}"
