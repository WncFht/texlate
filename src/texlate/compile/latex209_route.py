r"""compile.latex209_route — 选项分派与随源 ds@ 桥叶 (compile.latex209 域缝叶)。

``upgrade_209`` 的工程树判定臂：选项段拆解、随源 ``<opt>.sty``/``<cls>.sty``
检出、``ds@`` 分发探测、随源 documentstyle 桥体（``\input`` + ``\@options``
分发件复刻）、三路选项分派（剥除硬不兼容 → 内核/类内建 → 宏包/随源 →
默认落类选项）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.textutil import _tar_disguised, decode_tex

from .latex209_tables import (
    _DS_AT_RE,
    _GLOB_SAFE_RE,
    _INCOMPAT_PKGS,
    _KERNEL_OPTS,
    _PKG_OPTS,
)
from .mask import visible_tex

if TYPE_CHECKING:
    from pathlib import Path

    from .latex209_tables import _ClassSpec


def _split_opts(optspan: str | None) -> list[str]:
    """从掩码视图选项段提选项名。

    注释字符已被 ``visible_tex`` 掩成空白、真实空白本就该剥——非空白字符即
    选项文本；逗号切分后空段（被整段注释掉的选项）丢弃。
    """
    if not optspan:
        return []
    compact = "".join(c for c in optspan if not c.isspace())
    return [o for o in compact.split(",") if o]


def _ships_style(root: Path | None, name: str) -> bool:
    """工程树内检出随源 ``<name>.sty``——该选项是随稿样式文件，走 usepackage。"""
    if root is None or ".." in name or not _GLOB_SAFE_RE.fullmatch(name):
        return False
    return any(root.rglob(f"{name}.sty"))


def _uses_ds_at(root: Path | None, cls: str) -> bool:
    """随源 ``<cls>.sty``/``<cls>.cls`` 检出 ``ds@`` 选项分发定义。

    检索面为 ``visible_tex`` 遮盖视图——注释/逐字环境内的 ``ds@`` 字样
    不参与判定（真分发形态见 ``_DS_AT_RE`` 注）。
    """
    if root is None or ".." in cls or not _GLOB_SAFE_RE.fullmatch(cls):
        return False
    for cand in root.rglob(f"{cls}.*"):
        if cand.suffix not in {".sty", ".cls"}:
            continue
        try:
            blob = cand.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue  # tar 伪装件——成员文本可含 ds@ 字样（inject._iter_tex 同闸）
        if _DS_AT_RE.search(visible_tex(decode_tex(blob))):
            return True
    return False


def _style209_path(root: Path | None, cls: str) -> str | None:
    r"""随源 ``<cls>.sty`` 检出 → 相对 ``root`` 的 posix 路径；缺席 ``None``。

    桥体只 ``\input`` ``.sty`` 载体——2.09 documentstyle 本体一律以 ``.sty``
    发行；只携 ``.cls`` 的工程走原盲升（真 2e 类文件可直接载）。tar 伪装
    件同 ``_uses_ds_at`` 闸剔除；多命中取目录最浅者（编译
    ``cwd=main.parent`` 的平铺案排前）。
    """
    if root is None or ".." in cls or not _GLOB_SAFE_RE.fullmatch(cls):
        return None
    for cand in sorted(
        (c for c in root.rglob(f"{cls}.sty") if c.is_file()),
        key=lambda c: (len(c.relative_to(root).parts), str(c)),
    ):
        try:
            blob = cand.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue
        return cand.relative_to(root).as_posix()
    return None


def _ds_at_bridge(cls: str, sty_rel: str, opts: list[str]) -> str:
    r"""随源 2.09 documentstyle 桥体——``\input{<cls>.sty}`` + ``\@options`` 分发件。

    ``\@options`` 是 2.09 样式文件的自分发钩：样式本体在定义完
    ``ds@<opt>`` 处理器后自行调用它，逐选项执行 ``\ds@<opt>``，未定义则
    ``\input{<opt>.sty}``。2e 内核无此宏——本桥复刻其语义：分发字面
    选项表（未定义处理器退回 ``\IfFileExists`` 装载，缺席跳过），执行后
    自耗成空操作；样式不调用时由桥尾补调一次——恰好一次分发。同窗口
    ``\@ifdefinable`` 放开为无条件执行：2.09 样式假设独占计数器空间
    （``\newcounter{section}`` 等撞上预载类已注册名），lax 版让重分配
    直接生效。
    """
    safe_opts = [o for o in opts if _GLOB_SAFE_RE.fullmatch(o)]
    bare = f"\\input{{{cls}.sty}}"
    if sty_rel == f"{cls}.sty":
        load = bare
    else:
        # sty 在子目录——先按编译 cwd 裸名解析（main.parent 邻位常态），
        # 再退 root 相对路径；两路皆空时回退裸名让 missing_file 走正常
        # 归因面。
        rel = f"\\input{{{sty_rel}}}"
        load = (
            f"\\IfFileExists{{{cls}.sty}}{{{bare}}}"
            f"{{\\IfFileExists{{{sty_rel}}}{{{rel}}}{{{bare}}}}}"
        )
    return (
        "% texlate: LaTeX 2.09 ds@ bridge —— 随源 documentstyle 当 2e 样式装载\n"
        "\\makeatletter\n"
        "\\def\\@options{\\@for\\@tempa:="
        + ",".join(safe_opts)
        + "\\do{\\@ifundefined{ds@\\@tempa}"
        "{\\IfFileExists{\\@tempa.sty}{\\input{\\@tempa.sty}}{}}"
        "{\\@nameuse{ds@\\@tempa}}}\\gdef\\@options{}}\n"
        # ``\renewcommand``/``\DeclareTextCommand`` 会把 ``\@ifdefinable``
        # 重绑回自恢复体 ``\@rc@ifdefinable``（其体内首动作即还原内核版）——
        # 两路同放开才护得住整个 \input 窗口。
        "\\let\\@ifdefinable@orig\\@ifdefinable\n"
        "\\let\\@rc@ifdefinable@orig\\@rc@ifdefinable\n"
        "\\def\\@ifdefinable#1#2{#2}\\def\\@rc@ifdefinable#1#2{#2}\n"
        + load
        + "\n\\@options\n"
        "\\let\\@ifdefinable\\@ifdefinable@orig\n"
        "\\let\\@rc@ifdefinable\\@rc@ifdefinable@orig\n"
        "\\makeatother"
    )


def _route_opts(
    opts: list[str], spec: _ClassSpec | None, root: Path | None, target: str
) -> tuple[list[str], list[str], list[str], list[str]]:
    """选项三路分派 → ``(class_opts, pkg_opts, shipped_hits, stripped)``。

    判别序：209 选项名先经目标类 ``rename`` 表改写成 2e 词汇，再查目标类
    硬不兼容表（剥除）→ 内核选项 → 目标类内建表 → 宏包白名单/随源
    ``.sty`` → 默认落类选项。
    """
    incompat = _INCOMPAT_PKGS.get(target, frozenset())
    cls_opts: list[str] = []
    pkg_opts: list[str] = []
    shipped: list[str] = []
    stripped: list[str] = []
    for opt in opts:
        o = spec.rename.get(opt, opt) if spec is not None else opt
        if o in incompat:
            stripped.append(o)
        elif o in _KERNEL_OPTS or (spec is not None and o in spec.options):
            cls_opts.append(o)
        elif o in _PKG_OPTS or _ships_style(root, o):
            pkg_opts.append(o)
            if o not in _PKG_OPTS:
                shipped.append(o)
        else:
            cls_opts.append(o)
    return cls_opts, pkg_opts, shipped, stripped
