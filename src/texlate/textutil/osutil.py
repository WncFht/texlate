r"""os 边界小件 —— env 名表/读取与路径防御的各层共用单源。

``TEXLATE_*`` env 的单一事实源：**名表**逐名登记（新 env 先登记再取，
叶子模块历史散名统一别名本表）；**读取**侧布尔旗标统一 ``1/true/yes/on``
真值表（strip+lower 后判定）；字符串选择器统一 strip+lower 归一、值
敏感场 strip-only；浮点参数统一解析失败/nan/inf 回默认（范围裁剪归
调用方）；数据根统一 ``TEXLATE_DATA_DIR`` > ``~/.texlate``（只定位不
mkdir，副作用归调用方）。``safe_resolve``/``safe_is_file`` 是
``Path`` 防御层——上游恶意/病态名触发的 ``OSError``/``RuntimeError``/
``ValueError`` 一律收敛为缺席语义；``safe_rel`` 是纯词法级相对路径
守卫（``..``/绝对/NUL 拒收，不触盘）。
"""

from __future__ import annotations

import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------- 路径防御
def safe_resolve(path: Path) -> Path | None:
    r"""``Path.resolve()`` 防御层：symlink loop/NUL/ENAMETOOLONG → ``None``。

    不可解析按不存在处理——上游恶意/病态名（``\\input`` 巨参、LLM patch
    ``p.file``、log 解析出的文件名）触发的 ``OSError``/``RuntimeError``/
    ``ValueError`` 一律收敛为缺席语义。
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _safe_pred(path: Path, op: Callable[[Path], bool]) -> bool:
    r"""``Path`` 谓词防御层单源：NUL ``ValueError`` + 非豁免 ``OSError`` → False。

    pathlib 自吞 ``OSError``，但内嵌 NUL 字节的路径抛 ``ValueError`` 不豁免——
    攻击者可控名（``\\includegraphics`` 参数、fixloop 供给的 fname）直达即崩。
    """
    try:
        return op(path)
    except (OSError, ValueError):
        return False


def safe_is_file(path: Path) -> bool:
    r"""``Path.is_file()`` 防御层：``_safe_pred`` 同口径——NUL ``ValueError``/``OSError`` → False。"""
    return _safe_pred(path, Path.is_file)


def safe_is_dir(path: Path) -> bool:
    r"""``Path.is_dir()`` 防御层：``_safe_pred`` 同口径——NUL ``ValueError``/``OSError`` → False。"""
    return _safe_pred(path, Path.is_dir)


def safe_rel(name: str) -> PurePosixPath | None:
    """``name`` → ``PurePosixPath``; 空名/绝对路径/``..`` 段/NUL → ``None``。

    词法级路径守卫（不做存在性/解析）：fixloop 各注入/归位 builtin 统一
    的 payload 拒收口——非相对安全名一律 decline，绝不把 ``../x``/``/etc/x``
    写进 wdir。
    """
    rel = PurePosixPath(name)
    if not name or rel.is_absolute() or ".." in rel.parts or "\x00" in name:
        return None
    return rel


# ------------------------------------------------------------------ env 名表
# ``TEXLATE_*`` env **名**的单一事实源——包内逐名登记（bench/tests 私名不入
# 表）；新 env 先在此登记再取，doctor/文档的 env 面即本表。叶子模块历史
# 散名（``repair.ENV_NO_FIXLOOP``/``repair_l2.ENV_*``/``e2e.ENV_AUTO_GLOSSARY``/
# ``pipecore.ENV_FRONT_MATTER``/``logsetup.ENV_LOG*``/``staticfiles.SPA_DIR_ENV``/
# ``xlat.client.ENV_STREAM_FALLBACK``）统一别名本表常量，消费侧一律
# ``env_flag(ENV_X, ...)``。

#: 网关/API key——provider 兜底名表 ``PROVIDER_KEY_ENV`` 前的直读名。
ENV_API_KEY: Final = "TEXLATE_API_KEY"
#: e2e 逐篇 LLM 术语抽取臂开关（默认关）。
ENV_AUTO_GLOSSARY: Final = "TEXLATE_AUTO_GLOSSARY"
#: babeldoc 整单超时秒数（``env_float``）。
ENV_BABELDOC_TIMEOUT: Final = "TEXLATE_BABELDOC_TIMEOUT"
#: 网关 base URL（值敏感场）。
ENV_BASE_URL: Final = "TEXLATE_BASE_URL"
#: ctan 缓存根——``$TEXLATE_CACHE`` > ``data_root()/cache``。
ENV_CACHE: Final = "TEXLATE_CACHE"
#: 缓存根——``TEXLATE_CACHE_DIR`` > ``$XDG_CACHE_HOME/texlate`` >
#: ``~/.cache/texlate``（``ENV_CACHE`` 已占 ctan filemap 叶不混用）。
ENV_CACHE_DIR: Final = "TEXLATE_CACHE_DIR"
#: server 缓存粒度：``shared``（默认）| ``per_key``。
ENV_CACHE_SCOPE: Final = "TEXLATE_CACHE_SCOPE"
#: 编译超时秒数——env > settings.json ``compile_timeout`` > 240。
ENV_COMPILE_TIMEOUT: Final = "TEXLATE_COMPILE_TIMEOUT"
#: 数据根——``TEXLATE_DATA_DIR`` > ``~/.texlate``（只定位不 mkdir）。
ENV_DATA_DIR: Final = "TEXLATE_DATA_DIR"
#: 译文方言选择器（值敏感场）。
ENV_DIALECT: Final = "TEXLATE_DIALECT"
#: L2 unknown-env LLM 判定臂开关（默认关）。
ENV_ENV_JUDGE: Final = "TEXLATE_ENV_JUDGE"
#: fixloop escalate LLM 钩——e2e 侧 opt-in，server 侧默认开。
ENV_FIXLOOP_LLM: Final = "TEXLATE_FIXLOOP_LLM"
#: preamble 前置发射集逗号清单（缺省 ``abstract,title``）。
ENV_FRONT_MATTER: Final = "TEXLATE_FRONT_MATTER"
#: gateway provider 的 key 兜底名（``TEXLATE_API_KEY`` 空时按 host 读此）。
ENV_GATEWAY_KEY: Final = "TEXLATE_GATEWAY_KEY"
#: 日志级别词——``debug|info|warning|error|off``。
ENV_LOG: Final = "TEXLATE_LOG"
#: 日志文件路径 / ``off`` 关文件（``env_opt`` 三态：未设走调用方默认）。
ENV_LOG_FILE: Final = "TEXLATE_LOG_FILE"
#: server 部署形态——``local``（默认）| ``server``。
ENV_MODE: Final = "TEXLATE_MODE"
#: 模型名（值敏感场）。
ENV_MODEL: Final = "TEXLATE_MODEL"
#: settings save 期模型探活闸（默认开，非真值显式关——离线/CI 兜底）。
ENV_MODEL_PROBE: Final = "TEXLATE_MODEL_PROBE"
#: bwrap 沙盒显式关停（坏件逃生门）。
ENV_NO_BWRAP: Final = "TEXLATE_NO_BWRAP"
#: 托管件自动下载关——``CI`` 真值默认关，显式 ``=0`` 可强制开。
ENV_NO_DOWNLOAD: Final = "TEXLATE_NO_DOWNLOAD"
#: fixloop 关（缺省皆开——``NO_*`` 族取反喂入）。
ENV_NO_FIXLOOP: Final = "TEXLATE_NO_FIXLOOP"
#: L2 回灌关（缺省皆开，同 ``NO_*`` 族口径）。
ENV_NO_L2: Final = "TEXLATE_NO_L2"
#: zh.pdf seq marked-content 注锚关（缺省开——``options.seq_marks`` 同键）。
ENV_NO_SEQ_MARKS: Final = "TEXLATE_NO_SEQ_MARKS"
#: node 可执行路径（validate TS worker；缺省 ``shutil.which("node")``）。
ENV_NODE: Final = "TEXLATE_NODE"
#: 离线模式——只用本地缓存、零网络请求（``--offline`` 等效）。
ENV_OFFLINE: Final = "TEXLATE_OFFLINE"
#: 共享包发布目录——``TEXLATE_SHARE_DIR`` > ``<root>/share``。
ENV_SHARE_DIR: Final = "TEXLATE_SHARE_DIR"
#: SPA 产物目录——``TEXLATE_SPA_DIR`` > 包内 ``static/``。
ENV_SPA_DIR: Final = "TEXLATE_SPA_DIR"
#: ``chat`` 流式兜底臂开关（默认关；``ChatClient(stream_fallback=)`` 显式值优先）。
ENV_STREAM_FALLBACK: Final = "TEXLATE_STREAM_FALLBACK"
#: tectonic bundle 覆盖（``env_opt``——set-empty 有独立语义：引擎自带默认）。
ENV_TEX_BUNDLE: Final = "TEXLATE_TEX_BUNDLE"
#: tlmgr 缓存目录。
ENV_TLMGR_CACHE: Final = "TEXLATE_TLMGR_CACHE"
#: tlmgr 仓库 URL（xelatex 拉取共用）。
ENV_TLNET: Final = "TEXLATE_TLNET"
#: 翻译臂白名单——``mock|gateway``（缺省自动）。
ENV_TRANSLATOR: Final = "TEXLATE_TRANSLATOR"
#: TS worker 的 node_modules 路径（开发态指现成依赖树）。
ENV_TS_NODE_PATH: Final = "TEXLATE_TS_NODE_PATH"
#: TS worker 脚本路径。
ENV_TS_WORKER: Final = "TEXLATE_TS_WORKER"


# ------------------------------------------------------------------ env 读取
# ``TEXLATE_*`` env 读取的单一事实源——布尔旗标统一 ``1/true/yes/on`` 真值表
# （strip+lower 后判定）；字符串选择器统一 strip+lower 归一；浮点参数统一
# 解析失败/nan/inf 回默认（范围裁剪归调用方）；数据根统一
# ``TEXLATE_DATA_DIR`` > ``~/.texlate``（只定位不 mkdir，副作用归调用方）。
_TRUE_WORDS: Final = frozenset({"1", "true", "yes", "on"})


def env_flag(name: str, *, default: bool) -> bool:
    """读布尔 env：``1/true/yes/on``（strip+lower 后）为真；未设置取 ``default``。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_WORDS


def env_switch(name: str, *, explicit: bool | None, default: bool) -> bool:
    """三态开关归一：显式参数优先，``None`` 才读 ``env_flag``。

    env 仍在调用时读取——``monkeypatch.setenv`` 缝不受影响（``e2e`` 同形
    本地件的沉淀单源）。
    """
    return explicit if explicit is not None else env_flag(name, default=default)


def env_float(name: str, default: float) -> float:
    """读浮点 env：strip 后 ``float()`` 解析；未设置/解析失败/nan/inf 一律回 ``default``。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        v = float(raw.strip())
    except ValueError:
        return default
    return v if math.isfinite(v) else default


def env_str(name: str) -> str:
    """读字符串 env：strip+lower 归一返回；未设置返 ``""``（选择器类旗标同口径）。"""
    return os.environ.get(name, "").strip().lower()


def env_raw(name: str) -> str:
    """读字符串 env：strip 归一但**不** lower；未设置返 ``""``。

    路径/URL/model/key 等值敏感场用（选择器类旗标用 ``env_str``）。set-empty
    与未设置同归 ``""``——需要区分两者时用 ``env_opt``。
    """
    return os.environ.get(name, "").strip()


def env_opt(name: str) -> str | None:
    """读字符串 env：未设置 → ``None``；已设置 → strip 后原样（空串保留）。

    「置空串」带独立语义的场用（如 ``TEXLATE_TEX_BUNDLE=""`` 表引擎自带
    默认 bundle）——``env_raw`` 会把 set-empty 与未设置混同。
    """
    raw = os.environ.get(name)
    return raw.strip() if raw is not None else None


def translator_mode() -> str:
    """``TEXLATE_TRANSLATOR`` 归一读取：``env_str`` 口径，未设/置空 → ``""``。

    只归一不裁决——``TRANSLATOR_MODES`` 白名单的处置归消费侧
    （``cli.export`` 未知值 exit 2 显式拒；server 三读点对未知值**静默按
    auto 回落**——两侧 typo 语义不同口径、统一裁决待定）。
    """
    return env_str(ENV_TRANSLATOR)


def data_root() -> Path:
    """数据根：``TEXLATE_DATA_DIR`` > ``~/.texlate``——只定位不 mkdir。"""
    raw = env_raw(ENV_DATA_DIR)
    return Path(raw).expanduser() if raw else Path.home() / ".texlate"


def set_data_dir(path: Path) -> None:
    """``--data-dir`` → ``TEXLATE_DATA_DIR`` env 写（``data_root`` 读侧的写半）。

    env 是显式覆盖的统一到达通道——settings/toolchain/ctan 消费侧全经
    env 读取（``create_app(data_dir=)`` 参数面覆盖不到），故只写 env、
    不走参数传递。
    """
    os.environ[ENV_DATA_DIR] = str(path.expanduser())


def cache_root() -> Path:
    """缓存根：``TEXLATE_CACHE_DIR`` > ``$XDG_CACHE_HOME/texlate`` > ``~/.cache/texlate``——只定位不 mkdir。

    ``data_root`` 的缓存侧对称件。``TEXLATE_CACHE`` 不复用：已登记为 ctan
    filemap 叶目录（``compile/ctan.py``）。
    """
    raw = env_raw(ENV_CACHE_DIR)
    if raw:
        return Path(raw).expanduser()
    xdg = env_raw("XDG_CACHE_HOME")
    return (
        Path(xdg).expanduser() / "texlate"
        if xdg
        else Path.home() / ".cache" / "texlate"
    )


# ------------------------------------------------------------ 派生共享件

#: local 形态缺省绑定面——``cli.web``/``server.__main__`` 两入口同值。
DEFAULT_BIND_HOST: Final = "127.0.0.1"
DEFAULT_BIND_PORT: Final = 8765


def utc_now() -> str:
    """UTC 秒级时间戳，canonical Z 形（``2026-09-21T12:34:56Z``）。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def filtered_env(
    exact: set[str] | frozenset[str],
    prefixes: tuple[str, ...],
    forced: dict[str, str] | None = None,
) -> dict[str, str]:
    r"""子进程 env 白名单透传：``exact`` 名集 ∪ ``prefixes`` 前缀命中 + ``forced`` 尾写覆盖。

    ``dict(os.environ)`` 全量继承会把 ``TEXLATE_API_KEY`` 等 secret 灌进
    子进程及其孙链——``server.babeldoc``/``compile.sandbox``/
    ``validate.l1`` 三份同构白名单透传的单源骨架（``_ENV_PASS_*`` 表仍归
    各消费方自持，本件只承载过滤+覆盖机制）。
    """
    env = {k: v for k, v in os.environ.items() if k in exact or k.startswith(prefixes)}
    if forced:
        env.update(forced)
    return env


def atomic_write(path: Path, data: bytes | str, *, mode: int | None = 0o600) -> None:
    """tmp+replace 原子落盘：mkstemp 随机后缀 tmp 名防同路径并发撞名，异常清 tmp 不留尸。

    ``os.replace`` 收尾（跨平台可覆盖——POSIX rename 语义）；``mode=None``
    跳过 chmod，产物权限留 mkstemp 缺省 0600（bench ``atomic_write_text``
    同构件的委托口径）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        if isinstance(data, str):
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        if mode is not None:
            Path(tmp_name).chmod(mode)
        Path(tmp_name).replace(path)  # os.replace 同语义——跨平台原子覆盖
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
