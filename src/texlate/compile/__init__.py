"""编译层：Engine 协议 / ctex 注入 / normalize / clean 判定 / 沙箱（规格 docs/08 §3–4）。

- `mask`：visible_tex 遮蔽视图（所有手术的定位地基）
- `normalize`：pdfTeX→XeTeX 无条件手术 12 项
- `latex209`：LaTeX 2.09 ``documentstyle`` → LaTeX2e 受限升级器（compat 模式唯一注入通路）
- `inject`：ctex/xeCJK 中文注入 + FLOAT_SIZING/TABLE_FITTING
- `cjkmap`：GB1→UCS2 ToUnicode CMap 注入（zh.pdf 复制/检索修复）
- `engine`：Engine Protocol + xelatex/tectonic + 静态路由 + compiled_dependencies（实现在 deps.py 经 facade 回引）
- `deps`：编译器自述输入集解析（.fls INPUT / dependencies.mk——翻译文件集权威）
- `loginfo`：.log → LogInfo 语义层 + 错误分类学适配（taxonomy 单源在 fixloop/rules/）
- `probe`：声明依赖静态探针（target_probe）+ 权威输入集差分（deps_diff）
- `judge`：clean/partial/fail 判定三件套 + 中文渲染检查
- `sandbox`：env 白名单 + sandbox-exec + killpg
- `toolchain`：tectonic 五平台 sha256 钉死分发 + 托管件自动安装
"""

from texlate.textutil import decode_tex

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
    CTEX_LINE,
    XECJK_BLOCK,
    InjectRejectError,
    classify_no_main,
    find_docclass_end,
    find_main_tex,
    inject_cjk,
    inject_float_sizing,
    inject_preamble,
    inject_table_fitting,
    prepare_chinese,
)
from .judge import (
    CLEAN_ERR_MAX,
    Verdict,
    count_missing_chars,
    judge,
    pdf_cjk_chars,
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
    normalize_engine,
    normalize_project,
    source_path_violations,
)
from .probe import DepProbe, DepsDiff, ProbeReport, dep_seen, deps_diff, target_probe
from .sandbox import child_env, find_tool, run_process, sandbox_wrap
from .toolchain import ensure_tectonic, install_tectonic, resolve_tool

__all__ = [
    "CLEAN_ERR_MAX",
    "CTEX_LINE",
    "PIXEL_COMPATIBILITY",
    "TECTONIC_FONT_COMPATIBILITY",
    "TEX_SOURCE_SUFFIXES",
    "XECJK_BLOCK",
    "XETEX_COMPATIBILITY",
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
    "inject_preamble",
    "inject_table_fitting",
    "install_tectonic",
    "judge",
    "normalize_engine",
    "normalize_project",
    "parse_log",
    "pdf_cjk_chars",
    "prepare_chinese",
    "resolve_tool",
    "route_project",
    "run_process",
    "sandbox_wrap",
    "source_path_violations",
    "target_probe",
    "visible_tex",
    "without_comments",
]
