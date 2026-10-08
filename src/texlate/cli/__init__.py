"""texlate 命令行入口（``cli.py`` → ``cli/`` 包拆分 facade）。

M0 集成面：``fetch``（取源钉版）/ ``parse``（半解析分块）/ ``run``（mock 端到端
——normalize → mock 翻译 → ctex 注入 → 编译 → 判定，驱动在 ``texlate.e2e``）。
``run --server`` 为瘦客户端形态（web-layer §6）：本地不跑管线，任务提交远端
server API、轮询快照到终态、拉取产物。

拆分后面守恒：``texlate.cli:app`` 入口与 ``cli.X`` 属性面逐名不变——命令组
出叶（fetch/parse/run/web/export/share/tools/version/doctor），瘦客户端与
共享底座各归 ``thin``/``_common`` 叶；monkeypatch 缝（``cli.Fetcher``/
``cli.find_tool``/``cli.find_spec``/``cli.mock_pipeline_run``/
``cli._export_translator``）经叶内 ``_cli.`` 调用期解析保留。

惰性门面（PEP 562，同 ``xlat``/``fixloop`` 形制）：``__all__`` 平名经
``__getattr__`` 映射回子模块/跨包源惰性解析——``import texlate.cli`` 不再
急切拉入 e2e/share/arxiv/latex.api/compile 全链（audit：``_cli.`` 缝名
与 ``cli.X`` 钉点均为调用期查名，无顶层消费；``import texlate.cli`` 从
133 个 texlate 模块降至 ~2）。``from texlate.cli import _output`` 类
子模块名走 ``import .X`` 兜底。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.util import find_spec

    from texlate import __version__  # noqa: F401
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import (
        AcquireResult,
        AcquireStatus,
        Fetcher,
        acquire_source,
        normalize_arxiv_id,
    )
    from texlate.compile import toolchain
    from texlate.compile.sandbox import find_tool
    from texlate.e2e import pipeline_run as mock_pipeline_run
    from texlate.latex.api import parse_file
    from texlate.share import (
        KEY_PART_FIELDS,
        ShareError,
        glossary_content_hash,
        pack_share,
        unpack_share,
    )
    from texlate.textutil import data_root, env_flag, env_raw, env_str

    from ._common import (  # noqa: F401
        _CLI_FILE,
        _CLI_PATH,
        _CTRL_CHARS_RE,
        _DEFAULT_CACHE,
        _CliPath,
        _is_dir,
        _is_file,
        _main,
        app,
    )
    from .channels import (
        channels_app,
        channels_list,
        channels_route,
        channels_test,
    )
    from .doctor import (  # noqa: F401
        _DOC_GATEWAY_TIMEOUT_S,
        _DOC_PROBE_TIMEOUT_S,
        _Check,
        _doc_babeldoc,
        _doc_channels,
        _doc_cjk_fonts,
        _doc_data_dir,
        _doc_engines,
        _doc_fc_list_zh,
        _doc_gateway,
        _doc_kpsewhich,
        _doc_pdftotext,
        _doc_python,
        _doc_run,
        _doc_settings_raw,
        _doc_tool_version,
        doctor,
    )
    from .export import (
        _export_translator,  # noqa: F401
        export,
    )
    from .fetch import _acquire, _echo_acquire, fetch  # noqa: F401
    from .parse import parse
    from .run import _populate_work_dir, _resolve_source, run  # noqa: F401
    from .service import (  # noqa: F401
        _probe_service,
        _ServiceStatus,
        service_app,
        service_restart,
        service_start,
        service_status,
        service_stop,
    )
    from .share import (  # noqa: F401
        _share_data_root,
        _share_db,
        _share_fields,
        _share_final_move,
        _share_glossary_hash,
        _share_out_is_file,
        _share_row,
        _share_task_dir,
        _share_verify_pipeline,
        _share_warn_no_pdf,
        share_app,
        share_pack,
        share_unpack,
    )
    from .thin import (  # noqa: F401
        _THIN_POLL_S,
        _THIN_TERMINAL,
        _thin_download,
        _thin_fetch_one,
        _thin_run,
        _thin_submit,
        _thin_wait,
    )
    from .tools import tools_app, tools_install_tectonic
    from .version import version
    from .web import _connect_url, _service_lock, web  # noqa: F401

#: 平名 → 源模块。``.x`` 相对 spec = 包内叶；绝对 spec = 跨包转口
#: （``cli.Fetcher``/``cli.find_tool``/``cli.data_root`` 等钉点面守恒——
#: eager 期 ``from texlate.X import`` 同款转口语义）。
_SUBMODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "._common": (
        "_CLI_FILE",
        "_CLI_PATH",
        "_CTRL_CHARS_RE",
        "_DEFAULT_CACHE",
        "_CliPath",
        "_is_dir",
        "_is_file",
        "_main",
        "app",
    ),
    ".channels": (
        "channels_app",
        "channels_list",
        "channels_route",
        "channels_test",
    ),
    ".doctor": (
        "_DOC_GATEWAY_TIMEOUT_S",
        "_DOC_PROBE_TIMEOUT_S",
        "_Check",
        "_doc_babeldoc",
        "_doc_channels",
        "_doc_cjk_fonts",
        "_doc_data_dir",
        "_doc_engines",
        "_doc_fc_list_zh",
        "_doc_gateway",
        "_doc_kpsewhich",
        "_doc_pdftotext",
        "_doc_python",
        "_doc_run",
        "_doc_settings_raw",
        "_doc_tool_version",
        "doctor",
    ),
    ".export": ("_export_translator", "export"),
    ".fetch": ("_acquire", "_echo_acquire", "fetch"),
    ".parse": ("parse",),
    ".run": ("_populate_work_dir", "_resolve_source", "run"),
    ".service": (
        "_ServiceStatus",
        "_probe_service",
        "service_app",
        "service_restart",
        "service_start",
        "service_status",
        "service_stop",
    ),
    ".share": (
        "_share_data_root",
        "_share_db",
        "_share_fields",
        "_share_final_move",
        "_share_glossary_hash",
        "_share_out_is_file",
        "_share_row",
        "_share_task_dir",
        "_share_verify_pipeline",
        "_share_warn_no_pdf",
        "share_app",
        "share_pack",
        "share_unpack",
    ),
    ".thin": (
        "_THIN_POLL_S",
        "_THIN_TERMINAL",
        "_thin_download",
        "_thin_fetch_one",
        "_thin_run",
        "_thin_submit",
        "_thin_wait",
    ),
    ".tools": ("tools_app", "tools_install_tectonic"),
    ".version": ("version",),
    ".web": ("_connect_url", "_service_lock", "web"),
    "texlate": ("__version__",),
    "texlate.arxiv.cache": ("SourceCache",),
    "texlate.arxiv.fetch": (
        "AcquireResult",
        "AcquireStatus",
        "Fetcher",
        "acquire_source",
        "normalize_arxiv_id",
    ),
    "texlate.compile.sandbox": ("find_tool",),
    "texlate.latex.api": ("parse_file",),
    "texlate.share": (
        "KEY_PART_FIELDS",
        "ShareError",
        "glossary_content_hash",
        "pack_share",
        "unpack_share",
    ),
    "texlate.textutil": ("data_root", "env_flag", "env_raw", "env_str"),
}

#: 平名 → (源模块，源属性)；属性 None = 取模块本体（``toolchain`` 旧语义
#: ``from texlate.compile import toolchain`` 绑的是模块对象）。
_LAZY: dict[str, tuple[str, str | None]] = {
    name: (mod, name) for mod, names in _SUBMODULE_EXPORTS.items() for name in names
}
_LAZY["find_spec"] = ("importlib.util", "find_spec")
_LAZY["toolchain"] = ("texlate.compile.toolchain", None)
_LAZY["mock_pipeline_run"] = ("texlate.e2e", "pipeline_run")

# 字面列表——ruff F822 静态点名要字面值；键集 = _LAZY 键集，新增导出两侧同步。
__all__ = [
    "KEY_PART_FIELDS",
    "AcquireResult",
    "AcquireStatus",
    "Fetcher",
    "ShareError",
    "SourceCache",
    "acquire_source",
    "app",
    "channels_app",
    "channels_list",
    "channels_route",
    "channels_test",
    "data_root",
    "doctor",
    "env_flag",
    "env_raw",
    "env_str",
    "export",
    "fetch",
    "find_spec",
    "find_tool",
    "glossary_content_hash",
    "mock_pipeline_run",
    "normalize_arxiv_id",
    "pack_share",
    "parse",
    "parse_file",
    "run",
    "service_app",
    "service_restart",
    "service_start",
    "service_status",
    "service_stop",
    "share_app",
    "share_pack",
    "share_unpack",
    "toolchain",
    "tools_app",
    "tools_install_tectonic",
    "unpack_share",
    "version",
    "web",
]


#: typer 命令叶——``@app.command()``/``add_typer`` 注册是叶 import 副作用；
#: ``cli.app`` 首访时装齐才出完整命令面（``import texlate.cli`` 保 ~3 模块）。
_COMMAND_LEAVES: tuple[str, ...] = (
    "fetch",
    "parse",
    "run",
    "web",
    "service",
    "export",
    "share",
    "tools",
    "version",
    "doctor",
    "channels",
)


def __getattr__(name: str) -> object:
    """平名惰性解析 → 源模块属性（None = 模块本体）；子模块名走 ``import .X`` 兜底。"""
    if name == "app":
        for leaf in _COMMAND_LEAVES:
            importlib.import_module(f".{leaf}", __name__)
        value = importlib.import_module("._common", __name__).app
        globals()["app"] = value
        return value
    hit = _LAZY.get(name)
    if hit is not None:
        spec, attr = hit
        mod = importlib.import_module(spec, __name__)
        value = mod if attr is None else getattr(mod, attr)
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
