"""compile/toolchain.py 分发矩阵 + engine.detect 接线的离线单测。

httpx MockTransport 打桩——不打真网；``TEXLATE_DATA_DIR`` 隔离到
tmp_path，``find_tool`` 钉 None 免疫宿主 PATH 上的真 tectonic。
"""

import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from conftest import make_targz

from texlate.compile import toolchain
from texlate.compile.engine import TECTONIC_BUNDLE_PIN, TectonicEngine

_FAKE_BIN = b"#!/bin/sh\necho fake tectonic\n"
_FAKE_EXE = b"MZ fake tectonic exe"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """数据目录隔离 + env 确定性 + 宿主 PATH 上的 tectonic 不可见。"""
    monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
    for key in ("TEXLATE_NO_DOWNLOAD", "CI", "TEXLATE_TEX_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(toolchain, "find_tool", lambda _name: None)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return buf.getvalue()


def _client(payload: bytes, status: int = 200) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _boom_client() -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("不应触网")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _pin(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    suffix: str,
    archive: bytes,
) -> None:
    """把构造归档的真实 sha256 钉进矩阵条目（install 校验才能过）。"""
    monkeypatch.setitem(
        toolchain.ASSETS,
        (system, machine),
        (suffix, hashlib.sha256(archive).hexdigest()),
    )


# ---------------------------------------------------------------- 平台矩阵
def test_asset_matrix_five_platforms() -> None:
    """五条钉值逐字对拍（上游实下载复核过的值，勿漂移）。"""
    cases = {
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
    assert cases == toolchain.ASSETS
    for (system, _machine), (suffix, _digest) in cases.items():
        url, sha, binary = toolchain.asset_for(system, _machine)
        assert url == (
            "https://github.com/tectonic-typesetting/tectonic/releases/"
            f"download/tectonic%40{toolchain.TECTONIC_VERSION}/"
            f"tectonic-{toolchain.TECTONIC_VERSION}-{suffix}"
        )
        assert sha == cases[(system, _machine)][1]
        assert binary == ("tectonic.exe" if system == "Windows" else "tectonic")


def test_asset_machine_aliases() -> None:
    """amd64→x86_64、aarch64→arm64 归一化（uname -m 差异免疫）。"""
    url_a, sha_a, _ = toolchain.asset_for("Linux", "amd64")
    url_b, sha_b, _ = toolchain.asset_for("Linux", "x86_64")
    assert (url_a, sha_a) == (url_b, sha_b)
    _, sha_m, _ = toolchain.asset_for("Darwin", "aarch64")
    _, sha_m2, _ = toolchain.asset_for("Darwin", "arm64")
    assert sha_m == sha_m2


def test_asset_unsupported_platform() -> None:
    with pytest.raises(RuntimeError, match="无预置编译器"):
        toolchain.asset_for("FreeBSD", "x86_64")


# ---------------------------------------------------------------- 安装
def test_install_targz_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tar.gz：单文件提取 + 0o755 + replace 落位 + 无 .download 残留。"""
    archive = make_targz({"tectonic": _FAKE_BIN})
    _pin(monkeypatch, "Linux", "x86_64", "x86_64-unknown-linux-musl.tar.gz", archive)
    dest = tmp_path / "tools"
    out = toolchain.install_tectonic(
        dest, system="Linux", machine="x86_64", client=_client(archive)
    )
    assert out == dest / "tectonic"
    assert out.read_bytes() == _FAKE_BIN
    assert os.access(out, os.X_OK)
    assert not (dest / "tectonic.download").exists()


def test_install_zip_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """zip：basename tectonic.exe 提取。"""
    archive = _zip({"tectonic.exe": _FAKE_EXE, "README.txt": b"hi"})
    _pin(monkeypatch, "Windows", "x86_64", "x86_64-pc-windows-msvc.zip", archive)
    dest = tmp_path / "tools"
    out = toolchain.install_tectonic(
        dest, system="Windows", machine="x86_64", client=_client(archive)
    )
    assert out.name == "tectonic.exe"
    assert out.read_bytes() == _FAKE_EXE


def test_install_sha256_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """digest 不匹配 → 整体拒绝且不落任何文件（校验先于 mkdir）。"""
    archive = make_targz({"tectonic": _FAKE_BIN})
    monkeypatch.setitem(
        toolchain.ASSETS,
        ("Linux", "x86_64"),
        ("x86_64-unknown-linux-musl.tar.gz", "0" * 64),
    )
    dest = tmp_path / "tools"
    with pytest.raises(RuntimeError, match="sha256"):
        toolchain.install_tectonic(
            dest, system="Linux", machine="x86_64", client=_client(archive)
        )
    assert not dest.exists()


def test_install_multi_member_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归档里 basename 匹配数 != 1 → 拒绝（sha256 过也不放行布局异常）。"""
    archive = make_targz({"a/tectonic": b"1", "b/tectonic": b"2"})
    _pin(monkeypatch, "Linux", "x86_64", "x86_64-unknown-linux-musl.tar.gz", archive)
    dest = tmp_path / "tools"
    with pytest.raises(RuntimeError, match="布局异常"):
        toolchain.install_tectonic(
            dest, system="Linux", machine="x86_64", client=_client(archive)
        )
    assert not dest.exists()


def test_install_oversize_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载体超 150MB 帽即拒（测试把帽缩到 8B）。"""
    monkeypatch.setattr(toolchain, "_DOWNLOAD_CAP", 8)
    with pytest.raises(RuntimeError, match="超限"):
        toolchain.install_tectonic(
            tmp_path / "tools",
            system="Linux",
            machine="x86_64",
            client=_client(b"x" * 16),
        )


def test_install_http_error_raises(tmp_path: Path) -> None:
    """HTTP 5xx → raise_for_status 抛 HTTPStatusError。"""
    with pytest.raises(httpx.HTTPStatusError):
        toolchain.install_tectonic(
            tmp_path / "tools",
            system="Linux",
            machine="x86_64",
            client=_client(b"err", status=500),
        )


# ---------------------------------------------------------------- ensure 链
def _plant_managed() -> Path:
    """托管目录放一个可执行 tectonic（autouse 已把 PATH 探测钉 None）。"""
    managed = toolchain.tools_dir()
    managed.mkdir(parents=True)
    exe = managed / "tectonic"
    exe.write_bytes(_FAKE_BIN)
    exe.chmod(0o755)
    return exe


def test_ensure_prefers_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """系统预装优先于托管件与下载（不触网）。"""
    _plant_managed()
    monkeypatch.setattr(toolchain, "find_tool", lambda _n: "/usr/bin/tectonic")
    assert toolchain.ensure_tectonic(client=_boom_client()) == "/usr/bin/tectonic"


def test_ensure_managed_short_circuit() -> None:
    """已落托管件 → 直接返回不下载（PATH 探测钉 None 由 autouse 给）。"""
    exe = _plant_managed()
    assert toolchain.ensure_tectonic(client=_boom_client()) == str(exe)


def test_ensure_no_download_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEXLATE_NO_DOWNLOAD=1 → None 且不触网。"""
    monkeypatch.setenv("TEXLATE_NO_DOWNLOAD", "1")
    assert toolchain.ensure_tectonic(client=_boom_client()) is None


def test_ensure_ci_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI 环境默认不拉（CI 引擎腿显式装）。"""
    monkeypatch.setenv("CI", "true")
    assert toolchain.ensure_tectonic(client=_boom_client()) is None


def test_ensure_ci_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEXLATE_NO_DOWNLOAD=0 显式覆盖 CI 默认 → 仍下载。"""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("TEXLATE_NO_DOWNLOAD", "0")
    archive = make_targz({"tectonic": _FAKE_BIN})
    _pin(monkeypatch, "Linux", "x86_64", "x86_64-unknown-linux-musl.tar.gz", archive)
    out = toolchain.ensure_tectonic(
        system="Linux", machine="x86_64", client=_client(archive)
    )
    assert out == str(toolchain.tools_dir() / "tectonic")
    assert Path(out).read_bytes() == _FAKE_BIN


def test_ensure_http_failure_returns_none() -> None:
    """下载失败 → warning + None（编译侧按引擎缺失处理，不炸调用方）。"""
    assert (
        toolchain.ensure_tectonic(
            system="Linux", machine="x86_64", client=_client(b"err", status=500)
        )
        is None
    )


def test_ensure_corrupt_archive_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sha256 匹配但归档损坏（既非 zip 也非 tar）→ None。"""
    garbage = b"definitely not an archive"
    _pin(
        monkeypatch,
        "Linux",
        "x86_64",
        "x86_64-unknown-linux-musl.tar.gz",
        garbage,
    )
    assert (
        toolchain.ensure_tectonic(
            system="Linux", machine="x86_64", client=_client(garbage)
        )
        is None
    )


def test_ensure_unsupported_platform_returns_none() -> None:
    """矩阵外平台 → None（asset_for 的 RuntimeError 被吞为引擎缺失）。"""
    assert toolchain.ensure_tectonic(system="FreeBSD", machine="x86_64") is None


def test_ensure_smoke_failure_removes_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sha256 过但产物不可执行 → 删掉再返 None（防 find_managed 毒化）。"""
    archive = make_targz({"tectonic": b"exit 1\n"})  # /bin/sh 兜底执行 rc=1
    _pin(
        monkeypatch,
        "Linux",
        "x86_64",
        "x86_64-unknown-linux-musl.tar.gz",
        archive,
    )
    assert (
        toolchain.ensure_tectonic(
            system="Linux", machine="x86_64", client=_client(archive)
        )
        is None
    )
    assert not (toolchain.tools_dir() / "tectonic").exists()


def test_resolve_tool_no_network() -> None:
    """resolve_tool 是纯探测：系统件 → 托管件，永不下载。"""
    assert toolchain.resolve_tool("tectonic") is None
    exe = _plant_managed()
    assert toolchain.resolve_tool("tectonic") == str(exe)


# ---------------------------------------------------------------- engine 接线
def test_engine_detect_uses_managed() -> None:
    """detect() 落到托管件（ctor/PATH 未命中时）。"""
    exe = _plant_managed()
    assert TectonicEngine().detect() == str(exe)


def test_engine_detect_ctor_binary_wins() -> None:
    assert TectonicEngine(binary="/opt/tex/tectonic").detect() == "/opt/tex/tectonic"


def test_engine_detect_none_when_no_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """禁下载 + 无托管件 → detect() None → compile 报 tectonic not found。"""
    monkeypatch.setenv("TEXLATE_NO_DOWNLOAD", "1")
    assert TectonicEngine().detect() is None


def test_engine_bundle_pin_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认走 tlextras-2022.0r0 钉版（env 缺席时）。"""
    monkeypatch.delenv("TEXLATE_TEX_BUNDLE", raising=False)
    assert TectonicEngine().bundle == TECTONIC_BUNDLE_PIN


def test_engine_bundle_env_override_and_empty_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 覆盖 pin；置空串 = 引擎自带默认 bundle（falsy → 不加 --web-bundle）。"""
    monkeypatch.setenv("TEXLATE_TEX_BUNDLE", "https://x/custom.tar")
    assert TectonicEngine().bundle == "https://x/custom.tar"
    monkeypatch.setenv("TEXLATE_TEX_BUNDLE", "")
    assert TectonicEngine().bundle == ""
    assert TectonicEngine(bundle="https://y/b.tar").bundle == "https://y/b.tar"


# ---------------------------------------------------------------- 版本探针
def _plant_version_exe(tmp_path: Path, body: str) -> str:
    """tmp_path 放一个假 tectonic 脚本（输出内容由 body 定）。"""
    exe = tmp_path / "tectonic"
    exe.write_text(body, encoding="utf-8")
    exe.chmod(0o755)
    return str(exe)


@pytest.mark.skipif(sys.platform == "win32", reason="win32 无法 exec sh 脚本替身")
def test_tectonic_version_parses(tmp_path: Path) -> None:
    """``--version`` 输出 → ``(major,minor,patch)``；大小写两种行首都吃。"""
    exe = _plant_version_exe(tmp_path, '#!/bin/sh\necho "Tectonic 0.17.0"\n')
    toolchain.tectonic_version.cache_clear()
    assert toolchain.tectonic_version(exe) == (0, 17, 0)


def test_tectonic_version_unparseable_and_missing(tmp_path: Path) -> None:
    """跑不动/无版本号 → None（bundle flag 落新语法默认侧）。"""
    exe = _plant_version_exe(tmp_path, "#!/bin/sh\necho noise\n")
    toolchain.tectonic_version.cache_clear()
    assert toolchain.tectonic_version(exe) is None
    assert toolchain.tectonic_version(str(tmp_path / "nonexistent")) is None


@pytest.mark.skipif(sys.platform == "win32", reason="win32 无法 exec sh 脚本替身")
def test_tectonic_version_cached(tmp_path: Path) -> None:
    """同一 binary 只探一回——``-X compile`` 每文件都走 ``_cmd`` 问到。"""
    counter = tmp_path / "n"
    exe = _plant_version_exe(
        tmp_path, f'#!/bin/sh\necho x >> "{counter}"\necho "tectonic 0.15.0"\n'
    )
    toolchain.tectonic_version.cache_clear()
    assert toolchain.tectonic_version(exe) == (0, 15, 0)
    assert toolchain.tectonic_version(exe) == (0, 15, 0)
    assert counter.read_text(encoding="utf-8").strip() == "x"  # 只跑了一次
