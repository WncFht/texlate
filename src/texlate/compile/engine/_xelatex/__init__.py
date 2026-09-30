r"""xelatex 引擎 —— TeX Live 系全工具链通路（``engine.py`` 拆分叶，二级门面）。

``run_process``/``find_tool`` 走 ``_eng.`` 运行期回查——测试 patch
缝钉在 ``texlate.compile.engine.X`` 模块名上（worker ``_w.`` 同款）。

god-split: 实现体按域拆进同包 6 孙叶——``_xelatex.frame``（compile()
头尾段共享件 ``_prepare_main``/``_harvest`` + ``\end{document}`` 输入覆盖
出货闸）、``_xelatex.bib``（``.bbl``/``.bcf``/aux 文件态判件 +
``_XelatexBib`` 趟间补跑 mixin）、``_xelatex.probe``（``_XelatexProbe``
kpsewhich/tlpdb/tlmgr 探测 mixin）、``_xelatex.install``
（``_XelatexInstall`` tlmgr usermode 装件 mixin）、``_xelatex.runenv``
（``_XelatexEnv`` env 构造/argv plumbing mixin）、``_xelatex.main``
（``XelatexEngine`` 组合根 + pass 环闸常量）。本文件是 PEP 562 惰性门面
（同 ``latex209``/``pipeline`` 形制）——平名经 ``_LEAF_EXPORTS`` 映射回
孙叶，``__getattr__`` 首访解析并缓存，``_xelatex.X`` 公共面与
``from texlate import X`` 属性读面不变（``_tectonic`` 的
``_harvest``/``_prepare_main`` 回取不受影响）。孙叶间互引走全路径直跨
（``._xelatex_<叶>``），不经本门面；mixin 宿主属性/方法契约经叶内
``TYPE_CHECKING`` 声明钉静态面（segmenter ``args_handlers`` 同式）。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.engine._xelatex.bib import (
        _AUX_CITE_RX,
        _BBL_HEAD_BYTES,
        _BBL_KEY_RX,
        _BBL_TAIL_BYTES,
        _BBL_TAIL_RX,
        _BBL_VER_RX,
        _BCF_MIN_BYTES,
        _BCF_TAIL_BYTES,
        _BCF_TAIL_RX,
        _BIB_AUX_SCAN_MAX,
        _BIB_TOOL_TIMEOUT_MAX,
        _BIBDATA_RX,
        _BLX_VER_MEMO,
        _BLX_VER_RX,
        _aux_cite_keys,
        _bbl_complete,
        _bbl_decl_version,
        _bbl_keys,
        _bbl_stray_candidate,
        _bbl_version_skewed,
        _bcf_intact,
        _bibdata_resolvable,
        _has_bbl,
        _XelatexBib,
        contextlib,
    )
    from texlate.compile.engine._xelatex.frame import (
        _ENDDOC_MAX_DEPTH,
        _ENDDOC_RX,
        _ENDINPUT_DEF_RX,
        _ENDINPUT_RX,
        _INCLUDE_SRC_RX,
        Path,
        _checked_main,
        _enddoc_scan,
        _harvest,
        _input_covers_enddoc,
        _prepare_main,
        compiled_dependencies,
        os,
        re,
        visible_tex,
    )
    from texlate.compile.engine._xelatex.install import (
        _XelatexInstall,
        shutil,
        tlmgr_search_cache_path,
    )
    from texlate.compile.engine._xelatex.main import (
        _ADAPTIVE_PASS_CAP,
        _RERUN_HINT_RX,
        _SHELL_ESCAPE_FLAGS,
        DEFAULT_TIMEOUT,
        ENV_TLNET,
        MAX_PASSES,
        CompRes,
        XelatexEngine,
        _apply_sandbox,
        _collect_compile_outputs,
        _rc_to_signal,
        _salvage_driver_fatal,
        env_raw,
        log_text_of,
        parse_log,
    )
    from texlate.compile.engine._xelatex.probe import (
        _PROBE_MEMO_MAX,
        _XelatexProbe,
        load_search_cache,
        safe_is_file,
        save_search_cache,
    )
    from texlate.compile.engine._xelatex.runenv import (
        _OUTPUT_REKEY_PREFIXES,
        _texmfdist,
        _XelatexEnv,
        child_env,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "bib": (
        "_AUX_CITE_RX",
        "_BBL_HEAD_BYTES",
        "_BBL_KEY_RX",
        "_BBL_TAIL_BYTES",
        "_BBL_TAIL_RX",
        "_BBL_VER_RX",
        "_BIBDATA_RX",
        "_BIB_AUX_SCAN_MAX",
        "_BIB_TOOL_TIMEOUT_MAX",
        "_BLX_VER_MEMO",
        "_BLX_VER_RX",
        "_BCF_MIN_BYTES",
        "_BCF_TAIL_BYTES",
        "_BCF_TAIL_RX",
        "_XelatexBib",
        "_aux_cite_keys",
        "_bbl_complete",
        "_bbl_decl_version",
        "_bbl_keys",
        "_bbl_stray_candidate",
        "_bbl_version_skewed",
        "_bibdata_resolvable",
        "_bcf_intact",
        "_has_bbl",
        "contextlib",
    ),
    "frame": (
        "_ENDDOC_MAX_DEPTH",
        "_ENDDOC_RX",
        "_ENDINPUT_DEF_RX",
        "_ENDINPUT_RX",
        "_INCLUDE_SRC_RX",
        "_checked_main",
        "_enddoc_scan",
        "_harvest",
        "_input_covers_enddoc",
        "_prepare_main",
        "Path",
        "compiled_dependencies",
        "os",
        "re",
        "visible_tex",
    ),
    "install": (
        "_XelatexInstall",
        "shutil",
        "tlmgr_search_cache_path",
    ),
    "main": (
        "CompRes",
        "DEFAULT_TIMEOUT",
        "ENV_TLNET",
        "MAX_PASSES",
        "XelatexEngine",
        "_ADAPTIVE_PASS_CAP",
        "_RERUN_HINT_RX",
        "_SHELL_ESCAPE_FLAGS",
        "_apply_sandbox",
        "_collect_compile_outputs",
        "_rc_to_signal",
        "_salvage_driver_fatal",
        "env_raw",
        "log_text_of",
        "parse_log",
    ),
    "probe": (
        "_PROBE_MEMO_MAX",
        "_XelatexProbe",
        "load_search_cache",
        "safe_is_file",
        "save_search_cache",
    ),
    "runenv": (
        "_OUTPUT_REKEY_PREFIXES",
        "_XelatexEnv",
        "_texmfdist",
        "child_env",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "DEFAULT_TIMEOUT",
    "ENV_TLNET",
    "MAX_PASSES",
    "_ADAPTIVE_PASS_CAP",
    "_AUX_CITE_RX",
    "_BBL_HEAD_BYTES",
    "_BBL_KEY_RX",
    "_BBL_TAIL_BYTES",
    "_BBL_TAIL_RX",
    "_BBL_VER_RX",
    "_BCF_MIN_BYTES",
    "_BCF_TAIL_BYTES",
    "_BCF_TAIL_RX",
    "_BIBDATA_RX",
    "_BIB_AUX_SCAN_MAX",
    "_BIB_TOOL_TIMEOUT_MAX",
    "_BLX_VER_MEMO",
    "_BLX_VER_RX",
    "_ENDDOC_MAX_DEPTH",
    "_ENDDOC_RX",
    "_ENDINPUT_DEF_RX",
    "_ENDINPUT_RX",
    "_INCLUDE_SRC_RX",
    "_OUTPUT_REKEY_PREFIXES",
    "_PROBE_MEMO_MAX",
    "_RERUN_HINT_RX",
    "_SHELL_ESCAPE_FLAGS",
    "CompRes",
    "Path",
    "XelatexEngine",
    "_XelatexBib",
    "_XelatexEnv",
    "_XelatexInstall",
    "_XelatexProbe",
    "_apply_sandbox",
    "_aux_cite_keys",
    "_bbl_complete",
    "_bbl_decl_version",
    "_bbl_keys",
    "_bbl_stray_candidate",
    "_bbl_version_skewed",
    "_bcf_intact",
    "_bibdata_resolvable",
    "_checked_main",
    "_collect_compile_outputs",
    "_enddoc_scan",
    "_harvest",
    "_has_bbl",
    "_input_covers_enddoc",
    "_prepare_main",
    "_rc_to_signal",
    "_salvage_driver_fatal",
    "_texmfdist",
    "child_env",
    "compiled_dependencies",
    "contextlib",
    "env_raw",
    "load_search_cache",
    "log_text_of",
    "os",
    "parse_log",
    "re",
    "safe_is_file",
    "save_search_cache",
    "shutil",
    "tlmgr_search_cache_path",
    "visible_tex",
]

log = logging.getLogger(__name__)

_eng = sys.modules.get("texlate.compile.engine")


def __getattr__(name: str) -> object:
    """平名惰性解析 → 孙叶属性。"""
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
    - ``__all__`` 逐名 ``getattr`` 可解——孙叶断链 (``_LEAF_EXPORTS``
      配名孙叶不提供) 与幽灵条 (既非孙叶名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部孙叶，只供测试调用，装载期不自检。
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
