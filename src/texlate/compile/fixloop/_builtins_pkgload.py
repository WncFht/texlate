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
#: 源侧既有 ``\\input{physics}`` 裸载点 —— 裸 ``\\input`` 本就不进注册表, 不重复补。
_PHYS_INPUT_RE = re.compile(r"\\input\s*\{?\s*physics(?:\.sty|\.tex)?(?![\w.-])")
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
                "\\makeatletter\\input{physics.sty}\\makeatother"
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


def _detach_in_tex_files(
    ctx: LoopCtx, stub: Path, exts: tuple[str, ...], *, need_input: bool
) -> list[str]:
    r"""逐 tex 文件剥 physics 装载点 (首个文件补 ``\\input`` 续载) → 改动文件名。"""
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        if f == stub:
            continue
        t = ctx.read(f)
        if t is None or "physics" not in t:
            continue
        nt, n = _detach_physics_loads(
            t, add_input=need_input, letter_wrap=f.suffix.lower() == ".tex"
        )
        if not n or nt == t:
            continue
        ctx.write(f, nt)
        changed.append(f.name)
        need_input = False
    return changed


def physics_stub_detach(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Bundled ``physics.sty`` stub 撞 siunitx ``\\@ifpackageloaded{physics}`` → 脱注册续载。

    实证 (1706.00240 wall-3, fixer-apjbbx verification.txt): e-print 捆绑
    2012 手写 mini-physics (``\\dbar\\ord\\bra\\ket`` 族), siunitx v3
    ``\\AtBeginDocument`` 对 ``\\@ifpackageloaded{physics}`` 硬报错 →
    ``\\begin{document}`` 处 undefined_cs。三步: ``\\usepackage`` 名单剥
    physics 原位改 ``\\input{physics.sty}`` (``\\input`` 不进 ``ver@`` 注册)
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
    need_input = _PHYS_INPUT_RE.search(mask_tex(ctx.source_blob())) is None
    changed = _detach_in_tex_files(ctx, stub, exts, need_input=need_input)
    renamed = _PHYS_PROVIDES_RE.sub(r"\g<1>physics-stub\g<2>", st)
    neut = renamed
    if (changed or neut != st) and _PHYS_GUARD_MARK not in neut:
        neut = _PHYS_STUB_GUARD + neut
    if neut != st:
        ctx.write(stub, neut)
    if not changed and renamed == st:
        return False, "no physics load sites to detach"
    parts = []
    if changed:
        parts.append(f"\\input detach in {', '.join(changed)}")
    if renamed != st:
        parts.append("ProvidesPackage neutered")
    if neut != renamed:
        parts.append("reload guard")
    return True, "physics stub detached: " + "; ".join(parts)


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
