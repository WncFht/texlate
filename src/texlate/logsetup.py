r"""日志配置单源——CLI/server 共用：``texlate`` logger handler、级别/env、secret scrub。

背景：全仓 ~30 个模块 ``log = logging.getLogger(__name__)`` 但无 handler
配置——INFO/DEBUG 全丢、WARNING+ 走 lastResort 裸打。本模块是唯一的
装配点：handler 只挂 ``texlate`` 顶层 logger（非 root——不劫持
uvicorn/httpx 三方输出），``propagate`` 保持 True 让 pytest caplog
（root handler）照常采集；texlate logger 有 handler 后 lastResort 不再
触发（callHandlers found>0），无双打。

级别三来源：显式参 > ``TEXLATE_LOG`` env（``debug|info|warning|error|off``
归一小写）> 调用方 default。文件路径三态经 ``_file_from_env``：
``TEXLATE_LOG_FILE`` 未设/空 → 调用方 default 形参；``off`` → 关文件；
其余 → 路径。脱敏面本地自足不反引 xlat——本模块是日志底座
（``cli/run.py``/server ``__main__`` 顶层经），引 ``xlat.client`` 会拖入
httpx/asyncio/ssl 全栈，纯 ``re`` 小件就地实现：``SECRET_LOG_PATTERNS``
单表全覆盖 ``xlat.client._SECRET_PATTERNS``（sk- 宽松形收编基表两档），
``scrub`` 与 ``RedactFilter`` 共用同一迭代面不再各养可漂移的
``key.replace + rx.sub``；待提升 ``textutil`` 单源后 client 与本模块
同引一处。``RedactFilter`` 类体从 ``server/logredact.py`` 下沉本层，
原址 re-export 保名字面。
"""

from __future__ import annotations

import contextlib
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

from texlate.textutil import env_opt, env_str

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "ENV_LOG",
    "ENV_LOG_FILE",
    "SECRET_LOG_PATTERNS",
    "RedactFilter",
    "configure_logging",
    "configure_server_logging",
    "level_from_flags",
    "scrub",
]

#: ``TEXLATE_LOG`` env——级别词（debug/info/warning/error/off）。
ENV_LOG = "TEXLATE_LOG"
#: ``TEXLATE_LOG_FILE`` env——文件路径 / ``off`` 关文件；未设走调用方默认。
ENV_LOG_FILE = "TEXLATE_LOG_FILE"

#: 级别词 → logging 常量（``off`` 单列——CRITICAL+1 全闸）。
_LEVEL_NAMES: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: ``configure_logging`` 自装 handler 的认领证——幂等重入只摘自己装的件，
#: caplog/外部挂进 texlate logger 的 handler 不动。
_MANAGED_ATTR = "_texlate_managed"

#: 轮转文件上限：4MB×3 份封顶 12MB（postmortem 现场够用且不摊磁盘）。
_LOG_FILE_MAX_BYTES = 4 * 1024 * 1024
_LOG_FILE_BACKUPS = 3

#: 日志面 secret 形态表——``xlat.client._SECRET_PATTERNS`` 基表的全覆盖
#: 超集：Bearer/AIza/api_key= 三行同形；``sk-`` 放宽（``.`` 入类 + ``{4,}``
#: 下限）收编基表 ``sk-{8,}``/``sk-ant-{4,}`` 两档与旧表 ``sk-ant-.`` 冗行
#: （窄形先跑会把 ``sk-…….`` 截成 ``***.尾`` 留残，单宽行无此坑）；
#: ``key-`` 宽松形为日志面独有。纯 ``re`` 小件就地单表——底座层不反引
#: ``xlat.client``（拖 httpx/asyncio/ssl 全栈），待提升 ``textutil`` 单源。
#: ``scrub``/``RedactFilter._scrub`` 共用同一份迭代面（server
#: ``logredact._KEY_PATTERNS`` 名字面同源）。
SECRET_LOG_PATTERNS = [
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9._-]{4,}"),
    re.compile(r"key-[A-Za-z0-9._-]{4,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"(?:api[_-]?key|x-api-key|token)[=:]\s*[\"']?\S+", re.IGNORECASE),
]


def scrub(text: str, api_key: str = "") -> str:
    """显式 key 值 + 已知 secret 形态抹除（§4.2 第一道防线）。

    regex 道单实现——``RedactFilter._scrub`` 抹完动态 key 后同走本函数。
    """
    out = text
    if api_key:
        out = out.replace(api_key, "***")
    for rx in SECRET_LOG_PATTERNS:
        out = rx.sub("***", out)
    return out


class RedactFilter(logging.Filter):
    """日志脱敏（§4.2 第二道防线，防三方库把请求体打进 traceback）。

    ``key_provider`` 返回当前该抹掉的 key 值集合（settings key +
    运行中的 header key）——动态取，key 轮换即生效；None 时只抹正则
    形态。filter 绝不能炸掉日志调用——provider 异常吞掉按空集处理。
    """

    def __init__(self, key_provider: object = None) -> None:
        """key_provider: ``() -> Iterable[str]``，None 时只抹正则形态。"""
        super().__init__()
        self._key_provider = key_provider

    def _keys(self) -> list[str]:
        if callable(self._key_provider):
            try:
                return [k for k in self._key_provider() if k]
            except Exception:  # noqa: BLE001 -- 过滤器绝不能炸掉日志调用
                return []
        return []

    def _scrub(self, text: str) -> str:
        out = text
        for key in self._keys():
            out = out.replace(key, "***")
        return scrub(out)

    def filter(self, record: logging.LogRecord) -> bool:
        """命中 secret 形态时改写 msg 并清空 args（避免二次格式化还原）。

        ``exc_info``/``stack_info`` 不走 ``msg``——Formatter 另路渲染；
        含 key 的异常文本（三方库把请求体打进异常）须先行 format 再
        洗，写回 ``record.exc_text`` 供 Formatter 直接用缓存值。
        """
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 -- 同上，filter 不炸
            return True
        clean = self._scrub(msg)
        if clean != msg:
            record.msg = clean
            record.args = ()
        if record.exc_info:
            with contextlib.suppress(Exception):
                record.exc_text = self._scrub(
                    logging.Formatter().formatException(record.exc_info)
                )
        if record.stack_info:
            record.stack_info = self._scrub(record.stack_info)
        return True


def _resolve_level(level: str | int | None, default: int) -> int:
    """级别三来源：显式参 > ``TEXLATE_LOG`` env > ``default``。

    非法词/未设 env 落 default；``off``/``none`` 返 ``CRITICAL+1``
    全闸（连 CRITICAL 都不放——比 disable() 可逆，重配即恢复）。
    """
    raw: str | int | None = level
    if raw is None:
        env = env_str(ENV_LOG)
        raw = env or default
    if isinstance(raw, int):
        return raw
    name = str(raw).strip().lower()
    if name in ("off", "none"):
        return logging.CRITICAL + 1
    return _LEVEL_NAMES.get(name, default)


def level_from_flags(verbose: int, quiet: int) -> int:
    """CLI ``-v/-q`` count 旗标 → 级别：-v INFO、-vv+ DEBUG、-q ERROR、-qq CRITICAL。"""
    if quiet >= 2:  # noqa: PLR2004 -- 两档计数即语义，常量化反而绕
        return logging.CRITICAL
    if quiet:
        return logging.ERROR
    if verbose >= 2:  # noqa: PLR2004 -- 同上
        return logging.DEBUG
    if verbose:
        return logging.INFO
    return logging.WARNING


def _file_from_env(default: Path | None) -> Path | None:
    """``TEXLATE_LOG_FILE`` → 文件路径三态：未设/空 → ``default``；``off`` → None；其余 → 路径。"""
    raw = env_opt(ENV_LOG_FILE)
    if raw is None or not raw:
        return default
    if raw.lower() == "off":
        return None
    return Path(raw).expanduser()


def configure_logging(
    level: str | int | None = None,
    *,
    default: int = logging.WARNING,
    file: Path | str | None = None,
    console: Console | None = None,
    key_provider: Callable[[], Iterable[str]] | None = None,
) -> logging.Logger:
    """``texlate`` 顶层 logger 装 handler（幂等——重入先摘本函数装的件）。

    - stderr：``RichHandler``（markup=False 防 ``[`` 误解析、
      ``rich_tracebacks=True``、``show_path=False``），``console`` 可注入
      共享实例——RichHandler 与 Progress/Live 必须同 Console，否则两个
      Console 写同一 stderr 刷新区错乱；
    - ``file``：``RotatingFileHandler`` DEBUG 级（文件是 postmortem 现场，
      比 stderr 活口收得更全）；父目录 mkdir 失败/不可写降级仅 stderr +
      warning，不炸调用方；
    - 两 handler 各挂 :class:`RedactFilter`（``key_provider`` 动态取 key）。
    """
    lg = logging.getLogger("texlate")
    lvl = _resolve_level(level, default)
    lg.setLevel(lvl)
    for h in [h for h in lg.handlers if getattr(h, _MANAGED_ATTR, False)]:
        lg.removeHandler(h)
        h.close()
    if lvl > logging.CRITICAL:
        return lg

    filt = RedactFilter(key_provider)
    sh = RichHandler(
        console=console or Console(stderr=True),
        level=lvl,
        markup=False,
        rich_tracebacks=True,
        show_path=False,
    )
    sh.setFormatter(logging.Formatter("%(message)s"))
    setattr(sh, _MANAGED_ATTR, True)
    sh.addFilter(filt)
    lg.addHandler(sh)

    if file is not None:
        fp = Path(file).expanduser()
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                fp,
                maxBytes=_LOG_FILE_MAX_BYTES,
                backupCount=_LOG_FILE_BACKUPS,
                encoding="utf-8",
            )
        except OSError as e:
            lg.warning("日志文件不可用 %s: %s——仅 stderr", fp, e)
        else:
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            setattr(fh, _MANAGED_ATTR, True)
            fh.addFilter(filt)
            lg.addHandler(fh)
    return lg


def configure_server_logging(data_dir: Path) -> Path | None:
    """Server 入口日志装配：stderr（default INFO）+ ``<data_dir>/logs/texlate.log`` 轮转文件。

    ``TEXLATE_LOG`` 调级别；``TEXLATE_LOG_FILE=off`` 关文件、``=path``
    改路径。调用点在 ``uvicorn.run`` 前——uvicorn dictConfig
    ``disable_existing_loggers=False`` 不拆本 handler；lifespan
    ``install_log_scrub`` 会把 RedactFilter 补挂到 texlate logger 及其
    handler（文件行自动 scrub）。返回实际文件路径（关/不可用为 None）。
    """
    file = _file_from_env(data_dir / "logs" / "texlate.log")
    configure_logging(default=logging.INFO, file=file)
    return file
