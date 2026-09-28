r"""引擎层：Engine 协议 + xelatex/tectonic 实现 + 静态路由表（docs/spec/compile.md）。

- Engine 协议（§4.1）：`detect/compile/probe_file/install_file/rebuild_fontmaps/
  filemap/parse_log` + `caps` 能力集——fixloop 按 caps 降级（tectonic 无
  tlmgr/kpsewhich/updmap，走 ctan_fetch 原语，见 §5.3）。
- 命令行（§4.1）：xelatex `-no-shell-escape -interaction=nonstopmode
  [-halt-on-error] -file-line-error -recorder` ≤2 pass；tectonic `-X compile
  --untrusted -Z continue-on-errors --keep-logs --keep-intermediates
  --makefile-rules`（continue-on-errors 对齐 nonstopmode 语义——tectonic
  默认 halt-on-error，engine-matrix §0 已实证）。
- pass 闸（B14 fix#7/C3）：``passes=None``（缺省）= 自适应——pass-1 后按
  log rerun 提示族（``_RERUN_HINT_RX``）决定续跑，无提示即收；显式 int
  = 无条件 ≤N 遍（fixloop 收敛终编靠它跑满）。两口径失败路径同闸：
  错误退出（rc>0 非信号）/exec 失败/无 pdf/超时即停——已炸编译不空烧；
  信号死（负 rc）保留续趟重试通道（2211.13013 实证可救）。
- 静态路由（§4.2）：`route_project` 编译前决策；失败集互补实测联合 clean
  9/12（engine-matrix §0）。
- OS 沙箱（§4.4）在 ``sandbox.py``（darwin ``sandbox-exec`` / linux ``bwrap``
  / 缺席退 env 白名单，``_apply_sandbox`` 分发，实落形态记
  ``CompRes.sandbox_mode``，``TEXLATE_NO_BWRAP=1`` 关停）；log 解析（§2.3）
  与错误分类学适配在 ``loginfo.py``；依赖记录（.fls/.mk→权威输入集）在
  ``deps.py``——本模块持引擎实现与路由，公共面经 import 回引保持
  ``from texlate.compile.engine import X`` 不破。

``engine.py`` 拆分包：本 facade 全量回引公开面与测试 patch 缝
（``run_process``/``find_tool``/``tectonic_version``/``ensure_tectonic``
钉在本模块名上，叶内经 ``import texlate.compile.engine as _eng`` 运行期
回查，worker ``_w.`` 同款——缝名单源 ``texlate.compile.seams``，本包
eager 回引为叶侧确定性锚；``seams.X`` patch 只拦 seams 路由消费点、
``engine.X`` patch 拦叶消费点，两平面不互通）；实现按边界出叶——
``_base``（CompRes/Engine 协议/共享小件）、``_xelatex``、``_tectonic``、
``_route``（RouteDecision/签名集/route_project/engine_for）、
``_cache``（tlmgr 搜索落盘缓存）。
"""

from __future__ import annotations

import logging

from texlate.compile.deps import compiled_dependencies
from texlate.compile.loginfo import (
    WARNING_RED_LINES,  # WARNING_RED_LINES/classify_error 门面回引（judge/test_redlines 经本模块取）
    LogInfo,
    classify_error,
    parse_log,
)
from texlate.compile.mask import visible_tex
from texlate.compile.sandbox import (
    _apply_sandbox,
    _rc_to_signal,
    _texmfdist,
    child_env,
)

# 测试 patch 缝（叶内经 ``_eng.`` 运行期回查，worker ``_w.`` 同款）——
# 名单单源 ``texlate.compile.seams``；本包 eager 回引是 ``_eng.`` 消费侧
# 确定性锚：``engine.X`` patch 拦叶消费点，``seams.X`` patch 拦 seams
# 路由消费点，两平面不互通。
from texlate.compile.seams import (
    ensure_tectonic,
    find_tool,
    run_process,
    tectonic_version,
)
from texlate.textutil import (
    DOCSTYLE_RX,
    decode_tex,
    env_opt,
    env_raw,
    safe_is_file,
    safe_resolve,
)

from ._base import (
    DEFAULT_TIMEOUT,
    CompRes,
    Engine,
    _checked_main,
    _collect_compile_outputs,
    _driver_fatal,
    _salvage_driver_fatal,
)
from ._cache import load_search_cache, save_search_cache, tlmgr_search_cache_path
from ._route import (
    _BITMAP_FONT_PKGS,
    _MINTED_FROZEN_RE,
    _MINTED_PKG_RE,
    _PSFILE_SPECIAL_RE,
    _PSTRICKS_RE,
    BITMAP_FONT_PKG_NAMES,
    ENGINE_NAMES,
    PST_PKG_PREFIXES,
    PSTRICKS_PKG_NAMES,
    RouteDecision,
    _apply_route_sigs,
    _route_sigs,
    _RouteSigs,
    engine_for,
    route_project,
)
from ._tectonic import (
    _TECTONIC_ATTEMPTS,
    _TECTONIC_BUNDLE_URL_MIN,
    _TECTONIC_FLAG_MAP,
    _TECTONIC_RETRY_TIMEOUT,
    _TECTONIC_Z_OK,
    TECTONIC_BUNDLE_PIN,
    TectonicEngine,
    _mirror_source_dirs,
)
from ._xelatex import (
    _ADAPTIVE_PASS_CAP,
    _OUTPUT_REKEY_PREFIXES,
    _PROBE_MEMO_MAX,
    _RERUN_HINT_RX,
    _SHELL_ESCAPE_FLAGS,
    MAX_PASSES,
    XelatexEngine,
)

log = logging.getLogger(__name__)

__all__ = [
    "BITMAP_FONT_PKG_NAMES",
    "DEFAULT_TIMEOUT",
    "DOCSTYLE_RX",
    "ENGINE_NAMES",
    "MAX_PASSES",
    "PSTRICKS_PKG_NAMES",
    "PST_PKG_PREFIXES",
    "TECTONIC_BUNDLE_PIN",
    "WARNING_RED_LINES",
    "_ADAPTIVE_PASS_CAP",
    "_BITMAP_FONT_PKGS",
    "_MINTED_FROZEN_RE",
    "_MINTED_PKG_RE",
    "_OUTPUT_REKEY_PREFIXES",
    "_PROBE_MEMO_MAX",
    "_PSFILE_SPECIAL_RE",
    "_PSTRICKS_RE",
    "_RERUN_HINT_RX",
    "_SHELL_ESCAPE_FLAGS",
    "_TECTONIC_ATTEMPTS",
    "_TECTONIC_BUNDLE_URL_MIN",
    "_TECTONIC_FLAG_MAP",
    "_TECTONIC_RETRY_TIMEOUT",
    "_TECTONIC_Z_OK",
    "CompRes",
    "Engine",
    "LogInfo",
    "RouteDecision",
    "TectonicEngine",
    "XelatexEngine",
    "_RouteSigs",
    "_apply_route_sigs",
    "_apply_sandbox",
    "_checked_main",
    "_collect_compile_outputs",
    "_driver_fatal",
    "_mirror_source_dirs",
    "_rc_to_signal",
    "_route_sigs",
    "_salvage_driver_fatal",
    "_texmfdist",
    "child_env",
    "classify_error",
    "compiled_dependencies",
    "decode_tex",
    "engine_for",
    "ensure_tectonic",
    "env_opt",
    "env_raw",
    "find_tool",
    "load_search_cache",
    "parse_log",
    "route_project",
    "run_process",
    "safe_is_file",
    "safe_resolve",
    "save_search_cache",
    "tectonic_version",
    "tlmgr_search_cache_path",
    "visible_tex",
]
