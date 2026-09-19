"""actions —— fixloop 动作解释器簇 (C2 自 engine.py 拆出).

``when``/``condition`` 评估 + 7 种 ``action.kind`` 分派 + 依赖闭包安装
+ ``_match_apply`` 规则匹配 (spike pick_and_apply)。类型面 ``LoopCtx``/
``Engine``/``Rule``/``Ruleset``/``ErrReport`` 一律 TYPE_CHECKING 反引
断运行时环; ``_REJECT_PREFIX`` (reject_route 产出、主循环判读) 与
``_probe`` (``probe_file`` cwd 兼容调用, 消费点全在本簇) 移驻本叶,
``engine`` 门面回引保 ``engine.X`` import 面不变。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import regex

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.ruleset import _WHEN_ITEM_KEYS
from texlate.texlog import is_project_file
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from texlate.compile.fixloop.engine import Engine, LoopCtx
    from texlate.compile.fixloop.logparse import ErrReport
    from texlate.compile.fixloop.ruleset import Rule, Ruleset

_REJECT_PREFIX = "REJECT:"


def _probe(eng: Engine, fname: str, cwd: Path | None = None) -> str | None:
    """``probe_file`` 兼容调用: 支持可选 ``cwd`` kwarg 的 impl 直传; 裸 Protocol 实现退无参。"""
    if cwd is not None:
        try:
            return eng.probe_file(fname, cwd=cwd)
        except TypeError:
            pass  # 裸签名实现 → 退回 fname-only
    return eng.probe_file(fname)


# ════════════════════════════════════════════════════════════════
# when / condition 评估
# ════════════════════════════════════════════════════════════════


def _substitute(v: Any, payload: str | None) -> Any:  # noqa: ANN401  # yaml 值天然 Any
    """Params 值里的 ``{payload}`` 占位替换。"""
    if isinstance(v, str):
        return v.replace("{payload}", payload or "")
    if isinstance(v, dict):
        return {k: _substitute(x, payload) for k, x in v.items()}
    if isinstance(v, list):
        return [_substitute(x, payload) for x in v]
    return v


def _when_ok(
    when: dict[str, Any], cat: str | None, pay: str | None, ctx: LoopCtx
) -> bool:
    """When 匹配: ``always`` / ``any:[...]`` / 单条 category 条件。

    无可识别键的候选 fail-closed (与 _cond_ok 未知键对称)——``categry:``
    型 typo 旧行为是对全 category 点火; load 期另有 _when_problems 白名单。
    """
    if not when:
        return False
    if when.get("always"):
        return True
    cands: list[dict[str, Any]] = when.get("any") or [when]
    for c in cands:
        if not isinstance(c, dict) or not (_WHEN_ITEM_KEYS & c.keys()):
            continue
        if c.get("category") is not None and c["category"] != cat:
            continue
        if c.get("payload_required") and not pay:
            continue
        mhc = c.get("main_head_contains")
        if mhc is not None and mhc not in ctx.main_head():
            continue
        return True
    return False


def _package_version(eng: Engine, fname: str) -> int | None:
    """Probe 到的包文件 ``vX.Y`` 主版本号 (package_version_ge 条件用)。"""
    found = eng.probe_file(fname)
    if not found:
        return None
    try:
        text = Path(found).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    m = re.search(
        r"\\Provides(?:Expl)?(?:Package|Class)\s*\{[^}]*\}[^v\n]*v?(\d+)", text
    )
    return int(m.group(1)) if m else None


def _err_site_outside(ctx: LoopCtx, rep: ErrReport | None) -> bool:
    """``err_outside_fileset`` 条件实现: 报错文件栈内层帧判工程外。

    ``rep.file_stack[-1]`` = TeX ``l.N`` 报错所在文件 (内层帧); runaway
    空栈回退 ``popped_files[-1]`` (最近关闭帧肇事口径, 与
    ``_requester_paths`` 同)。``is_project_file`` 与红线归因同口径——
    相对帧/``root`` 内 = 工程 (fileset 可 patch), texmf/bundle 帧 =
    工程外 (fileset 够不到, 仅 wdir 无关 arm 可治)。无栈帧证据
    (``rep=None`` 的直驱/旧调用面) → False (fail-closed)。
    """
    if rep is None:
        return False
    site = rep.file_stack[-1] if rep.file_stack else None
    if site is None and rep.popped_files:
        site = rep.popped_files[-1]
    return site is not None and not is_project_file(site, ctx.wdir)


def _cond_ok(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0917  # 条件原语分派表, 每键一处
    cond: dict[str, Any],
    rule: Rule,
    ctx: LoopCtx,
    eng: Engine,
    pay: str | None,
    rep: ErrReport | None = None,
) -> tuple[bool, str]:
    """Condition 全部键 AND; ``any`` 子键 OR。未知键 fail-closed。

    ``rep`` 仅 ``err_outside_fileset`` 消费 (报错文件栈判站点归属);
    缺省 ``None`` 时该键 fail-closed, 其余键语义不变。
    """
    for key, val in cond.items():
        v = _substitute(val, pay)
        if key == "any":
            subs = v if isinstance(v, list) else []
            ok = any(
                _cond_ok(sub, rule, ctx, eng, pay, rep)[0]
                for sub in subs
                if isinstance(sub, dict)
            )
            if not ok:
                return False, "any 子条件全不中"
        elif key == "tool_available":
            if not shutil.which(str(v)):
                return False, f"tool {v} unavailable"
        elif key == "cap_available":
            if str(v) not in getattr(eng, "caps", set()):
                return False, f"cap {v} missing"
        elif key == "engine_in":
            if ctx.engine_name not in v:
                return False, f"engine {ctx.engine_name} not in {v}"
        elif key == "main_head_contains":
            if str(v) not in ctx.main_head():
                return False, "main head 无该子串"
        elif key == "source_contains":
            if not regex.search(str(v), ctx.source_blob()):
                return False, "源码无该 pattern"
        elif key == "ctx_suggests":
            if not regex.search(str(v), ctx.err_head or ""):
                return False, "err ctx 无提示"
        elif key == "fileset":
            has = v.get("has_ext") or []
            lacks = v.get("lacks_ext") or []
            names = {p.suffix for p in ctx.wdir.rglob("*") if p.is_file()}
            if any(e not in names for e in has) or any(e in names for e in lacks):
                return False, "fileset 不满足"
        elif key == "cache_dir_glob":
            if not any(ctx.wdir.glob(str(v))):
                return False, f"无 {v} 匹配"
        elif key == "vendored_shadow":
            if not builtins.find_vendored_shadows(ctx, eng, (".sty", ".cls")):
                return False, "无遮蔽候选"
        elif key == "package_version_ge":
            got = _package_version(eng, str(v.get("file", "")))
            if got is None or got < int(v.get("version", 0)):
                return False, f"{v.get('file')} 版本 {got} < {v.get('version')}"
        elif key == "prim_read_form":
            prim = re.escape(str(v))
            if not re.search(rf"\\if[a-zA-Z@]*\s*\\{prim}\b", ctx.source_blob()):
                return False, f"无 \\if*\\{v} 读取语境"
        elif key == "err_outside_fileset":
            if not _err_site_outside(ctx, rep):
                return False, "报错站点可归工程 fileset"
        elif key == "shim_known":
            shim_map = ((rule.action.get("params") or {}).get("shim_map")) or {}
            if not builtins.shim_pkgs_in_use(ctx, shim_map):
                return False, "工程未用 shim_map 内包"
        else:
            return False, f"unknown condition {key!r}"
    return True, ""


# ════════════════════════════════════════════════════════════════
# 动作分派 —— 7 种 action.kind (docs/08:260)
# ════════════════════════════════════════════════════════════════


#: 单次 ``pat.sub`` 硬顶（秒）——病态回溯超此即弃守该条替换。
_SUB_TIMEOUT_S = 20.0


def _bounded_sub(
    pat: regex.Pattern[str],
    repl: str | Callable[[regex.Match[str]], str],
    text: str,
    *,
    timeout_s: float = _SUB_TIMEOUT_S,
) -> str | None:
    """``pat.sub`` 时限包裹：超时 ``TimeoutError`` 归一成 ``None``。

    ``regex`` 引擎在匹配环内查 deadline——超时真中断、无残留线程。
    旧 stdlib ``re`` + daemon-thread 弃守形实证失效：泄漏 spinner 在
    C 层回溯不放 GIL，整进程冻结（guardsmoke fixloop 格 Thread-4
    utime 29min、worker 全 GIL 饿死、子进程僵死不收，2026-09-18）。
    ``regex`` 还自带部分病态形免疫（``(x+x+)``/``([a-zA-Z]+)*`` 线性过）。
    """
    try:
        return pat.sub(repl, text, timeout=timeout_s)
    except TimeoutError:
        return None


def _masked_sub(
    pat: regex.Pattern[str],
    repl: str | Callable[[regex.Match[str]], str],
    text: str,
    *,
    timeout_s: float = _SUB_TIMEOUT_S,
) -> str | None:
    r"""``match_surface: masked`` 替换——等长遮盖面匹配 + span 回切原文。

    在 ``mask_tex`` 等长视图上 finditer, 命中 span 右→左拼回原文
    (replacement 变长不漂后续 offset)。注释/逐字/失活区在视图中是等长
    空白——pattern 的必要内容无法锚在其中 (natbib_numbers_pass 注释行
    ``\\begin{document}`` 裂伤类的根修); repl 展开读视图 group——命中区
    全在活面时与原文逐字节一致, 跨遮盖区的野 span 按原文 span 替换
    (作者自担 pattern 形状)。超时归一 ``None``, 与 ``_bounded_sub`` 同约。
    """
    try:
        matches = list(pat.finditer(mask_tex(text), timeout=timeout_s))
        for m in reversed(matches):
            piece = repl(m) if callable(repl) else m.expand(repl)
            text = text[: m.start()] + piece + text[m.end() :]
    except TimeoutError:
        return None
    else:
        return text


def _patch_files(
    ctx: LoopCtx,
    exts: Iterable[str],
    subs: list[tuple[regex.Pattern[str], Any, bool]],
    rule_id: str = "",
) -> int:
    """对全部匹配文件做 ``pattern→repl|function`` 替换; 返回改动文件数 (spike L245-261)。"""
    n = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for pat, repl, masked in subs:
            nxt = _masked_sub(pat, repl, nt) if masked else _bounded_sub(pat, repl, nt)
            if nxt is None:
                ctx.events.append(
                    f"rewrite_timeout {rule_id}: {pat.pattern[:80]!r} on {f}"
                )
                continue
            nt = nxt
        if nt != t:
            ctx.write(f, nt)
            n += 1
    return n


def _compile_rewrites(
    rewrites: list[dict[str, Any]],
) -> list[tuple[regex.Pattern[str], Any, bool]]:
    """Rewrite 条目 → ``(pattern, repl|fn, masked)`` 三元组。

    ``match_surface: masked`` 是逐条 opt-in——缺席/其他值走原文 ``sub``,
    既有规则零行为差 (ruleset 装载侧已把非法值拦成 RulesetError)。
    """
    subs = []
    for rw in rewrites:
        flags = 0
        for fl in rw.get("flags") or []:
            flags |= getattr(regex, fl, getattr(re, fl, 0))
        pat = regex.compile(rw["pattern"], flags)
        masked = rw.get("match_surface") == "masked"
        if "function" in rw:
            subs.append((pat, builtins.REWRITE_FNS[rw["function"]], masked))
        else:
            subs.append((pat, rw.get("repl", ""), masked))
    return subs


def _scan_names(code: str, sp: dict[str, Any]) -> Iterator[str]:
    r"""单行 (已切注释) 按 scan_pattern 抽文件名——构造名/截断头滤除。

    ``\input sv\CurrentOption.clo`` 裸名被 ``\`` 截成 ``sv`` 残头、
    ``\InputIfFileExists{aip-\X.tex}`` 花括号内构造名——都不可探测,
    放行即产 ``sv.tex``/``aip-.tex`` 噪音安装 (svjour/aipcheck 实证)。
    """
    for m in regex.finditer(sp["regex"], code):
        if m.end() < len(code) and code[m.end()] == "\\" and code[m.end() - 1] != "}":
            continue  # 匹配被 \ 截断——残头非实名
        names = [m.group(1)]
        if sp.get("split"):
            names = m.group(1).split(sp["split"])
        for nm in names:
            name = nm.strip()
            if name and "\\" not in name:
                yield name


def _apply_scan_install(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""静态扫 ``\usepackage``/``\documentclass`` → 探测缺失 → 批量装 (spike L594-618)。"""
    need: set[str] = set()
    noise = (
        regex.compile(params["noise_filter"]) if params.get("noise_filter") else None
    )
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None:
            continue
        for sp in params.get("scan_patterns") or []:
            # 逐行切注释后扫——``% \input foo`` 注释行不该触发安装
            # (pst-notreal 实证; ``\%`` 转义不算注释起点)
            for line in t.splitlines():
                code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
                for name in _scan_names(code, sp):
                    # suffix 仅补给无扩展名 (``\input epsf`` → epsf.tex);
                    # 已带扩展名者 (``\input{x.tex}``) 照旧不叠。
                    fname = name if Path(name).suffix else name + sp.get("suffix", "")
                    if noise and not noise.match(name):
                        continue
                    need.add(fname)
    missing = sorted(f for f in need if not _probe(eng, f, cwd=ctx.wdir))
    installed = [f for f in missing if eng.install_file(f)]
    ctx.installed.extend(installed)
    note = f"missing files={missing} -> installed {installed}"
    if params.get("vendored"):
        vendored = _scan_vendored(ctx, eng, params, missing, set(installed))
        if vendored:
            note += f" vendored {vendored}"
    return True, note


def _scan_vendored(
    ctx: LoopCtx,
    eng: Engine,
    params: dict[str, Any],
    missing: list[str],
    got: set[str],
) -> list[str]:
    r"""Install 全链败件 → repo vendored 兜底平铺 + 落点依赖闭包预装。

    ``builtins.vendored_fetch`` 同款语义 (basename 查件 / ``..``-绝对-NUL
    守卫 / payload 相对径落位)——预检在 round-0 落件, 不依赖 first-error
    序位 (hep-ph/0104121: ``fixes.sty:41`` 的 undefined_cs 抢在
    ``missing_file`` 前, 轮级分类永远看不到 vendored 可救的缺件)。
    落件喂 ``_dep_fanout``: 真件 ``\RequirePackage`` 依赖同轮预装
    (aastex62→revtex4-1 类二阶缺件前置, 免穿透轮)。
    """
    root = builtins._vendor_root(params)  # noqa: SLF001 - vendored 查件单源
    dropped: list[Path] = []
    out: list[str] = []
    for fname in missing:
        if fname in got:
            continue
        rel = PurePosixPath(fname)
        if rel.is_absolute() or ".." in rel.parts or "\x00" in fname:
            continue
        src = builtins._vendored_source(root, fname)  # noqa: SLF001 - 同上
        if src is None:
            continue
        dst = ctx.wdir / Path(*rel.parts)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except OSError:
            continue
        out.append(fname)
        ctx.installed.append(fname)
        dropped.append(dst)
    if dropped:
        _dep_fanout(ctx, eng, dropped, set(ctx.installed), depth=2)
    return out


def _filemap_candidates(eng: Engine, fname: str) -> list[str]:
    """``filemap`` 查询 + tectonic 侧 tlpdb 索引兜底 (CtanFetcher.peek_index)。"""
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname) or idx.suggest(fname.rsplit(".", 1)[0])
    return pkgs


#: 包文件行首依赖声明 —— 注释掉的 ``% \RequirePackage`` 不命中。
#: ``textutil.LOADER_CMDS`` 真子集: ``PassOptionsToPackage``/``PassOptionsToClass``
#: 首 ``{}`` 实参是选项表, group(1) 抓错名会产噪音安装件; ``LoadClassWithOptions``
#: 首参虽为类名可收但原面不含 (差异留档非漏收)。
_DEP_DECL_RE = re.compile(
    r"^[ \t]*\\(?:RequirePackage|RequirePackageWithOptions|LoadClass|usepackage)"
    r"\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)

#: ``\input stem``/``\input{stem}`` 裸名依赖——行内允许 (pst-* generic 实证:
#: pstricks-add.tex l.27-32 ``\ifx\PSTnodesLoaded\endinput\else \input pst-node \fi``
#: 顺序链, 条件不管照装——probe/install 门控天然无害)。花括号形吃 ``\s*``
#: (``\input{x}`` 零空白是 LaTeX 主导形态; arxiv/locate.py:53 同口径),
#: 裸名仍要求 ``\s+``——否则 ``\inputfoo``/``\inputlineno`` 被前缀误吃成
#: ``foo``/``lineno`` 伪依赖 (lineno.sty 真实存在, 会真装)。
_DEP_INPUT_RE = re.compile(r"\\input(?:\s*\{([^}\n]*)\}|\s+([^\s{}%\\]+))")

#: 行内注释切尾 —— ``\%`` 转义不算注释起点。
_COMMENT_CUT_RE = re.compile(r"(?<!\\)%")


def _dep_stems(path: Path) -> list[str]:
    r"""包文件依赖名表: 行首 ``\\RequirePackage``/``\\LoadClass`` + 行内 ``\\input``。"""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    stems = [
        stem
        for m in _DEP_DECL_RE.finditer(text)
        for stem in (s.strip() for s in m.group(1).split(","))
        if stem
    ]
    for line in text.splitlines():
        code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
        for m in _DEP_INPUT_RE.finditer(code):
            g = m.group(1) or m.group(2)
            if not g or "\\" in g:
                continue  # 构造文件名 (aip-\CurrentOption.tex) 不可探测
            if m.group(2) is not None and m.end() < len(code) and code[m.end()] == "\\":
                continue  # 裸名被 \ 截断 (sv\CurrentOption.clo → 'sv' 残头)
            stems.append(g)
    return stems


def _try_install_dep(ctx: LoopCtx, eng: Engine, stem: str) -> Path | None:
    """单依赖名探测/补装 → 已解析路径 (供闭包续层)。"""
    cands = (
        [stem] if Path(stem).suffix else [f"{stem}.sty", f"{stem}.cls", f"{stem}.tex"]
    )
    for cand in cands:
        if r := _probe(eng, cand, cwd=ctx.wdir):
            return Path(r)
        if eng.install_file(cand):
            ctx.installed.append(cand)
            if r := _probe(eng, cand, cwd=ctx.wdir):
                return Path(r)
            return None
    return None


def _dep_fanout(
    ctx: LoopCtx, eng: Engine, seeds: Iterable[Path], seen: set[str], *, depth: int
) -> None:
    """``seeds`` 各文件依赖声明 BFS 补装 (就地改 ``ctx.installed``/``seen``)。"""
    frontier = list(seeds)
    for _ in range(depth):
        nxt: list[Path] = []
        for p in frontier:
            for stem in _dep_stems(p):
                if stem in seen:
                    continue
                seen.add(stem)
                if r := _try_install_dep(ctx, eng, stem):
                    nxt.append(r)
        if not nxt:
            return
        frontier = nxt


def _install_dep_closure(
    ctx: LoopCtx, eng: Engine, fname: str, path: str | None, *, depth: int = 2
) -> None:
    r"""包装文件的依赖闭包补装: 行首 ``\RequirePackage``/``\LoadClass`` 逐层探测+装。

    2410.00012 实证: 装 mhchem 不装 chemgreek (包内 ``\RequirePackage`` 依赖),
    texmf 遮蔽下依赖缺席 → log 尾 Emergency stop。``depth`` 界住链长。
    """
    if path is None:
        return
    _dep_fanout(ctx, eng, [Path(path)], set(ctx.installed) | {fname}, depth=depth)


#: ``-file-line-error`` 锚里的要求方文件 token (``./pst-all.sty:25:``)
_REQ_ANCHOR_RE = re.compile(r"([^\s(){}]+?\.(?:sty|cls|def|clo|tex)):\d+:")


def _requester_paths(ctx: LoopCtx, eng: Engine, rep: ErrReport) -> list[Path]:
    r"""missing_file 报错的要求方文件 (``\\RequirePackage`` 宿主) 逐个解析。

    pst-all 实证 (delta b4akkgal5): meta-wrapper 连发 11 个成员包, 缺谁报谁、
    file:line 锚是要求方自身 —— 一轮补一个要等 8+ 轮 max_rounds; 直接扫
    要求方依赖全表一轮补齐。锚序: 首错行 > ctx > tail 末位 > file_stack
    内层包文件兜底 (无 ``file:line`` 的老式 ``!`` 错误) > popped_files
    尾段 (runaway 把肇事帧先弹走——``\@iiiparbox``/``\next`` 扫描族)。
    """
    names = _REQ_ANCHOR_RE.findall(rep.first or "")
    names += _REQ_ANCHOR_RE.findall(rep.ctx or "")
    names += _REQ_ANCHOR_RE.findall(rep.tail)[::-1]
    stack = [s for s in rep.file_stack[-2:] if s.endswith((".sty", ".cls", ".def"))]
    if not stack:
        # runaway 错报位在最近关闭帧（``popped_files[-1]`` 肇事候选，
        # #78/\@iiiparbox×3/\next 扫描实证）——栈取不到时 popped 尾段递补
        stack = [
            s
            for s in reversed(rep.popped_files)
            if s.endswith((".sty", ".cls", ".def"))
        ]
    names += stack
    out: list[Path] = []
    seen: set[str] = set()
    for name in names:
        base = Path(name).name
        if base in seen:
            continue
        seen.add(base)
        p = Path(name)
        if not p.is_absolute():
            p = ctx.wdir / p
        if not p.exists():
            hit = _probe(eng, base, cwd=ctx.wdir)
            if hit is None:
                continue
            p = Path(hit)
        if p not in out:
            out.append(p)
    return out


def _apply_install_file(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any], rep: ErrReport
) -> tuple[bool, str]:
    """缺文件 → probe → install_file → 复核; font_related → rebuild_fontmaps (spike L264-276)。"""
    fanout_seeds = _requester_paths(ctx, eng, rep)
    if fanout_seeds:
        before = len(ctx.installed)
        _dep_fanout(ctx, eng, fanout_seeds, set(ctx.installed), depth=2)
        fanout_note = f" (+{len(ctx.installed) - before} requester deps)"
    else:
        fanout_note = ""
    font_exts = tuple(params.get("font_related_exts") or ())
    # file_aliases: 查询名≠实档名桥 —— babel ini 按 \BabelDefinitionFile{0}{X}
    # 指名实档 (选项 ukrainian → ukraineb.ldf 型), try_exts 拼不出来的异形名
    # 走显式别名表先试 (序=别名先, 本名扩展后)。
    candidates = list((params.get("file_aliases") or {}).get(params["file"], []))
    if params.get("try_exts"):
        candidates += [params["file"] + e for e in params["try_exts"]]
    else:
        candidates.append(params["file"])
        if not Path(candidates[-1]).suffix:
            # `I can't find file `X'` 裸 payload (\input/openin 系报错) ——
            # TeX 语义实际找 X.tex; 裸名照试后补 .tex 变体 (epsf 实证:
            # filemap/shim_map 键全带扩展名, 裸名恒 miss)。
            candidates.append(params["file"] + ".tex")
    missed: list[str] = []
    for fname in candidates:
        font_related = bool(params.get("font_related")) or fname.endswith(font_exts)
        # probe 带 cwd=wdir: 工程内文件/ctan_fetch 平铺落盘均算命中
        # (tectonic probe_file 无 cwd 恒 None, 复核必败)
        if present := _probe(eng, fname, cwd=ctx.wdir):
            _install_dep_closure(ctx, eng, fname, present)
            if params.get("already_present_ok", True):
                return True, f"already-present {fname}{fanout_note}"
            continue
        if not eng.install_file(fname, font_related=font_related):
            pkgs = _filemap_candidates(eng, fname)
            hint = f" (candidates: {', '.join(pkgs)})" if pkgs else ""
            missed.append(f"no package provides {fname}{hint}")
            continue
        if not (installed := _probe(eng, fname, cwd=ctx.wdir)):
            ctx.advisories.append(f"installed but {fname} still not found")
            continue
        ctx.installed.append(fname)
        _install_dep_closure(ctx, eng, fname, installed)
        if font_related:
            eng.rebuild_fontmaps()
        return True, f"installed {fname}{fanout_note}"
    # 全候选失败才落 advisory——前候选 miss 后候选成 (裸名→.tex fallback)
    # 的常态路径不该污染归因统计 (scout-pst 实证噪音)
    ctx.advisories.extend(missed)
    return False, f"no candidate file installed for {params['file']}{fanout_note}"


def _apply(  # noqa: C901, PLR0911  # action.kind 分派表, 每种一处
    rule: Rule, ctx: LoopCtx, eng: Engine, pay: str | None, rep: ErrReport
) -> tuple[bool, str]:
    """按 action.kind 分派执行一条规则 → (applied, note)。"""
    action = rule.action
    kind = action.get("kind")
    params = _substitute(action.get("params") or {}, pay)
    if kind == "scan_install":
        return _apply_scan_install(ctx, eng, params)
    if kind == "install_file":
        return _apply_install_file(ctx, eng, params, rep)
    if kind == "run_tool":
        rc, out, to = ctx.run_tool(
            list(params.get("argv") or []), int(params.get("timeout", 120))
        )
        ctx.events.append(
            f"run {' '.join(params.get('argv') or [])} -> rc={rc}{' TIMEOUT' if to else ''}"
        )
        return True, f"rc={rc}{' TIMEOUT' if to else ''} {out[-200:].strip()}"
    if kind == "regex_rewrite":
        subs = _compile_rewrites(params.get("rewrites") or [])
        n = _patch_files(ctx, params.get("exts") or (".tex", ".sty"), subs, rule.id)
        if n > 0:  # 0 命中不落 engine_flags——空转规则不该给后续编译注 flag
            for fl in params.get("engine_flags") or []:
                if fl not in ctx.engine_flags:
                    ctx.engine_flags.append(fl)
        return (n > 0), f"rewrite in {n} files"
    if kind == "builtin_transform":
        fn = builtins.TRANSFORM_FNS[action["function"]]
        return fn(ctx, eng, pay, params)
    if kind == "reject_route":
        route = params.get("route", "")
        reason = params.get("reason", "")
        return True, f"{_REJECT_PREFIX} route={route} {reason}".strip()
    if kind == "escalate_llm":
        if ctx.llm_hook is None:
            return False, "no llm hook; stub (spike L523-527 parity)"
        return ctx.llm_hook(ctx, rep)
    return False, f"unknown action kind {kind!r}"


# ════════════════════════════════════════════════════════════════
# 规则匹配 (spike pick_and_apply L549-565 + mode/condition/fallback)
# ════════════════════════════════════════════════════════════════


def _match_apply(  # noqa: C901, PLR0912, PLR0913, PLR0917  # spike pick_and_apply 签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> tuple[Rule | None, str]:
    """Order 序找第一条 when+condition 过、mode 可行且应用成功的规则。

    ``unsupported`` + ``fallback: escalate_llm`` 不就地烧 LLM——记下首个
    待 escalate 规则继续扫描, 同 category 的廉价规则全耗尽后才调 hook
    (missing_pfb_updmap 原位评估会把后置的 font_sub_shim 饿死在 LLM 后面)。
    """
    pending_esc: tuple[Rule, str] | None = None
    for rule in rs.phase("loop"):
        key = f"{rule.id}:{pay}"
        if key in ctx.applied:
            continue
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.engine_name)
        mode = spec.get("mode", "native")
        if mode == "skip" or (mode == "degrade" and spec.get("degrade") == "skip"):
            continue
        if mode == "unsupported":
            if spec.get("fallback") == "escalate_llm" and pending_esc is None:
                pending_esc = (rule, key)
            ctx.advisories.append(f"{rule.id} unsupported on {ctx.engine_name}")
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay, rep)
        if not ok:
            ctx.events.append(f"rule {rule.id}: cond skip ({why})")
            d = f"{rule.id}: cond skip ({why})"
            if d not in ctx.declined:
                ctx.declined.append(d)
            continue
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001  # 规则崩溃=放弃该条, 试下一条 (spike L557-559)
            applied, note = False, f"rule crashed: {type(e).__name__}: {e}"
        if applied:
            ctx.applied.add(key)
            return rule, note
        if note:
            ctx.events.append(f"rule {rule.id}: skip ({note})")
            d = f"{rule.id}: {note}"
            if d not in ctx.declined:
                ctx.declined.append(d)
        fb = spec.get("fallback")
        if fb == "advisory":
            ctx.advisories.append(f"{rule.id}: {note}")
    if pending_esc is not None and ctx.llm_hook is not None:
        rule, key = pending_esc
        applied, note = ctx.llm_hook(ctx, rep)
        if applied:
            ctx.applied.add(key)
            return rule, f"escalated: {note}"
        if note:
            ctx.events.append(f"rule {rule.id}: escalate skip ({note})")
            d = f"{rule.id}: escalate skip ({note})"
            if d not in ctx.declined:
                ctx.declined.append(d)
    return None, ""
