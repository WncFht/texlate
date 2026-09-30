"""actions._actions_cond — when/condition 评估面 (C5 拆叶)。

``_when_ok`` 匹配 + ``_cond_ok`` 全键分派 + ``{payload}``/``{main_dir}``/
``{python}`` 占位 ``_substitute``, cond 树敏感面快照簇 (``_cond_snap``/
``_cond_snap_reset``/``_cond_files``/``_cond_blob``/``_cond_shadows``/
``_stem_sibling``), 与 ``_package_version``/``_err_site_outside``/
``_main_dir_rel`` 条件原语。类型面 ``LoopCtx``/``Engine``/``Rule``/
``ErrReport`` 一律 TYPE_CHECKING 反引断运行时环。
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import regex

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins.graphics import _PDF_SANITIZE_SKIP_DIRS
from texlate.compile.fixloop.ruleset import _WHEN_ITEM_KEYS
from texlate.texlog import is_project_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx
    from texlate.compile.fixloop.ruleset import Rule
    from texlate.compile.logparse import ErrReport


def _main_dir_rel(ctx: LoopCtx | None) -> str:
    """``{main_dir}`` 占位值: main_dir 相对 wdir 的 posix 径; 未知/逃逸 → ``.``。

    run_tool argv 内的落点占位——编译 cwd = main_dir (kpathsea 解析位),
    wdir 根对嵌套 main 不可见; ``main_rel`` 怪径致 main_dir 逃出 wdir
    时退 ``.`` (wdir 根) 与 _resolve_site DECLINE 口径一致。
    """
    mp = ctx.main_path() if ctx is not None else None
    if mp is None:
        return "."
    try:
        return mp.parent.resolve().relative_to(ctx.wdir.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return "."


def _substitute(
    v: Any,  # noqa: ANN401  # yaml 值天然 Any
    payload: str | None,
    ctx: LoopCtx | None = None,
) -> Any:  # noqa: ANN401  # 同上 (递归返回 yaml 值)
    """Params 值里的 ``{payload}``/``{main_dir}``/``{python}`` 占位替换。

    ``{python}`` → ``sys.executable``: run_tool argv 钉 texlate 宿主解释器
    —— uvx/pipx/system-site 部署下 PATH python3 可能是另一份无 texlate
    的解释器且无 VIRTUAL_ENV/CONDA_PREFIX 可借 (site.addsitedir 兜底不
    到), 直接用宿主解释器跑 ``-c`` 内嵌脚本 ``import texlate`` 恒可解析。
    executable 缺位 (嵌入式空串/None) 退回 ``python3`` 旧字面口径。
    """
    if isinstance(v, str):
        if "{main_dir}" in v:
            v = v.replace("{main_dir}", _main_dir_rel(ctx))
        if "{python}" in v:
            v = v.replace("{python}", sys.executable or "python3")
        return v.replace("{payload}", payload or "")
    if isinstance(v, dict):
        return {k: _substitute(x, payload, ctx) for k, x in v.items()}
    if isinstance(v, list):
        return [_substitute(x, payload, ctx) for x in v]
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
    r"""Probe 到的包文件 ``vX.Y`` 主版本号 (package_version_ge 条件用)。

    ``v`` 前缀必须显式——裸日期形 ``\ProvidesPackage{x}[2020/01/01]``
    不再把 ``2020`` 误吃成主版本号 (date-only → ``None``)。
    """
    found = eng.probe_file(fname)
    if not found:
        return None
    try:
        text = Path(found).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    m = re.search(
        r"\\Provides(?:Expl)?(?:Package|Class)\s*\{[^}]*\}[^v\n]*v(\d+)", text
    )
    return int(m.group(1)) if m else None


def _err_site_outside(ctx: LoopCtx, rep: ErrReport | None) -> bool:
    """``err_outside_fileset`` 条件实现: 报错文件栈内层帧判工程外。

    ``rep.file_stack[-1]`` = TeX ``l.N`` 报错所在文件 (内层帧); runaway
    空栈回退 ``popped_files[-1]`` (最近关闭帧肇事口径, 与
    ``_requester_paths`` 同——帧序单源 ``ErrReport.site_frames``)。
    ``is_project_file`` 与红线归因同口径——相对帧/``root`` 内 = 工程
    (fileset 可 patch), texmf/bundle 帧 = 工程外 (fileset 够不到,
    仅 wdir 无关臂可治)。无栈帧证据 (``rep=None`` 的直驱/旧调用面)
    → False (fail-closed)。
    """
    if rep is None:
        return False
    site = next(rep.site_frames(), None)
    return site is not None and not is_project_file(site, ctx.wdir)


# ════════════════════════════════════════════════════════════════
# cond 树敏感面快照 —— fileset/_stem_sibling 的 rglob 文件表与
# source_contains/prim_read_form 的 tex 拼接 blob 每派发各取一次
# ════════════════════════════════════════════════════════════════
#
# miss 轮 ``_cond_ok`` 逐规则评估数十次, 旧制每次各跑一遍全树 rglob +
# ~MB 级 join。同一派发窗内两次 ``_cond_ok`` 之间的盘面突变只能经
# ``_apply`` (规则自写/install 落件/run_tool 产出)——故不变量 =
# 「每次 ``_apply`` 尝试即整槽作废」(loop/gate/precheck 三相的派发
# 全经 ``_apply`` 分派, 崩溃半途而废亦在作废后), ``_match_apply``
# 入口再清一次兜住窗间编译产物 (aux/log 落删) 与 pending_esc 直调
# ``ctx.llm_hook`` 的 ``ctx.write`` —— loop 相文件面恒以当窗树为准。
# ``_landing_sync`` 的外部落件 ``_texts`` invalidate 在窗尾补刀时
# memo 若非空 (上次评估缓存未作废), blob 槽另有 ``sig`` 元素级校验
# (``ctx.read`` 返回对象级比对——invalidate/pop/重写必换对象, 内容
# 相同则 join 相同复用无碍), 与既有 freshness 逐字节同口径;
# files 槽以 loop 派发窗为刷新界 (gate/precheck 现无 fileset 条件)。

#: ``source_blob`` 拼接扩展名集 —— ``LoopCtx.tex_files`` 缺省值镜像
#: (快照 ``files`` 表派生 tex 清单, 不再第二遍 rglob)。
_SOURCE_BLOB_EXTS = (".tex", ".sty", ".cls")


def _cond_snap(ctx: LoopCtx) -> dict[str, Any]:
    """条件快照槽 (挂 ``ctx.io._cond_snap`` 动态面): ``files``/``sig``/``blob``/``shadows`` 四槽惰性填。"""
    snap = getattr(ctx.io, "_cond_snap", None)
    if snap is None:
        snap = {"files": None, "sig": None, "blob": None, "shadows": None}
        ctx.io._cond_snap = snap  # noqa: SLF001 - 同上
    return snap


def _cond_snap_reset(ctx: LoopCtx) -> None:
    """整槽作废——``_apply`` 尝试 / ``_match_apply`` 入口 / pending_esc hook 后。"""
    ctx.io._cond_snap = None  # noqa: SLF001 - 同上


def _cond_files(ctx: LoopCtx) -> list[Path]:
    """``wdir`` 存活文件表快照 (fileset 扩展名集 / ``_stem_sibling`` 共用一次 rglob)。"""
    snap = _cond_snap(ctx)
    if snap["files"] is None:
        snap["files"] = [p for p in ctx.wdir.rglob("*") if p.is_file()]
    return snap["files"]


def _cond_blob(ctx: LoopCtx) -> str:
    """``source_blob`` 等价 tex 源拼接快照 (source_contains/prim_read_form 共用)。

    ``sig`` = 逐 tex 件 ``ctx.read`` 返回对象元组——对象级不等必换
    (invalidate/pop/重写全换对象), 与当日 ``source_blob`` 逐字节同口径。
    """
    snap = _cond_snap(ctx)
    tex = sorted(p for p in _cond_files(ctx) if p.suffix.lower() in _SOURCE_BLOB_EXTS)
    sig = tuple(ctx.read(f) for f in tex)
    if snap["blob"] is None or snap["sig"] != sig:
        snap["sig"] = sig
        snap["blob"] = "\n".join(t for t in sig if t)
    return snap["blob"]


def _cond_shadows(
    ctx: LoopCtx, eng: Engine, exts: tuple[str, ...]
) -> list[tuple[Path, tuple[int, int, int] | None, tuple[int, int, int] | None, str]]:
    """``vendored_shadow`` 候选表快照 —— 按 ``exts`` 键 memo, 同派发窗内复用。

    ``find_vendored_shadows`` 每调一次全量 ``ctx.tex_files`` + probe/read
    系统副本——逐规则重跑纯属浪费; 窗内盘面突变仍由 ``_apply``/``_match_apply``
    入口的整槽作废兜底 (与 files/blob 槽同不变量)。
    """
    snap = _cond_snap(ctx)
    memo = snap["shadows"]
    if memo is None:
        memo = snap["shadows"] = {}
    if exts not in memo:
        memo[exts] = builtins.find_vendored_shadows(ctx, eng, exts)
    return memo[exts]


def _stem_sibling(ctx: LoopCtx, pay: str, exts: list[Any]) -> bool:
    r"""``fileset.sibling_exts`` 实现: payload stem 查图形族交替件。

    payload 剥末位扩展名后的 basename stem 在工程内存 ``exts`` 族交替件
    → True。语义 = same-basename-anywhere (kpathsea TEXINPUTS 近似,
    宁宽勿严): ``figs/a.eps`` 缺件时 ``other/a.pdf`` 也算 sibling——
    false-accept 只亏一轮 (剥名后仍缺 → 下轮占位臂收), false-abstain
    会把盘上真图换成占位框。stem 比对全小写; ``exts`` 各元带 ``.`` 前
    缀对 ``p.suffix``。引擎/封装树不计存活面: ``.`` 前缀部件
    (``.git``/``.fixloop-*``) 与 ``_PDF_SANITIZE_SKIP_DIRS``
    (顶层 ``_texmf``/``_tect_out`` 单源——texmfhome 面与 tectonic 产
    物树非文档内嵌图件)。stem 空 → False。

    ``<stem>-eps-converted-to.<ext>`` 归一为 ``<stem>`` 算 sibling:
    epstopdf ``.eps`` graphics rule 以该命名直读转换件——2308.04278
    实证 ``system-model.eps`` 缺件但 ``system-model-eps-converted-to.pdf``
    在盘时剥名是真解 (而非占位置换), stem 严格相等会把这类格饿死。
    """
    stem = PurePosixPath(
        builtins._norm_graphic_name(pay)  # noqa: SLF001 - graphics 名规整单源
    ).stem.lower()
    if not stem:
        return False
    pool = {str(e).lower() for e in exts}
    for p in _cond_files(ctx):
        parts = p.relative_to(ctx.wdir).parts
        if (
            any(part.startswith(".") for part in parts)
            or parts[0] in _PDF_SANITIZE_SKIP_DIRS
        ):
            continue
        s = p.stem.lower().removesuffix("-eps-converted-to")
        if s == stem and p.suffix.lower() in pool:
            return True
    return False


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
        v = _substitute(val, pay, ctx)
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
            if not regex.search(str(v), _cond_blob(ctx)):
                return False, "源码无该 pattern"
        elif key == "ctx_suggests":
            if not regex.search(str(v), ctx.err_head or ""):
                return False, "err ctx 无提示"
        elif key == "fileset":
            has = v.get("has_ext") or []
            lacks = v.get("lacks_ext") or []
            sib = v.get("sibling_exts") or []
            names = {p.suffix for p in _cond_files(ctx)}
            if any(e not in names for e in has) or any(e in names for e in lacks):
                return False, "fileset 不满足"
            if sib and not _stem_sibling(ctx, str(pay or ""), sib):
                return False, f"payload stem 无 {sib} 族 sibling"
        elif key == "cache_dir_glob":
            if not any(ctx.wdir.glob(str(v))):
                return False, f"无 {v} 匹配"
        elif key == "vendored_shadow":
            if not _cond_shadows(ctx, eng, (".sty", ".cls")):
                return False, "无遮蔽候选"
        elif key == "package_version_ge":
            got = _package_version(eng, str(v.get("file", "")))
            if got is None or got < int(v.get("version", 0)):
                return False, f"{v.get('file')} 版本 {got} < {v.get('version')}"
        elif key == "prim_read_form":
            prim = re.escape(str(v))
            if not re.search(rf"\\if[a-zA-Z@]*\s*\\{prim}\b", _cond_blob(ctx)):
                return False, f"无 \\if*\\{v} 读取语境"
        elif key == "payload_pattern":
            # payload 词形谓词 —— ``pdf@`` 别名族报错定义上即包内宏展开帧
            # (err_outside_fileset/source_contains 双臂都看不见), 按词形直放。
            if not regex.search(str(v), str(pay or "")):
                return False, f"payload 无 {v} pattern"
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
