r"""compile.latex209.main — 升级编排主入口叶 (compile.latex209 域缝叶)。

``upgrade_209`` 主编排 + 其私有臂：改名目标类可解析性守卫
``_target_resolvable``（本叶命名空间即 monkeypatch 锚点——patch
``latex209.main._target_resolvable`` 才改 ``upgrade_209`` 的调用解析）、
revtex4-2 ``\topskip`` 活赋值删除、首个深度 0 ``\documentstyle`` 定位。
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from texlate.compile.latex209.math import _fix_math_209
from texlate.compile.latex209.route import (
    _ds_at_bridge,
    _route_opts,
    _split_opts,
    _style209_path,
    _uses_ds_at,
)
from texlate.compile.latex209.shim import (
    _MULTICOLS_SHIM,
    _PRE_CLASS_SHIM,
    _REVTEX209_SHIM,
    COMPAT_SHIM,
)
from texlate.compile.latex209.tables import (
    _CLASS_MAP,
    _DS_AT_CLASSES,
    _GLOB_SAFE_RE,
    _KERNEL_OPTS,
    _STD_CLASSES,
    _TOPSKIP_ASSIGN_RE,
)
from texlate.compile.mask import visible_tex
from texlate.textutil import DOCSTYLE_DECL_RX, DOCSTYLE_RX, iter_depth0

if TYPE_CHECKING:
    import re
    from pathlib import Path


def _target_resolvable(root: Path | None, target: str) -> bool:
    """改名目标类可解析性——工程树 ``<target>.cls`` 或系统 kpsewhich 命中。

    kpsewhich 缺席/探测失败 fail-open：合法映射目标都在系统 texmf，缺工具
    不阻断（``_kpse_resolve`` 同款语义）；真返回空才判不可解析。
    """
    if (
        root is not None
        and _GLOB_SAFE_RE.fullmatch(target)
        and any(root.rglob(f"{target}.cls"))
    ):
        return True
    kpse = shutil.which("kpsewhich")
    if kpse is None:
        return True
    try:
        proc = subprocess.run(  # noqa: S603 — 固定 argv 无 shell
            [kpse, "--", f"{target}.cls"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _drop_topskip_assigns(tex: str) -> tuple[str, int]:
    r"""删全文深度 0、语句首位的活 ``\topskip`` 赋值；返回 ``(new_tex, count)``。

    语句首位判定：遮盖视图前缀去空白后尾字符 ∈ ``\n``/``}``/``;``（或文首）。
    该口径挡掉 ``= \topskip``/``\ifdim\topskip``/``\advance\topskip`` 等读用
    位——它们前一位是 ``=`` 或字母，不在白名单。
    """
    vis = visible_tex(tex)
    hits = [
        m
        for m in iter_depth0(_TOPSKIP_ASSIGN_RE, vis)
        if not (prefix := vis[: m.start()].rstrip(" \t")) or prefix[-1] in "\n};"
    ]
    for m in reversed(hits):
        tex = tex[: m.start()] + tex[m.end() :]
    return tex, len(hits)


def _primary_docstyle(vis: str) -> re.Match[str] | None:
    r"""首个 brace 深度 0 的 ``\documentstyle``——真声明点。

    深度>0 命中（``\newcommand{\ds}{\documentstyle{..}}`` 宏体、``\ifmain{..}``
    实参）不是声明点——全文搜首个会把 COMPAT_SHIM 塞进 def 体（fuzz I5）。
    """
    return next(iter_depth0(DOCSTYLE_DECL_RX, vis), None)


def upgrade_209(  # noqa: C901, PLR0912 -- 守卫链 + shim 分派逐支对应升级决策条目
    tex: str, *, root: Path | None = None
) -> tuple[str, dict]:
    r"""首个深度 0 ``\documentstyle`` 升级为 2e 形态；返回 ``(new_tex, info)``。

    ``root`` 提供工程树（可选）：选项位检出随源 ``<opt>.sty`` 进 ``\usepackage``；
    未映射非标准类携随源 ``<cls>.sty`` → ds@ 桥（article 底 + ``\input`` 样式
    + ``\@options`` 分发件，``info["ds_bridge"]`` 置位）；无随源载体且检出
    ``ds@`` 定义 → 拒转。
    残余的活 ``\documentstyle`` 记号（宏体/次分支）逐 token 改名
    ``\documentclass``——compat 下二次声明照样非法。

    ``info["status"]`` ∈ ``converted`` / ``reject`` / ``no-docstyle``；``reject``
    时 ``info["reason"]`` 供 inject 层记 ``inject_reject:<reason>``。
    """
    vis = visible_tex(tex)
    m = _primary_docstyle(vis)
    if m is None:
        if next(iter_depth0(DOCSTYLE_RX, vis), None) is not None:
            # 深度 0 裸 ``\documentstyle`` token 在场但配不出 ``[opt]{cls}``
            # 声明（残缺尾、选项段异常）——inject.find_docclass_ends 同深度
            # 口径会把它当缝走到这里，泛 ``latex209`` 落账混进真 209 拒收，
            # 细分标记供归因。深度>0 宏体残影（未闭合花括号内 token）
            # 不进此桶——inject 同深度口径也不会触达。
            return tex, {"status": "reject", "reason": "latex209_no_decl"}
        return tex, {"status": "no-docstyle"}
    cls = m.group(2).strip()
    if not cls:
        return tex, {"status": "no-docstyle"}
    # ds@ 桥：未映射非标准类携 ``<cls>.sty`` 随源即走「article 底 + \input
    # 样式 + \@options 分发」桥路，不再拒转；只有无载体可桥时保留原拒收。
    sty_rel: str | None = None
    if cls not in _CLASS_MAP and cls not in _STD_CLASSES:
        sty_rel = _style209_path(root, cls)
    if sty_rel is None and (
        cls in _DS_AT_CLASSES
        or (
            cls not in _CLASS_MAP and cls not in _STD_CLASSES and _uses_ds_at(root, cls)
        )
    ):
        return tex, {
            "status": "reject",
            "reason": "latex209_ds_at",
            "class": cls,
        }
    opts = _split_opts(m.group(1))
    if sty_rel is not None:
        spec = None
        target = "article"
        # 选项全量进 ``\@options`` 字面分发表（2.09 原语义）；内核选项另
        # 留类选项位让 article 侧拿到真实效果——两路不冲突。
        cls_opts = [o for o in opts if o in _KERNEL_OPTS]
        pkg_opts: list[str] = []
        shipped: list[str] = []
        stripped: list[str] = []
    else:
        spec = _CLASS_MAP.get(cls)
        target = spec.target if spec is not None else cls
        if target != cls and not _target_resolvable(root, target):
            # 盲升守卫：改名目标类双侧（工程/系统 texmf）不可解析——升上去
            # missing_file 必死（jpsj→jpsj3 教训：jpsj3 从未发行），拒转记台账。
            return tex, {
                "status": "reject",
                "reason": "latex209_no_target",
                "class": cls,
                "target": target,
            }
        cls_opts, pkg_opts, shipped, stripped = _route_opts(opts, spec, root, target)
    lines = [
        _PRE_CLASS_SHIM,
        f"\\documentclass[{','.join(cls_opts)}]{{{target}}}"
        if cls_opts
        else f"\\documentclass{{{target}}}",
        COMPAT_SHIM,
    ]
    if sty_rel is not None:
        lines.append(_ds_at_bridge(cls, sty_rel, opts))
    if target == "revtex4-2":
        # revtex4-2 删除面整块 polyfill——209 revtex 文稿习惯
        # （\twocolumn[...] 宽头、序言裸 \author、\wideabs、\pacs）
        # partial 稿不进 fixloop（--on fail 门），补位只能在升级缝。
        lines.append(_REVTEX209_SHIM)
    if "multicol" in stripped:
        lines.append(_MULTICOLS_SHIM)
    if pkg_opts:
        # shim 必须先于路由出的 \usepackage——209 时代 .sty 加载时就要见到
        # \footheight/\ifoldfss 等定义（2501.05407 nips.sty 实证）。
        lines.append("\\usepackage{" + ",".join(pkg_opts) + "}")
    new_tex = tex[: m.start()] + "\n".join(lines) + tex[m.end() :]
    # 残余 \documentstyle 记号改名（遮盖视图定位、原文回填，倒序保 offset）。
    vis2 = visible_tex(new_tex)
    for dm in reversed([*DOCSTYLE_RX.finditer(vis2)]):
        new_tex = new_tex[: dm.start()] + "\\documentclass" + new_tex[dm.end() :]
    dropped_topskip = 0
    if target == "revtex4-2":
        # ltxgrid 输出例程不容运行期 topskip 改写（gr-qc/0104075 实证
        # \topskip 0mm → enddoc \clearpage 7 万页死循环）——209 preamble
        # 的裸 topskip 赋值升上来即毒根，逐语句首位活赋值删除。
        new_tex, dropped_topskip = _drop_topskip_assigns(new_tex)
    # 209 数学域两族转写——``{\em X}`` 升上来在数学域必报
    # ``Command \itshape invalid in math mode``（\em 是 switch 非参数形），
    # ``\it``/``\bf`` 同形态归一消歧；裸 ``\cite{..}`` 的 natbib 未定义标记
    # ``{\reset@font\bfseries ?}`` 同标记硬报且 fixloop 自续，裹 ``\mbox{}``。
    new_tex, math_switch_fixed, math_cite_wrapped = _fix_math_209(new_tex)
    return new_tex, {
        "status": "converted",
        "orig": tex[m.start() : m.end()],
        "class": cls,
        "target": target,
        "ds_bridge": sty_rel is not None,
        "bridge_sty": sty_rel,
        "class_opts": cls_opts,
        "pkg_opts": pkg_opts,
        "shipped": shipped,
        "stripped": stripped,
        "topskip_dropped": dropped_topskip,
        "math_switch_fixed": math_switch_fixed,
        "math_cite_wrapped": math_cite_wrapped,
    }
