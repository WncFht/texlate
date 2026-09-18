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
"""

from __future__ import annotations

from importlib.util import find_spec

from texlate import __version__  # noqa: F401
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import (  # noqa: F401 -- _valid_id 私有转口
    AcquireResult,
    AcquireStatus,
    Fetcher,
    _valid_id,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.cli._common import app
from texlate.compile import toolchain
from texlate.compile.sandbox import find_tool
from texlate.e2e import mock_pipeline_run
from texlate.latex.api import parse_file
from texlate.share import (
    KEY_PART_FIELDS,
    ShareError,
    glossary_content_hash,
    pack_share,
    unpack_share,
)
from texlate.textutil import data_root, env_flag, env_raw, env_str

# 私有转口——tests/ 钉点经 ``from texlate.cli import _x`` 与 ``cli._x``
# 属性面消费（各带 noqa: SLF001），拆分后口径不变。
from ._common import (  # noqa: F401
    _CLI_FILE,
    _CLI_PATH,
    _CTRL_CHARS_RE,
    _DEFAULT_CACHE,
    _CliPath,
    _is_dir,
    _is_file,
    _main,
)
from .doctor import (  # noqa: F401
    _DOC_GATEWAY_TIMEOUT_S,
    _DOC_PROBE_TIMEOUT_S,
    _Check,
    _doc_babeldoc,
    _doc_cjk_fonts,
    _doc_data_dir,
    _doc_engines,
    _doc_fc_list_zh,
    _doc_gateway,
    _doc_kpsewhich,
    _doc_pdftotext,
    _doc_python,
    _doc_run,
    _doc_server_extra,
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

__all__ = [
    "KEY_PART_FIELDS",
    "AcquireResult",
    "AcquireStatus",
    "Fetcher",
    "ShareError",
    "SourceCache",
    "acquire_source",
    "app",
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
