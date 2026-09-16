"""tectonic 便携引擎分发：五平台 sha256 钉死矩阵 + 自动安装。

texglot ``scripts/install_compiler.py`` 移植（docs/research/latex/
texglot-patterns §5），服务 ``uv tool install`` 一键可用语义：

- 查找链 ``ensure_tectonic``：``find_tool``（PATH → macOS 落点）→ 托管目录
  ``<data>/tools/`` → 自动下载；``resolve_tool``/``find_managed`` 不触网，
  供 health/探测面用。
- sha256 是**唯一信任锚**（无 PGP/sigstore）——不匹配即整体拒绝，先校验
  后落盘，绝不执行未过校验的产物。
- 归档只提 ``tectonic`` 单文件（成员 basename 匹配且恰好一个）；先写
  ``<tools>/tectonic.download`` → ``chmod 0o755`` → ``replace()`` 原子落位。
- 托管根 ``TEXLATE_DATA_DIR`` > ``~/.texlate``（与 ``server/settings.data_dir``
  同根的独立实现——compile 层不反向依赖 server）。
- 开关：``TEXLATE_NO_DOWNLOAD`` 真值关；``CI`` 真值环境默认关（CI 引擎腿
  显式装引擎）；显式 ``TEXLATE_NO_DOWNLOAD=0`` 可在 CI 强制开。
- 矩阵 hash 抄自 texglot 钉值，2026-09-16 已对 GitHub release 实下载五条
  全复核一致（linux-x86_64 另与 ci.yml 钉值互证）。
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx

from .sandbox import find_tool

log = logging.getLogger(__name__)

TECTONIC_VERSION = "0.17.0"

#: ``(system, machine)`` → ``(asset 文件名后缀, sha256)``——texglot 钉值，
#: 已对上游 release 实下载复核（见模块 docstring）。
ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("Windows", "x86_64"): (
        "x86_64-pc-windows-msvc.zip",
        "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f",
    ),
    ("Darwin", "arm64"): (
        "aarch64-apple-darwin.tar.gz",
        "a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-apple-darwin.tar.gz",
        "7c90ef5b6ddb1eb1937e4337add5237b79338e4b9676459fa91187d24d6cdf80",
    ),
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-musl.tar.gz",
        "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7",
    ),
    ("Linux", "arm64"): (
        "aarch64-unknown-linux-musl.tar.gz",
        "b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8",
    ),
}

#: 下载体封顶（texglot 同额 150MB——内存帽，超限即拒）与超时。
_DOWNLOAD_CAP = 150 * 1024 * 1024
_TIMEOUT = httpx.Timeout(90.0, connect=15.0)

_TRUE = ("1", "true", "yes", "on")


def data_root() -> Path:
    """数据根：``TEXLATE_DATA_DIR`` > ``~/.texlate``（settings.data_dir 同款）。"""
    raw = os.environ.get("TEXLATE_DATA_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".texlate"


def tools_dir() -> Path:
    """托管二进制目录 ``<data>/tools``——只定位不 mkdir（探测面不产副作用）。"""
    return data_root() / "tools"


def download_allowed() -> bool:
    """自动下载开关：``TEXLATE_NO_DOWNLOAD`` 显式设置优先；``CI`` 真值默认关。"""
    v = os.environ.get("TEXLATE_NO_DOWNLOAD")
    if v is not None:
        return v.strip().lower() not in _TRUE
    return os.environ.get("CI", "").strip().lower() not in _TRUE


def asset_for(system: str, machine: str) -> tuple[str, str, str]:
    """平台 → ``(url, sha256, binary_name)``；不支持的平台 RuntimeError。"""
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine.lower(), machine.lower())
    try:
        suffix, digest = ASSETS[(system, arch)]
    except KeyError:
        msg = f"无预置编译器 {system}/{machine}；请自装 tectonic 加入 PATH"
        raise RuntimeError(msg) from None
    filename = f"tectonic-{TECTONIC_VERSION}-{suffix}"
    url = (
        "https://github.com/tectonic-typesetting/tectonic/releases/download/"
        f"tectonic%40{TECTONIC_VERSION}/{filename}"
    )
    binary_name = "tectonic.exe" if system == "Windows" else "tectonic"
    return url, digest, binary_name


def _fetch(url: str, client: httpx.Client) -> bytes:
    """流式下载到内存：累计超 ``_DOWNLOAD_CAP`` 即拒（texglot 同额帽）。"""
    buf = io.BytesIO()
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            buf.write(chunk)
            if buf.tell() > _DOWNLOAD_CAP:
                msg = f"tectonic 归档超限（>{_DOWNLOAD_CAP}B），拒绝安装"
                raise RuntimeError(msg)
    return buf.getvalue()


def _extract_binary(archive: bytes, binary_name: str) -> bytes:
    """只提 basename==binary_name 的**恰好一个**文件成员；布局不符即拒。

    内容判定按归档魔数（``is_zipfile``）而非 URL 后缀；成员读内容不落地，
    天然免 zip-slip/路径穿越。
    """
    if zipfile.is_zipfile(io.BytesIO(archive)):
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = [
                n
                for n in zf.namelist()
                if not n.endswith("/") and Path(n).name == binary_name
            ]
            if len(names) != 1:
                msg = "tectonic zip 布局异常（单文件成员数 != 1），拒绝安装"
                raise RuntimeError(msg)
            return zf.read(names[0])
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
        members = [
            m
            for m in tf.getmembers()
            if m.isfile() and Path(m.name).name == binary_name
        ]
        if len(members) != 1:
            msg = "tectonic tar 布局异常（单文件成员数 != 1），拒绝安装"
            raise RuntimeError(msg)
        member_file = tf.extractfile(members[0])
        if member_file is None:
            msg = "tectonic tar 成员不可读，拒绝安装"
            raise RuntimeError(msg)
        return member_file.read()


def install_tectonic(
    dest_dir: Path | None = None,
    *,
    system: str | None = None,
    machine: str | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """下载 → sha256 → 单文件提取 → 原子落位；任何一步失败不落目标文件。

    ``dest_dir`` 缺省 ``<data>/tools``（缺 data 根时按 settings.data_dir
    同款 0700 建根）；``client`` 缺省自建（90s 超时 + 跟随 GitHub release
    的 302 跳转）。
    """
    url, expected, binary_name = asset_for(
        system or platform.system(), machine or platform.machine()
    )
    http = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        archive = _fetch(url, http)
    finally:
        if client is None:
            http.close()
    if hashlib.sha256(archive).hexdigest() != expected:
        msg = "tectonic sha256 校验失败——未安装任何文件"
        raise RuntimeError(msg)
    data = _extract_binary(archive, binary_name)
    if dest_dir is None:
        root = data_root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest = root / "tools"
    else:
        dest = dest_dir
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (binary_name + ".download")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    target = dest / binary_name
    tmp.replace(target)
    return target


def find_managed(name: str = "tectonic") -> str | None:
    """托管目录已落位件；缺席 None（不触网、不 mkdir）。"""
    fname = name + (".exe" if sys.platform == "win32" else "")
    p = tools_dir() / fname
    if p.is_file() and os.access(p, os.X_OK):
        return str(p)
    return None


def resolve_tool(name: str) -> str | None:
    """系统件（``find_tool``：PATH/常见落点）→ 托管件。探测面用，不触网。"""
    return find_tool(name) or find_managed(name)


def _smoke(binary: Path) -> bool:
    """落位后 ``--version`` 自检：sha256 保字节对，自检保本平台可执行。"""
    try:
        r = subprocess.run(  # noqa: S603 — 二进制已过 sha256 钉校验
            [str(binary), "--version"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def ensure_tectonic(
    *,
    system: str | None = None,
    machine: str | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """``resolve_tool`` → 未命中且 ``download_allowed`` 时自动安装。

    下载/校验/落盘失败记 warning 返 None（编译侧按「引擎缺失」处理）；
    装完跑 ``--version`` 自检——不可执行的产物**删掉**再返 None（留着会
    让 ``find_managed`` 永远命中坏件、每次编译都踩 Popen 异常）。要 raise
    语义的显式安装走 ``install_tectonic``。
    """
    found = resolve_tool("tectonic")
    if found:
        return found
    if not download_allowed():
        return None
    try:
        path = install_tectonic(system=system, machine=machine, client=client)
    except (
        OSError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        httpx.HTTPError,
    ) as e:
        log.warning("tectonic 自动安装失败：%s", e)
        return None
    if not _smoke(path):
        log.warning("tectonic 自检（--version）失败：%s 不可执行，已移除", path)
        path.unlink(missing_ok=True)
        return None
    log.info("tectonic %s 已安装至 %s", TECTONIC_VERSION, path)
    return str(path)
