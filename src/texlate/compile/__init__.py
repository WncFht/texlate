"""编译层：Engine 协议 / ctex 注入 / normalize / clean 判定 / 沙箱（规格 docs/spec/compile.md）。

- `mask`：visible_tex 遮蔽视图（所有手术的定位地基）
- `normalize`：pdfTeX→XeTeX 无条件手术 12 项
- `transcode`：支持件字节转码/净化（aux/bib/中间件/PS 文件——invalid_utf8 修复臂一）
- `shadow`：系统包遮蔽（kpsewhich 解析 + 本地件遮蔽——invalid_utf8 修复臂三）
- `latex209`：LaTeX 2.09 ``documentstyle`` → LaTeX2e 受限升级器（compat 模式唯一注入通路）
- `inject`：ctex/xeCJK 中文注入 + FLOAT_SIZING
- `cjkmap`：GB1→UCS2 ToUnicode CMap 注入（zh.pdf 复制/检索修复）
- `engine`：Engine Protocol + xelatex/tectonic + 静态路由 + compiled_dependencies（实现在 deps.py 经 facade 回引）
- `deps`：编译器自述输入集解析（.fls INPUT / dependencies.mk——翻译文件集权威）
- `loginfo`：.log → LogInfo 语义层 + 错误分类学适配（taxonomy 单源在 fixloop/rules/）
- `probe`：声明依赖静态探针（target_probe）+ 权威输入集差分（deps_diff）
- `judge`：clean/partial/fail 判定三件套 + 中文渲染检查
- `sandbox`：env 白名单 + sandbox-exec + killpg
- `toolchain`：tectonic 五平台 sha256 钉死分发 + 托管件自动安装

惰性门面（PEP 562，同 ``xlat``/``fixloop`` 形制）：``__all__`` 平名经
``__getattr__`` 映射回子模块惰性解析——``import texlate.compile`` 不再
急切拉入 engine/inject/normalize 全链（audit：包外消费者全为子模块级
import，平名消费仅测试钉点与跨包转口；``import texlate.compile.logparse``
从 73 个 texlate 模块降至 ~2）。不在映射的子模块名走 ``import .X``
兜底（``patchseams``/``ctan``/``latex209`` 等——``from texlate.compile import X``
与 ``compile.X`` 同达）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.textutil import decode_tex

    from ._docseams import find_docclass_end
    from .engine import (
        CompRes,
        Engine,
        LogInfo,
        RouteDecision,
        TectonicEngine,
        XelatexEngine,
        classify_error,
        compiled_dependencies,
        engine_for,
        parse_log,
        route_project,
    )
    from .inject import (
        ACM_BASELINESTRETCH_GUARD,
        CTEX_LINE,
        XECJK_BLOCK,
        InjectRejectError,
        classify_no_main,
        demote_wrapfloats,
        find_main_tex,
        inject_cjk,
        inject_float_sizing,
        prepare_chinese,
        relax_float_specs,
    )
    from .judge import (
        CLEAN_ERR_MAX,
        Verdict,
        count_missing_chars,
        judge,
        log_died_mid_doc,
        pdf_cjk_chars,
        pdf_text_stats,
    )
    from .mask import (
        TEX_SOURCE_SUFFIXES,
        apply_edits,
        group_end,
        visible_tex,
        without_comments,
    )
    from .normalize import (
        PIXEL_COMPATIBILITY,
        TECTONIC_FONT_COMPATIBILITY,
        XETEX_COMPATIBILITY,
        XETEX_EARLY_DEFS,
        normalize_engine,
        normalize_project,
        source_path_violations,
    )
    from .probe import (
        DepProbe,
        DepsDiff,
        ProbeReport,
        dep_seen,
        deps_diff,
        target_probe,
    )
    from .sandbox import child_env, find_tool, run_process, sandbox_wrap
    from .toolchain import ensure_tectonic, install_tectonic, resolve_tool

#: 平名 → 源模块。``.x`` 相对 spec = 包内叶；绝对 spec = 跨包转口
#: （``decode_tex`` 钉 texlate.textutil——eager 期同款转口语义）。
_SUBMODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "._docseams": ("find_docclass_end",),
    ".engine": (
        "CompRes",
        "Engine",
        "LogInfo",
        "RouteDecision",
        "TectonicEngine",
        "XelatexEngine",
        "classify_error",
        "compiled_dependencies",
        "engine_for",
        "parse_log",
        "route_project",
    ),
    ".inject": (
        "ACM_BASELINESTRETCH_GUARD",
        "CTEX_LINE",
        "XECJK_BLOCK",
        "InjectRejectError",
        "classify_no_main",
        "demote_wrapfloats",
        "find_main_tex",
        "inject_cjk",
        "inject_float_sizing",
        "prepare_chinese",
        "relax_float_specs",
    ),
    ".judge": (
        "CLEAN_ERR_MAX",
        "Verdict",
        "count_missing_chars",
        "judge",
        "log_died_mid_doc",
        "pdf_cjk_chars",
        "pdf_text_stats",
    ),
    ".mask": (
        "TEX_SOURCE_SUFFIXES",
        "apply_edits",
        "group_end",
        "visible_tex",
        "without_comments",
    ),
    ".normalize": (
        "PIXEL_COMPATIBILITY",
        "TECTONIC_FONT_COMPATIBILITY",
        "XETEX_COMPATIBILITY",
        "XETEX_EARLY_DEFS",
        "normalize_engine",
        "normalize_project",
        "source_path_violations",
    ),
    ".probe": (
        "DepProbe",
        "DepsDiff",
        "ProbeReport",
        "dep_seen",
        "deps_diff",
        "target_probe",
    ),
    ".sandbox": ("child_env", "find_tool", "run_process", "sandbox_wrap"),
    ".toolchain": ("ensure_tectonic", "install_tectonic", "resolve_tool"),
    "texlate.textutil": ("decode_tex",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _SUBMODULE_EXPORTS.items() for name in names
}

# 字面列表——ruff F822 静态点名要字面值；键集 = _LAZY 键集，新增导出两侧同步。
__all__ = [
    "ACM_BASELINESTRETCH_GUARD",
    "CLEAN_ERR_MAX",
    "CTEX_LINE",
    "PIXEL_COMPATIBILITY",
    "TECTONIC_FONT_COMPATIBILITY",
    "TEX_SOURCE_SUFFIXES",
    "XECJK_BLOCK",
    "XETEX_COMPATIBILITY",
    "XETEX_EARLY_DEFS",
    "CompRes",
    "DepProbe",
    "DepsDiff",
    "Engine",
    "InjectRejectError",
    "LogInfo",
    "ProbeReport",
    "RouteDecision",
    "TectonicEngine",
    "Verdict",
    "XelatexEngine",
    "apply_edits",
    "child_env",
    "classify_error",
    "classify_no_main",
    "compiled_dependencies",
    "count_missing_chars",
    "decode_tex",
    "demote_wrapfloats",
    "dep_seen",
    "deps_diff",
    "engine_for",
    "ensure_tectonic",
    "find_docclass_end",
    "find_main_tex",
    "find_tool",
    "group_end",
    "inject_cjk",
    "inject_float_sizing",
    "install_tectonic",
    "judge",
    "log_died_mid_doc",
    "normalize_engine",
    "normalize_project",
    "parse_log",
    "pdf_cjk_chars",
    "pdf_text_stats",
    "prepare_chinese",
    "relax_float_specs",
    "resolve_tool",
    "route_project",
    "run_process",
    "sandbox_wrap",
    "source_path_violations",
    "target_probe",
    "visible_tex",
    "without_comments",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 子模块属性；子模块名走 ``import .X`` 兜底。"""
    mod = _LAZY.get(name)
    if mod is not None:
        value = getattr(importlib.import_module(mod, __name__), name)
        globals()[name] = value
        return value
    try:
        return importlib.import_module(f".{name}", __name__)
    except ModuleNotFoundError as e:
        # 只在「真无此子模块」时翻 AttributeError——叶内自身的缺依赖
        # ModuleNotFoundError 不吞，原样抛出保住真因。
        if e.name == f"{__name__}.{name}":
            msg = f"module {__name__!r} has no attribute {name!r}"
            raise AttributeError(msg) from None
        raise


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))
