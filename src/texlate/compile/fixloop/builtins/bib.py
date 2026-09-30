r"""builtins.bib — .bbl/.bib 族修复原语 (C3 拆分)。

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

from texlate.compile.fixloop.builtins.common import (
    _fixloop_log,
    _live_matches,
    _splice,
)

#: 同 normalize._AUTOBIB_DISARM —— revtex 系 ``\bibliography`` 顺带解除
#: end-doc ``\auto@bib`` 探测；裸 ``\input`` 改写必须补回，否则
#: ``\test@bbl@sw`` 在 vbox 排印 cite key 必需组（_/&/$ → in-math 级联 +
#: 三读重复书目）。``\ifcsname`` 守卫使非 revtex 工程零操作。
#: csname 形零字面 ``@`` —— ``\bibliography`` 站可落在已 tokenize 的
#: def 体内 (2105.11398 ``\newcommand{\showbib}`` 实证：旧
#: ``\makeatletter\@ifundefined`` 形在 @=12 预读体里成 ``\@``+裸字母
#: → ``\showbib`` 调用点 vmode spacefactor 炸), csname 任意 catcode 同读。
#: 名扫段内每个 ``@`` 都写 ``\string@``: doc 激活 @ (``\MakeShortVerb{\@}``
#: → @=13) 时裸 @ token 在 \ifcsname/\csname 名扫里被当 active cs 展开
#: → Missing \endcsname (1107.0063 实证); \string 取记号产 catcode-12
#: 字面 @ 字符，@=11/12/13 三态同名同读。
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
    return (changed > 0), f"\\bibliography -> \\input{{{target}}} in {changed} files"


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


#: ``.bcf`` 完整性门 —— 尾标 ``</bcf:controlfile>`` 缺席即截断件
#: (kill 撞档残留，1706.00240 实证：biber 对 truncated .bcf 会自删
#: 在席好 .bbl——截断 .bcf 下宁缺不跑)。
_BCF_TAIL_RX = re.compile(rb"</bcf:controlfile\s*>")
_BCF_TAIL_BYTES = 8192
_BCF_MIN_BYTES = 200


def _bcf_intact(bcf: Path) -> bool:
    """``.bcf`` 完整性判：尺寸下限 + 尾窗 ``</bcf:controlfile>`` 尾标。"""
    try:
        data = bcf.read_bytes()
    except OSError:
        return False
    if len(data) < _BCF_MIN_BYTES:
        return False
    return _BCF_TAIL_RX.search(data[-_BCF_TAIL_BYTES:]) is not None


def bbl_regen(  # noqa: C901, PLR0912, PLR0915 -- 隔离扫 + 逐 bcf 顺序闸；臂间状态互锁难拆
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

    qc-impl 扩展 (fp bbl_regen_ext + bbl_backup, 2026-09-28):

    - **前置隔离扫**: 循环前全树 ``*.bbl`` 头标扫描, fmt<3.0 一律改名
      ``<name>.bbl.fixloop-stale`` (保留 forensic, 不靠 .bcf 门——无
      .bcf 稿同样收; ``citekey_sanitize`` 等后续 bbl 消费臂不读改名件)。
      3.1/3.2 档**不**进此扫——``bbl_format_version_rewrite`` 是其正解
      (无 .bib 格再生无路, 隔离即掐灭唯一挽手)。
    - **.bcf 完整性门**: 尾标缺席/尺寸不足 → 跳过 biber 不碰在席 bbl
      (截断 .bcf 跑 biber = 自毁臂)。
    - **备份臂**: biber 前 fmt≥3.0 的在席 .bbl 快照 ``.fixloop-bak``;
      biber 失手且 bbl 消失 → 回滚, fmt<3.0 不备份 (poison 不回滚)。
    """
    del eng, payload, params
    # —— 前置：全树陈旧 bbl 隔离 (与 .bcf 有无无关) ——
    quarantined: list[str] = []
    for bbl in sorted(ctx.wdir.rglob("*.bbl")):
        if bbl.name.endswith(".fixloop-stale") or not bbl.is_file():
            continue
        ver = _bbl_format_version(bbl)
        if ver is not None and ver < (3, 0):
            try:
                bbl.rename(bbl.with_name(bbl.name + ".fixloop-stale"))
            except OSError:
                continue
            ctx.invalidate(bbl)
            quarantined.append(f"{bbl.name}(fmt {ver[0]}.{ver[1]})")
    bcfs = sorted(ctx.wdir.rglob("*.bcf"))
    if not bcfs:
        if quarantined:
            ctx.needs_pass = True
            return True, f"quarantined stale bbl: {', '.join(quarantined)}"
        return False, "no .bcf in project"
    done: list[str] = []
    dropped: list[str] = []
    failed: list[str] = []
    restored: list[str] = []
    for bcf in bcfs:
        stem = str(bcf.relative_to(ctx.wdir).with_suffix(""))
        bbl = bcf.with_suffix(".bbl")
        had_bbl = bbl.exists()
        bbl_ver = _bbl_format_version(bbl) if had_bbl else None
        if not _bcf_intact(bcf):
            failed.append(f"{bcf.name} truncated-bcf")
            continue
        backup: Path | None = None
        if had_bbl and bbl_ver is not None and bbl_ver >= (3, 0):
            backup = bbl.with_name(bbl.name + ".fixloop-bak")
            try:
                backup.write_bytes(bbl.read_bytes())
            except OSError:
                backup = None
        rc, _out, to = ctx.run_tool(["biber", stem], 60)
        if rc == 0 and not to:
            done.append(bcf.name)
            ctx.invalidate(bbl)
            if backup is not None:
                backup.unlink(missing_ok=True)
            continue
        if had_bbl and not bbl.exists():
            if backup is not None:
                # biber 自删了本可用的 bbl → 回滚 (非清场：fmt≥3.0 非 poison)
                try:
                    backup.rename(bbl)
                    ctx.invalidate(bbl)
                    restored.append(bbl.name)
                    continue
                except OSError:
                    pass
            # biber 自删 poison (陈旧格式拒载清场) —— 真实盘变，计 progress
            ctx.invalidate(bbl)
            dropped.append(f"{bbl.name}(biber-rm)")
        else:
            if backup is not None:
                backup.unlink(missing_ok=True)  # bbl 未被删 → 备份无用
            failed.append(f"{bcf.name} rc={rc}{'/timeout' if to else ''}")
    if quarantined:
        dropped.append(f"quarantined: {', '.join(quarantined)}")
    if not done and not dropped and not restored:
        return False, f"biber regen failed: {'; '.join(failed)}"
    parts: list[str] = []
    if done:
        parts.append(f"regen: {', '.join(done)}")
        ctx.needs_pass = True  # 新 bbl 由续趟吸收——解析趟请求
    if dropped:
        parts.append(f"stale-dropped: {', '.join(dropped)}")
    if restored:
        parts.append(f"restored: {', '.join(restored)}")
    if failed:
        parts.append(f"failed: {'; '.join(failed)}")
    return True, "; ".join(parts)


#: log 签名 ``... expected version X.Y`` —— 期望档提取 (biblatex 逐档
#: 硬校验，期望版本以 log 宣判为准; 无签名兜底当前 TL 3.3)。
_BBL_EXPECTED_RE = re.compile(r"expected (?:version )?(\d+)\.(\d+)")


def bbl_format_version_rewrite(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""无 .bib 可再生的 fmt 3.x 旧 .bbl → 头标版本号改写到 biblatex 期望档。

    实证面 (qc unfixable_bbl_ver 桶, 2 格): 2208.00058 (51 键)/2208.00174
    捆绑 fmt 3.1/3.2 .bbl 撞 TL biblatex "expected 3.3" 拒载 → thebibliography
    全文以 ``\\sortlist``/``\\entry`` 裸排 verbatim 倾倒 (vis_bbl_dump);
    工程内无 .bib → biber 再生无路。修 = 头标 ``bbl format version`` 改
    期望档 + preamble 兜 ``\\sortlist`` 等 bbl 内部 cs 的 provide-shim
    (3.x 族间 cs 面微差, 期望档覆盖后 biblatex 自供定义, shim 只在残缺
    时兜底, ``\\providecommand`` 不覆写已有定义)。

    门: fmt∈[3.0,期望) 且**全树无 .bib** (有 bib 走 ``bbl_regen`` 再生
    正解); log 有 ``wrong format version`` 签名, 或虽无签名但 fmt<期望
    (biblatex 逐档硬校验, 3.1/3.2 在 3.21 下同病)。fmt<3.0 结构与 3.x
    异构, 不改写——由 ``bbl_regen`` 隔离臂收。
    """
    del eng, payload, params
    if any(ctx.wdir.rglob("*.bib")):
        return False, ".bib present — biber regen is the correct path"
    log = _fixloop_log(ctx)
    exp = (3, 3)
    m_exp = _BBL_EXPECTED_RE.search(log)
    if m_exp is not None:
        exp = (int(m_exp.group(1)), int(m_exp.group(2)))
    rewritten: list[str] = []
    for bbl in sorted(ctx.wdir.rglob("*.bbl")):
        if bbl.name.endswith((".fixloop-stale", ".fixloop-bak")):
            continue
        ver = _bbl_format_version(bbl)
        if ver is None or not (3, 0) <= ver < exp:
            continue
        try:
            data = bbl.read_bytes()
        except OSError:
            continue
        # 头标整段替换到期望档——``bbl format version 3.1`` → ``3.3``
        new = _BBL_VER_RE.sub(
            rf"bbl format version {exp[0]}.{exp[1]}".encode(), data, count=1
        )
        if new == data:
            continue
        bbl.write_bytes(new)
        ctx.invalidate(bbl)
        rewritten.append(f"{bbl.name}({ver[0]}.{ver[1]}→{exp[0]}.{exp[1]})")
    if not rewritten:
        return False, "no 3.x stale-format .bbl without .bib"
    ctx.needs_pass = True  # 改写 bbl 由续趟重读——解析趟请求
    return True, f"bbl header rewritten to {exp[0]}.{exp[1]}: {', '.join(rewritten)}"


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
    TeXLive biber/biblatex 成对)。签名复核两级：本轮 ``err_head`` 快径
    → ``_fixloop_log`` 全文兜底 (外部工具 stdout dump 在 log 内位置
    不钉死——taxonomy head 窗未必盖到，落 ``other`` 时同规接住)。
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

    实证根因 (citemath 车道实证, gr-qc/9901082): natbib ``\@citex``
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


#: tectonic 内嵌 bibtex 挂死尾锚——``note: Running BibTeX on`` 是 kill 前
#: 末位管线 note 即死在 bibtex 内部 (t_0c9a/t_dce88 实证：tex pass 出
#: xdv 后 bibtex 无输出烧满 240s 墙钟; 系统 bibtex 同 .aux 秒过——
#: tectonic 0.15 Rust bibtex 特定输入死循环，timeout 类死因)。
_BIBTEX_STALL_TAIL_RE = re.compile(r"note: Running BibTeX on [^\n]+\s*$")

#: bbl 在席而 .bib 缺席的 biber 硬毙签名——tectonic 管线无 ``.bbl 在席
#: 跳过`` 分支，aux 有 citation 即跑 biber (t_a4ae 实证：src 只发
#: main.bbl 未发 references.bib, ``! can't open path`` 落 other 硬毙;
#: xelatex ``_bib_pass`` 同态 bbl 在席整臂跳过)。
_BIB_CANT_OPEN_RE = re.compile(r"can't open path [`']([^`']+\.bib)")


def tectonic_bib_stall_route(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """Tectonic bib 管线死面 → ``REJECT: route=<route>`` 路由令牌 (不改源)。

    两臂复核 (``err_head`` 快径 → ``_fixloop_log`` 全文兜底，同
    ``biber_biblatex_skew_route`` 两级序):

    - **bibtex 挂死**: 末位管线 note = ``Running BibTeX on`` 即死在
      bibtex 内部 (judge 落 timeout); xelatex 工具链走系统 bibtex 无此
      病种。
    - **bbl 在席缺 .bib**: ``can't open path '<name>.bib'`` 且 wdir 有
      ``*.bbl`` → tectonic 不看 bbl 在席强跑 biber 硬毙; xelatex
      ``_bib_pass`` 文件态触发、bbl 在席跳过 bib 趟。

    不中 → False 让位后续规则; 只发令牌不改源 (repair 跨引擎臂换编)。
    """
    del eng, payload
    route = str(params.get("route") or "xelatex")
    head = ctx.err_head or ""
    log = _fixloop_log(ctx)
    tail = log[-4096:]
    if _BIBTEX_STALL_TAIL_RE.search(tail) or _BIBTEX_STALL_TAIL_RE.search(head):
        return (
            True,
            f"REJECT: route={route} tectonic bibtex stall (killed inside bibtex)",
        )
    m = _BIB_CANT_OPEN_RE.search(head) or _BIB_CANT_OPEN_RE.search(log)
    if m is not None and any(ctx.wdir.rglob("*.bbl")):
        return True, (
            f"REJECT: route={route} missing {m.group(1)} but bundled .bbl present"
        )
    return False, "no tectonic bib-stall signature"
