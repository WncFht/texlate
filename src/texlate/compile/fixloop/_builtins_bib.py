r"""_builtins_bib — .bbl/.bib 族修复原语 (C3 拆分)。

tectonic stub bbl 断链改写 / 捆绑旧版 .bbl biber 重生成 /
ADS 时代 cite-key 裸 ``&``/``_`` 双侧一致消毒 /
数学域裸 cite 族 ``\\mbox`` 包裹 (invalid_in_math 签名臂)。
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.latex209 import wrap_math_cites
from texlate.textutil import (
    AUX_CITEKEY_RE,
    BIBITEM_KEY_RE,
    CITE_FAMILY_RE,
    mask_tex,
)

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx

from texlate.compile.fixloop._builtins_common import (
    _fixloop_log,
    _live_matches,
    _splice,
)

#: 同 normalize._AUTOBIB_DISARM —— revtex 系 ``\bibliography`` 顺带解除
#: end-doc ``\auto@bib`` 探测；裸 ``\input`` 改写必须补回，否则
#: ``\test@bbl@sw`` 在 vbox 排印 cite key 必需组（_/&/$ → in-math 级联 +
#: 三读重复书目）。``\ifcsname`` 守卫使非 revtex 工程零操作。
#: csname 形零字面 ``@`` —— ``\bibliography`` 站可落在已 tokenize 的
#: def 体内 (2105.11398 ``\newcommand{\showbib}`` 实证: 旧
#: ``\makeatletter\@ifundefined`` 形在 @=12 预读体里成 ``\@``+裸字母
#: → ``\showbib`` 调用点 vmode spacefactor 炸), csname 任意 catcode 同读。
#: 名扫段内每个 ``@`` 都写 ``\string@``: doc 激活 @ (``\MakeShortVerb{\@}``
#: → @=13) 时裸 @ token 在 \ifcsname/\csname 名扫里被当 active cs 展开
#: → Missing \endcsname (1107.0063 实证); \string 取记号产 catcode-12
#: 字面 @ 字符, @=11/12/13 三态同名同读。
_AUTOBIB_DISARM = (
    r"\ifcsname auto\string@bib\endcsname"
    r"\expandafter\let\csname auto\string@bib\expandafter\endcsname"
    r"\csname \string@empty\endcsname\fi"
)


def bbl_stub_rewrite(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Tectonic stub bbl 断链: 有 .bbl 无 .bib → ``\\bibliography{x}`` → ``\\input{main.bbl}``。

    实证根因 (ctanfetch-probe §3.2): tectonic 自动 bibtex 在无 .bib 时
    生成 24 行 stub bbl, 在内存文件层遮蔽磁盘真 bbl → 空 thebibliography。

    与 ``normalize.use_bundled_bibliography`` 同口径收口: 只认含
    ``\begin{thebibliography}`` 的真 bbl (24 行 stub/空壳不接);
    ``\input`` 目标按编译 cwd (``main.parent``) 落 relpath —— 嵌套稿
    引裸 basename 会断 (kpathsea 按 cwd 解析); 遮盖视图定位全量改写
    —— 注释/verbatim 内假装载点不动, live 多站仍各印 (multibib 逐
    call-site 本义, 非首站截断)。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    bbls = {
        p.stem: p
        for p in sorted(ctx.wdir.rglob("*.bbl"))
        if "\\begin{thebibliography}" in (ctx.read(p) or "")
    }
    if not bbls:
        return False, "no usable .bbl in project"
    main = ctx.main_path()
    stem = main.stem if main is not None else None
    bbl = bbls.get(stem) or next(iter(bbls.values()))
    base = main.parent if main is not None else ctx.wdir
    target = PurePosixPath(os.path.relpath(bbl, base)).as_posix()
    if ".." in PurePosixPath(target).parts:
        return False, "bbl target escapes compile cwd"
    pat = re.compile(r"\\bibliography(\[[^\]]*\])?\{[^}]*\}")
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "\\bibliography" not in t:
            continue
        edits = [
            (m.start(), m.end(), _AUTOBIB_DISARM + "\n\\input{" + target + "}")
            for m in _live_matches(pat, t)
        ]
        if not edits:
            continue
        nt = _splice(t, edits)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    return (
        changed > 0
    ), f"\\bibliography -> \\input{{{target}}} in {changed} files"


#: ``.bbl`` 头标 ``bbl format version X.Y`` (biber 产物首行) —— 版本元组提取。
_BBL_VER_RE = re.compile(rb"bbl format version (\d+)\.(\d+)")


def _bbl_format_version(bbl: Path) -> tuple[int, int] | None:
    """``.bbl`` 头标 ``bbl format version X.Y`` → ``(X, Y)``; 无标/读失败 → ``None``。"""
    try:
        head = bbl.read_bytes()[:2048]
    except OSError:
        return None
    m = _BBL_VER_RE.search(head)
    return (int(m.group(1)), int(m.group(2))) if m else None


def bbl_regen(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Bundled 旧版 .bbl 撞新 biblatex → ``biber <stem>`` 就地重生成 (.bcf 在场)。

    实证根因 (2009.11064): e-print 捆绑 biber <3.3 格式 .bbl, TL biblatex 3.21
    拒载 —— ``\\sortlist`` undefined / ``File 'ms.bbl' is wrong format version``;
    .bcf+.bib 在场即 ``biber <stem>`` 重生成正确版本 .bbl (输出落 .bcf 同目录,
    嵌套亦直传 wdir 相对 stem)。biber 缺席 → run_tool rc≠0 fail-safe。

    wall-2 (1706.00240, fixer-apjbbx verification.txt): biber rc=2 对陈旧
    .bcf/.bbl 会**自删** stem.bbl ("malformed ... Deleted")——清场即 progress,
    旧实现 ``if not done: return False`` 白做; 残留 bbl 头标
    ``bbl format version <3.0`` 同理是 poison (biblatex 硬拒), 删除后变
    "no bbl" 软缺——无文献但出 PDF, 比硬错强。
    """
    del eng, payload, params
    bcfs = sorted(ctx.wdir.rglob("*.bcf"))
    if not bcfs:
        return False, "no .bcf in project"
    done: list[str] = []
    dropped: list[str] = []
    failed: list[str] = []
    for bcf in bcfs:
        stem = str(bcf.relative_to(ctx.wdir).with_suffix(""))
        bbl = bcf.with_suffix(".bbl")
        had_bbl = bbl.exists()
        rc, _out, to = ctx.run_tool(["biber", stem], 60)
        if rc == 0 and not to:
            done.append(bcf.name)
            ctx.invalidate(bbl)
            continue
        if had_bbl and not bbl.exists():
            # biber 自删 poison (陈旧格式拒载清场) —— 真实盘变, 计 progress
            ctx.invalidate(bbl)
            dropped.append(f"{bbl.name}(biber-rm)")
        elif (
            bbl.is_file()
            and (ver := _bbl_format_version(bbl)) is not None
            and ver < (3, 0)  # bbl 格式主版本门 (biblatex 3.x 硬拒 <3.0)
        ):
            bbl.unlink()
            ctx.invalidate(bbl)
            dropped.append(f"{bbl.name}(fmt {ver[0]}.{ver[1]})")
        else:
            failed.append(f"{bcf.name} rc={rc}{'/timeout' if to else ''}")
    if not done and not dropped:
        return False, f"biber regen failed: {'; '.join(failed)}"
    parts: list[str] = []
    if done:
        parts.append(f"regen: {', '.join(done)}")
    if dropped:
        parts.append(f"stale-dropped: {', '.join(dropped)}")
    if failed:
        parts.append(f"failed: {'; '.join(failed)}")
    return True, "; ".join(parts)


#: cite/bib 键面词法单源已并 ``texlate.textutil`` (``CITE_FAMILY_RE``/
#: ``BIBITEM_KEY_RE``/``AUX_CITEKEY_RE`` 顶名直引)——judge/slotrev 借调
#: 本叶私名面的分层倒置随 F2 解清。


def _rewrite_keylists(
    text: str, rx: re.Pattern[str], *, masked: bool
) -> tuple[str, int]:
    r"""``rx`` 组1 键表逐键 ``&``→``A``、``_``→``-``；返回 (新文本, 改写数)。

    ``masked=True`` 在 ``mask_tex`` 视图上定位、原文上拼接——注释/verbatim
    内同形 token 不改写（键串是查找语义，展示性出现不必动）。
    """
    view = mask_tex(text) if masked else text
    edits: list[tuple[int, int, str]] = []
    for m in rx.finditer(view):
        keys = m.group(1)
        if "&" not in keys and "_" not in keys:
            continue
        new = ",".join(k.replace("&", "A").replace("_", "-") for k in keys.split(","))
        edits.append((m.start(1), m.end(1), new))
    return _splice(text, edits), len(edits)


def citekey_sanitize(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""ADS/apj.bst 时代 .bbl cite-key 裸 ``&``/``_`` → 双侧一致重写。

    实证根因 (apj-bib-scout §S4, 11 格)：老导出 key 的 ``&``（A&A bibcode）/
    ``_``（Allen_90/GW170104_main 形）在现代内核 ``\bibitem``/标签机制下炸
    ``Missing $ inserted``/``Misplaced alignment tab``——.bbl ``\bibitem{key}``
    定义点与全部 .tex ``\cite`` 族引用点必须同图改写，单侧改 = 引用断链。
    .aux 残留 ``\bibcite``/``\citation`` 陈旧键同源改写（防 undefined-citation
    残响）。
    """
    del eng, payload
    tex_exts = tuple(params.get("tex_exts") or (".tex",))
    gen_map = (
        (".bbl", BIBITEM_KEY_RE),
        (".bbl", CITE_FAMILY_RE),
        (".aux", AUX_CITEKEY_RE),
    )
    changed: list[str] = []
    for f in ctx.tex_files(tex_exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = _rewrite_keylists(t, CITE_FAMILY_RE, masked=True)
        if n:
            ctx.write(f, nt)
            changed.append(f"{f.name}({n})")
    for ext, rx in gen_map:
        for f in ctx.tex_files((ext,)):
            t = ctx.read(f)
            if t is None:
                continue
            nt, n = _rewrite_keylists(t, rx, masked=False)
            if n:
                ctx.write(f, nt)
                changed.append(f"{f.name}({n})")
    if not changed:
        return False, "no unsafe cite keys"
    return True, f"sanitize cite keys &->A/_->-: {', '.join(changed)}"


#: biber/biblatex bcf 版本错配签名——biber stdout 被 tectonic 以
#: ``! the external tool exited`` 形态 dump 进 xetex log:
#: ``Found biblatex control file version 3.8, expected version 3.11.``
_BIBER_SKEW_RE = re.compile(
    r"biblatex control file version ([\d.]+), expected version ([\d.]+)"
)


def biber_biblatex_skew_route(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """biber/biblatex 版本错配 → ``REJECT: route=<route>`` 路由令牌 (不改源)。

    实证根因 (task t_c9249919e8d7a13f, 2026-09-18): tectonic bundle 钉
    biblatex 3.17 (bcf 3.8) 但外部 biber 走系统 PATH (2.22 要 bcf 3.11)
    ——bundle 内无解；路由令牌由 repair 跨引擎臂换 xelatex (本地
    TeXLive biber/biblatex 成对)。签名复核两级: 本轮 ``err_head`` 快径
    → ``_fixloop_log`` 全文兜底 (外部工具 stdout dump 在 log 内位置
    不钉死——taxonomy head 窗未必盖到, 落 ``other`` 时同规接住)。
    不中 → False 让位后续 ``other`` 规则。
    """
    del eng, payload
    route = str(params.get("route") or "xelatex")
    m = _BIBER_SKEW_RE.search(ctx.err_head or "")
    if m is None:
        m = _BIBER_SKEW_RE.search(_fixloop_log(ctx))
    if m is None:
        return False, "no biber/biblatex skew signature"
    return True, (
        f"REJECT: route={route} biber/biblatex version skew "
        f"(bcf {m.group(1)} vs tool wants {m.group(2)})"
    )


def cite_in_math_mbox(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""数学域内裸 cite 族调用 → ``\mbox{\cite[..]{k}}`` 包裹 (kernel, 无 amsmath 依赖)。

    实证根因 (lane-citemath EVIDENCE, gr-qc/9901082): natbib ``\@citex``
    未定义引用标记 ``{\reset@font\bfseries ?}`` 不带盒子, 数学域内展开
    撞 ``\not@math@alphabet`` → ``Command \bfseries invalid in math mode``
    硬错; halt_on_error 在 thebibliography 之前死掉 → ``\bibcite`` 永不
    落 .aux → 错误自续。``\mbox`` 把标记带回文本域即断链。走查面 =
    ``latex209.wrap_math_cites`` (209 修复臂 cite 侧的独立出口, 同
    ``_MATH_CITE_CS_209`` 17 命令清单)。同签名可由字面 ``{\bfseries X}``
    触发——无 cite token 时本变换 0 改写自然 decline, 不误伤。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = wrap_math_cites(t)
        if n:
            ctx.write(f, nt)
            changed.append(f"{f.name}({n})")
    if not changed:
        return False, "no bare cite-family calls in math regions"
    return True, f"wrap cite-in-math in \\mbox: {', '.join(changed)}"
