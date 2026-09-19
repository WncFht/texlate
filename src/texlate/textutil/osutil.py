r"""os 边界小件 —— env 读取与路径防御的各层共用单源。

``TEXLATE_*`` env 读取的单一事实源：布尔旗标统一 ``1/true/yes/on``
真值表（strip+lower 后判定）；字符串选择器统一 strip+lower 归一、值
敏感场 strip-only；浮点参数统一解析失败/nan/inf 回默认（范围裁剪归
调用方）；数据根统一 ``TEXLATE_DATA_DIR`` > ``~/.texlate``（只定位不
mkdir，副作用归调用方）。``safe_resolve``/``safe_is_file`` 是
``Path`` 防御层——上游恶意/病态名触发的 ``OSError``/``RuntimeError``/
``ValueError`` 一律收敛为缺席语义。
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Final


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


def safe_is_file(path: Path) -> bool:
    r"""``Path.is_file()`` 防御层：NUL ``ValueError`` + 非豁免 ``OSError`` → False。

    pathlib 自吞 ``OSError``，但内嵌 NUL 字节的路径抛 ``ValueError`` 不豁免——
    攻击者可控名（``\\includegraphics`` 参数、fixloop 供给的 fname）直达即崩。
    """
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


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


def data_root() -> Path:
    """数据根：``TEXLATE_DATA_DIR`` > ``~/.texlate``——只定位不 mkdir。"""
    raw = os.environ.get("TEXLATE_DATA_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".texlate"
