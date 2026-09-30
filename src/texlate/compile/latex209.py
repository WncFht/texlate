r"""LaTeX 2.09 ``\documentstyle`` → LaTeX2e ``\documentclass`` 受限升级器。

compat 模式在内核层禁用 ``\usepackage``（探针实证：A 臂 11/11 同签名全灭）——
2.09 文档唯一的 CJK 注入通路是先升级成
2e 形态。本模块只做有界转换：

- 首个非注释 ``\documentstyle[o]{c}`` 改写为 ``\documentclass`` + ``\usepackage``
  拆分。定位走 :func:`texlate.compile.mask.visible_tex` 等长掩码视图——注释与
  verbatim 里的 ``\documentstyle`` 命中不到，且选项段内的穿插注释被掩成空白，
  offset 与原文逐字节对齐，回原文做 span 替换；
- 209 时代类名映射到存续 2e 类（revtex→revtex4-2 等）；未识别类名原样保留，
  缺 ``.cls`` 交 fixloop missing_file → CTAN fetch；
- 选项三路分派：目标类 ``\incompatible@package`` 硬不兼容名（revtex4-2:
  cite/mcite/multicol——loaded 即 ``\ClassError``+``\stop``）剥除记账 →
  内核/目标类内建选项 → 类选项（未知选项进类只是
  "unused global option" warning，错进 ``\usepackage`` 是 missing_file 硬错）；
  已知宏包名或工程随源 ``<opt>.sty`` → ``\usepackage``；默认落类选项。
  multicol 被剥时附 ``\multicols``/``\col@number``/``\multicolsep`` 透传
  shim 保正文环境与长度赋值可解析；revtex4-2 目标另附
  ``_REVTEX209_SHIM``——cls 刻意删掉的 209 文稿面（``\frontmatter@init``
  武装 + ``\twocolumn``/``\@makecol``/``\wideabs``/``\abstract`` 兜底 +
  ``\pacs`` 闸门解除），partial 稿不进 fixloop，补位只能在升级缝；
- 转换产物尾部附 ``COMPAT_SHIM``——探针实证的 209 内建残留（``\Box`` 系
  latexsym、``\vruleheight``、``\ifoldfss``、``\footheight``、``\tightenlines``、
  ``\@floats``）+ 209 序言面普查件（``\ifnfssone``、旧字体开关
  ``\rm``..``\sc``、``\cal``、plain/lfonts 字体系、``\theorembodyfont``、
  ``\address``/``\collab``/``\abstracts`` 渲染透传——全 ``\@ifundefined``
  守护，原生已定义目标类不吃惊）；
- ``ds@`` 选项机驱动的 style-as-class（ias/jaa/julie，及随源 ``<cls>.sty``/``.cls``
  内检出 ``ds@`` 定义者）不可转——2e 无此分发机制，返回 ``reject`` 状态交
  inject 层按 ``latex209_ds_at`` 拒；
- 改名目标类落盘前做可解析性守卫（盲升闸）：工程树 ``<target>.cls`` 或
  ``kpsewhich`` 双侧均无命中 → 升上去必 missing_file（jpsj3 不在 CTAN），
  按 ``latex209_no_target`` 拒；kpsewhich 缺席/探测失败 fail-open 不阻断。

god-split: 实现体按域拆进同包 5 叶——``latex209_tables``（选项路由
静态表：内核/标准类/宏包白名单 + 类映射 + ds@/topskip 正则）、
``latex209_math``（数学域模态走查 + switch 组/cite 包裹两族转写 +
``wrap_math_cites`` 独立出口）、``latex209_shim``（COMPAT_SHIM/
_PRE_CLASS_SHIM/_MULTICOLS_SHIM/REVTEX209_CORE/_REVTEX209_SHIM 垫块
文本）、``latex209_route``（选项三路分派 + 随源 ``<cls>.sty`` 检出 +
ds@ 桥体）、``latex209_main``（``upgrade_209`` 编排 + ``_target_resolvable``
盲升闸 + ``_drop_topskip_assigns`` + ``_primary_docstyle``）。本文件是
PEP 562 惰性门面（同 ``validate/l0`` 形制）——平名经 ``_LEAF_EXPORTS``
映射回叶子，``__getattr__`` 首访解析并缓存，``latex209.X`` 公共面与
``from ... import X``/``latex209._x`` 属性读面不变。monkeypatch 锚点
注意：patch 叶子不 patch 门面（docs/dev/seams.md §1）——
``_target_resolvable`` 桩点已迁 ``latex209_main``（调用方 ``upgrade_209``
同叶命名空间直读）；``latex209.shutil``/``latex209.subprocess`` 经门面
解析到的仍是真 stdlib 模块对象（``latex209_main`` 运行期 import），
对其 setattr 全局生效不变。叶子间互引走全路径直跨
（``texlate.compile.latex209_<叶>``），不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.latex209_main import (
        DOCSTYLE_DECL_RX,
        DOCSTYLE_RX,
        _drop_topskip_assigns,
        _primary_docstyle,
        _target_resolvable,
        iter_depth0,
        shutil,
        subprocess,
        upgrade_209,
    )
    from texlate.compile.latex209_math import (
        _BOXREG_CS_209,
        _BOXREG_RE,
        _BOXSPEC_CS_209,
        _BOXSPEC_RE,
        _MATH_CITE_CS_209,
        _MATH_CITE_RE,
        _MATH_ENV_RE,
        _MATH_ENVS_209,
        _MATH_SWITCH_209,
        _MATH_SWITCH_RE,
        _TEXTARG_CS_209,
        _TEXTARG_CS_RE,
        Final,
        _cite_call_end,
        _cite_mbox_edits,
        _fix_math_209,
        _innermost,
        _math_env_spans,
        _math_regions,
        _textarg_spans,
        apply_edits,
        cs_events_spans,
        group_end,
        re,
        visible_tex,
        wrap_math_cites,
        ws_skip,
    )
    from texlate.compile.latex209_route import (
        _ds_at_bridge,
        _route_opts,
        _ships_style,
        _split_opts,
        _style209_path,
        _tar_disguised,
        _uses_ds_at,
        decode_tex,
    )
    from texlate.compile.latex209_shim import (
        _MULTICOLS_SHIM,
        _PRE_CLASS_SHIM,
        _REVTEX209_SHIM,
        COMPAT_SHIM,
        REVTEX209_CORE,
    )
    from texlate.compile.latex209_tables import (
        _CLASS_MAP,
        _DS_AT_CLASSES,
        _DS_AT_RE,
        _GLOB_SAFE_RE,
        _INCOMPAT_PKGS,
        _KERNEL_OPTS,
        _PKG_OPTS,
        _STD_CLASSES,
        _TOPSKIP_ASSIGN_RE,
        CMD_BOUNDARY,
        NamedTuple,
        _ClassSpec,
        annotations,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "latex209_main": (
        "DOCSTYLE_DECL_RX",
        "DOCSTYLE_RX",
        "_drop_topskip_assigns",
        "_primary_docstyle",
        "_target_resolvable",
        "iter_depth0",
        "shutil",
        "subprocess",
        "upgrade_209",
    ),
    "latex209_math": (
        "Final",
        "_BOXREG_CS_209",
        "_BOXREG_RE",
        "_BOXSPEC_CS_209",
        "_BOXSPEC_RE",
        "_MATH_CITE_CS_209",
        "_MATH_CITE_RE",
        "_MATH_ENVS_209",
        "_MATH_ENV_RE",
        "_MATH_SWITCH_209",
        "_MATH_SWITCH_RE",
        "_TEXTARG_CS_209",
        "_TEXTARG_CS_RE",
        "_cite_call_end",
        "_cite_mbox_edits",
        "_fix_math_209",
        "_innermost",
        "_math_env_spans",
        "_math_regions",
        "_textarg_spans",
        "apply_edits",
        "cs_events_spans",
        "group_end",
        "re",
        "visible_tex",
        "wrap_math_cites",
        "ws_skip",
    ),
    "latex209_route": (
        "_ds_at_bridge",
        "_route_opts",
        "_ships_style",
        "_split_opts",
        "_style209_path",
        "_tar_disguised",
        "_uses_ds_at",
        "decode_tex",
    ),
    "latex209_shim": (
        "COMPAT_SHIM",
        "REVTEX209_CORE",
        "_MULTICOLS_SHIM",
        "_PRE_CLASS_SHIM",
        "_REVTEX209_SHIM",
    ),
    "latex209_tables": (
        "CMD_BOUNDARY",
        "NamedTuple",
        "TYPE_CHECKING",
        "_CLASS_MAP",
        "_ClassSpec",
        "_DS_AT_CLASSES",
        "_DS_AT_RE",
        "_GLOB_SAFE_RE",
        "_INCOMPAT_PKGS",
        "_KERNEL_OPTS",
        "_PKG_OPTS",
        "_STD_CLASSES",
        "_TOPSKIP_ASSIGN_RE",
        "annotations",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "CMD_BOUNDARY",
    "COMPAT_SHIM",
    "DOCSTYLE_DECL_RX",
    "DOCSTYLE_RX",
    "REVTEX209_CORE",
    "TYPE_CHECKING",
    "_BOXREG_CS_209",
    "_BOXREG_RE",
    "_BOXSPEC_CS_209",
    "_BOXSPEC_RE",
    "_CLASS_MAP",
    "_DS_AT_CLASSES",
    "_DS_AT_RE",
    "_GLOB_SAFE_RE",
    "_INCOMPAT_PKGS",
    "_KERNEL_OPTS",
    "_MATH_CITE_CS_209",
    "_MATH_CITE_RE",
    "_MATH_ENVS_209",
    "_MATH_ENV_RE",
    "_MATH_SWITCH_209",
    "_MATH_SWITCH_RE",
    "_MULTICOLS_SHIM",
    "_PKG_OPTS",
    "_PRE_CLASS_SHIM",
    "_REVTEX209_SHIM",
    "_STD_CLASSES",
    "_TEXTARG_CS_209",
    "_TEXTARG_CS_RE",
    "_TOPSKIP_ASSIGN_RE",
    "Final",
    "NamedTuple",
    "_ClassSpec",
    "_cite_call_end",
    "_cite_mbox_edits",
    "_drop_topskip_assigns",
    "_ds_at_bridge",
    "_fix_math_209",
    "_innermost",
    "_math_env_spans",
    "_math_regions",
    "_primary_docstyle",
    "_route_opts",
    "_ships_style",
    "_split_opts",
    "_style209_path",
    "_tar_disguised",
    "_target_resolvable",
    "_textarg_spans",
    "_uses_ds_at",
    "annotations",
    "apply_edits",
    "cs_events_spans",
    "decode_tex",
    "group_end",
    "iter_depth0",
    "re",
    "shutil",
    "subprocess",
    "upgrade_209",
    "visible_tex",
    "wrap_math_cites",
    "ws_skip",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and (
            isinstance(v, dict)
            or (callable(v) and getattr(v, "__module__", None) == __name__)
        )
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
