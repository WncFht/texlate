"""``texlate doctor``：环境自检各检查项三态 + 退出码语义（全 mock，不触网/不跑真二进制）。

探测面全部 monkeypatch：``cli.find_tool``/``toolchain.resolve_tool`` 定位置，
``subprocess.run`` 按 argv 桩出版本/kpsewhich/fc-list 应答，``httpx.get`` 桩网关
探活。data-dir 走 ``TEXLATE_DATA_DIR`` 真 tmp_path（mkdir/写删语义要真文件系统
过一遍）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx
import pytest
from typer.testing import CliRunner

from texlate import cli
from texlate.cli import app
from texlate.cli.service import _ServiceStatus
from texlate.compile import toolchain

if TYPE_CHECKING:
    from pathlib import Path

_RUNNER = CliRunner()

_GW_URL = "http://gw.test:3003"
_GW_KEY = "sk-doctor-test-secret"


def _cp(
    stdout: bytes = b"", stderr: bytes = b"", rc: int = 0
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout=stdout, stderr=stderr
    )


_RunStub = (
    bytes
    | subprocess.CompletedProcess[bytes]
    | Callable[[list[str]], subprocess.CompletedProcess[bytes]]
)


def _fake_run(
    tools: dict[str, _RunStub], *, default: bytes | None = None
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """``subprocess.run`` 桩工厂——按 ``argv[0]`` 基名派发应答。

    应答值三形：``bytes`` → ``_cp(stdout=..)`` 命中；``CompletedProcess`` →
    原样返回；``callable`` → ``fn(argv)`` 参级再分发。未列名工具回通用
    版本串（``default`` 缺省 ``<tool> 1.2.3``）。
    """

    def _run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[bytes]:
        tool = argv[0].rsplit("/", 1)[-1]
        resp = tools.get(tool)
        if callable(resp):
            return resp(argv)
        if isinstance(resp, bytes):
            return _cp(stdout=resp)
        if resp is not None:
            return resp
        return _cp(
            stdout=default if default is not None else f"{tool} 1.2.3\n".encode()
        )

    return _run


def _statuses(output: str) -> dict[str, str]:
    """stdout → ``{check_name: status}``（检查行首词即状态列）。"""
    out: dict[str, str] = {}
    for line in output.splitlines():
        match line.split(None, 2):
            case [status, name, *_] if status in {"ok", "warn", "fail", "n/a"}:
                out[name] = status
    return out


def _write_settings(data: Path, **kw: object) -> None:
    """``<data>/settings.json`` 落盘（gateway 检查的配置面）。"""
    data.mkdir(parents=True, exist_ok=True)
    (data / "settings.json").write_text(json.dumps(kw), encoding="utf-8")


def _svc_status(root: Path, **over: object) -> _ServiceStatus:
    """``_probe_service`` 桩返回值——缺省 stopped，``over`` 逐字段覆盖。"""
    base: dict[str, object] = {
        "state": "stopped",
        "pid": None,
        "pid_alive": False,
        "url": "",
        "root": root,
        "version": "",
        "started_at": "",
        "uptime": "",
        "foreign": "",
    }
    return _ServiceStatus(**{**base, **over})  # type: ignore[arg-type]


@pytest.fixture
def doctor_env(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """全件 ok 基线：工具全命中 + 版本应答 + 字体全核到。

    ``TEXLATE_DATA_DIR`` 落 ``tmp_path/data``；返回 monkeypatch 供各测试
    再翻单件。网关默认不配（无 settings.json/env）→ n/a，要探活的用例
    自己写 settings 并桩 ``httpx.get``。
    """
    clean_env.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
    clean_env.setattr(toolchain, "resolve_tool", lambda _n: "/fake/tectonic")
    clean_env.setattr(toolchain, "find_managed", lambda: None)
    clean_env.setattr(cli, "find_tool", lambda name: f"/fake/{name}")

    clean_env.setattr(
        subprocess,
        "run",
        _fake_run(
            {
                "kpsewhich": lambda argv: _cp(stdout=f"/texmf/{argv[1]}\n".encode()),
                "fc-list": b"Noto Sans CJK SC\n",
                # poppler -v 版本走 stderr
                "pdftotext": _cp(stderr=b"pdftotext version 24.01\n"),
            }
        ),
    )
    return clean_env


def test_help() -> None:
    """``--help`` 出命令文档，exit 0。"""
    r = _RUNNER.invoke(app, ["doctor", "--help"])
    assert r.exit_code == 0
    assert "环境自检" in r.stdout


class TestDoctor:
    def test_all_ok(self, tmp_path: Path, doctor_env: pytest.MonkeyPatch) -> None:
        """全绿基线：10 项全 ok（网关 settings+httpx 桩 200），exit 0。"""
        _write_settings(tmp_path / "data", base_url=_GW_URL, api_key=_GW_KEY)
        (tmp_path / "data" / "endpoints.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        {
                            "id": "p1",
                            "base_url": "https://gw.test:8443",
                            "models": [{"model": "m1", "redirect_model": ""}],
                            "api_key": _GW_KEY,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        doctor_env.setattr(
            cli,
            "_probe_service",
            lambda _root: _svc_status(
                tmp_path / "data",
                state="running",
                pid=1,
                pid_alive=True,
                url="http://127.0.0.1:8765",
                version="0.1.0",
            ),
        )
        seen: dict[str, object] = {}

        def _get(url: str, **kw: object) -> httpx.Response:
            seen["url"] = url
            seen["headers"] = kw.get("headers")
            return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

        doctor_env.setattr(httpx, "get", _get)
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert set(st) == {
            "python",
            "tectonic",
            "xelatex",
            "cjk-fonts",
            "pdftotext",
            "gateway",
            "data-dir",
            "babeldoc",
            "service",
            "endpoints",
        }
        assert all(v == "ok" for v in st.values()), r.stdout
        assert seen["url"] == f"{_GW_URL}/v1/models"
        assert seen["headers"] == {"Authorization": f"Bearer {_GW_KEY}"}
        assert _GW_KEY not in r.stdout  # key 绝不进输出
        assert "2 models" in r.stdout

    def test_python_too_old_fail(self, doctor_env: pytest.MonkeyPatch) -> None:
        """python <3.12 → fail + exit 1（tuple 桩兼容 sys.version_info 索引访问）。"""
        doctor_env.setattr(sys, "version_info", (3, 11, 9))
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 1
        assert _statuses(r.stdout)["python"] == "fail"

    def test_engines_both_missing_fail(self, doctor_env: pytest.MonkeyPatch) -> None:
        """双引擎缺席 → 两项 fail，exit 1。"""
        doctor_env.setattr(toolchain, "resolve_tool", lambda _n: None)
        doctor_env.setattr(cli, "find_tool", lambda _n: None)
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 1
        st = _statuses(r.stdout)
        assert st["tectonic"] == "fail"
        assert st["xelatex"] == "fail"

    def test_engine_single_missing_warn(self, doctor_env: pytest.MonkeyPatch) -> None:
        """tectonic 在、xelatex 缺 → warn 不 fail（auto 仍有腿），exit 0。"""
        doctor_env.setattr(
            cli,
            "find_tool",
            lambda n: None if n == "xelatex" else f"/fake/{n}",
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert st["tectonic"] == "ok"
        assert st["xelatex"] == "warn"
        assert "系统件" in r.stdout
        assert "托管件" not in r.stdout

    def test_managed_tectonic_label(self, doctor_env: pytest.MonkeyPatch) -> None:
        """resolve 命中托管目录 → detail 标托管件。"""
        doctor_env.setattr(toolchain, "resolve_tool", lambda _n: "/data/tools/tectonic")
        doctor_env.setattr(toolchain, "find_managed", lambda: "/data/tools/tectonic")
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert "托管件 /data/tools/tectonic" in r.stdout

    def test_cjk_fonts_na(self, doctor_env: pytest.MonkeyPatch) -> None:
        """kpsewhich/fc-list 双缺 → n/a。"""
        doctor_env.setattr(
            cli,
            "find_tool",
            lambda n: None if n in ("kpsewhich", "fc-list") else f"/fake/{n}",
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["cjk-fonts"] == "n/a"

    def test_cjk_fonts_warn(self, doctor_env: pytest.MonkeyPatch) -> None:
        """可探但全空（kpsewhich 无 ctex/fandol + fc-list 无 zh）→ warn。"""
        doctor_env.setattr(
            subprocess,
            "run",
            _fake_run({"kpsewhich": b"", "fc-list": b""}, default=b"t 1.0\n"),
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["cjk-fonts"] == "warn"

    def test_cjk_fonts_sys_zh_ok(self, doctor_env: pytest.MonkeyPatch) -> None:
        """fandol 缺但系统 zh 字体在 → ok（ctex fontset 可回落）。"""

        def _kpsewhich(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
            # ctex.sty 命中、fandol 不命中
            if argv[1] == "ctex.sty":
                return _cp(stdout=b"/texmf/ctex.sty\n")
            return _cp()

        doctor_env.setattr(
            subprocess,
            "run",
            _fake_run(
                {"kpsewhich": _kpsewhich, "fc-list": b"Noto Sans CJK\n"},
                default=b"t 1.0\n",
            ),
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["cjk-fonts"] == "ok"

    def test_pdftotext_missing_warn(self, doctor_env: pytest.MonkeyPatch) -> None:
        """pdftotext 缺席 → warn（judge 降级，不 fail）。"""
        doctor_env.setattr(
            cli,
            "find_tool",
            lambda n: None if n == "pdftotext" else f"/fake/{n}",
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert st["pdftotext"] == "warn"
        assert "log 判据" in r.stdout

    def test_gateway_unconfigured_na(
        self,
        doctor_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """无 settings/env → n/a + BYOK 提示，exit 0。"""
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert st["gateway"] == "n/a"
        assert "texlate web" in r.stdout

    def test_gateway_settings_without_keys_na(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """settings.json 在但没写网关键 → n/a——``load()`` 回填的默认
        base_url 不算"已配置"（否则非 tailnet 用户被默认网关误诊 fail）。"""
        _write_settings(tmp_path / "data", model="some-model")

        def _boom(*_a: object, **_kw: object) -> httpx.Response:
            msg = "should not probe"
            raise AssertionError(msg)

        doctor_env.setattr(httpx, "get", _boom)
        # service 检查的 health 探测同走 httpx——桩掉免触炸桩
        doctor_env.setattr(
            cli, "_probe_service", lambda _root: _svc_status(tmp_path / "data")
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["gateway"] == "n/a"

    def test_gateway_unauthorized_warn(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """网关可达但 401 → warn（key 无效），exit 0。"""
        _write_settings(tmp_path / "data", base_url=_GW_URL, api_key=_GW_KEY)
        doctor_env.setattr(httpx, "get", lambda *_a, **_kw: httpx.Response(401))
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert st["gateway"] == "warn"
        assert "401" in r.stdout

    def test_gateway_unreachable_fail(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """网关连不上（传输层）→ fail + exit 1。"""

        def _down(*_a: object, **_kw: object) -> httpx.Response:
            msg = "connection refused"
            raise httpx.ConnectError(msg)

        _write_settings(tmp_path / "data", base_url=_GW_URL, api_key=_GW_KEY)
        doctor_env.setattr(httpx, "get", _down)
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 1
        st = _statuses(r.stdout)
        assert st["gateway"] == "fail"

    def test_gateway_env_config(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """无 settings.json 但 TEXLATE_BASE_URL/API_KEY env 在 → 照样探活。"""
        doctor_env.setenv("TEXLATE_BASE_URL", _GW_URL)
        doctor_env.setenv("TEXLATE_API_KEY", _GW_KEY)
        # service 检查的 health 探测同走 httpx.get——桩掉免污染 seen 列表
        doctor_env.setattr(
            cli, "_probe_service", lambda _root: _svc_status(tmp_path / "data")
        )
        seen: list[str] = []

        def _get(url: str, **_kw: object) -> httpx.Response:
            seen.append(url)
            return httpx.Response(200, json={"data": []})

        doctor_env.setattr(httpx, "get", _get)
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["gateway"] == "ok"
        assert seen == [f"{_GW_URL}/v1/models"]

    def test_data_dir_unwritable_fail(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """``TEXLATE_DATA_DIR`` 指向已存在文件 → mkdir 炸 → fail + exit 1。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        doctor_env.setenv("TEXLATE_DATA_DIR", str(blocker))
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 1
        st = _statuses(r.stdout)
        assert st["data-dir"] == "fail"

    def test_babeldoc_na(self, doctor_env: pytest.MonkeyPatch) -> None:
        """babeldoc 缺席 → n/a（可选件不计 fail）。"""
        doctor_env.setattr(
            cli,
            "find_tool",
            lambda n: None if n == "babeldoc" else f"/fake/{n}",
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["babeldoc"] == "n/a"

    def test_endpoints_absent_na(
        self,
        doctor_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """无 endpoints.json → n/a（未建档是常态，读径投影兜底）。"""
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["endpoints"] == "n/a"

    def test_endpoints_ok_counts(
        self, tmp_path: Path, doctor_env: pytest.MonkeyPatch
    ) -> None:
        """档案在 → ok：条数/启用数/活动命中（settings.base_url 归一比对）。

        base_url 用 https——``validate_base_url`` 拒非 loopback/tailnet 的
        http（``_GW_URL`` 过不了档案校验会被 ``_load_profile`` 容错丢弃）。
        """
        ep_url = "https://ep.test/api"
        _write_settings(tmp_path / "data", base_url=ep_url)
        (tmp_path / "data" / "endpoints.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        {
                            "id": "p1",
                            "base_url": ep_url,
                            "models": [{"model": "m1", "redirect_model": ""}],
                        },
                        {
                            "id": "p2",
                            "base_url": "https://or.test/api",
                            "enabled": False,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        # gateway 检查会真 GET ep.test/v1/models——桩 200 免触网
        doctor_env.setattr(
            httpx, "get", lambda *_a, **_kw: httpx.Response(200, json={"data": []})
        )
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        st = _statuses(r.stdout)
        assert st["endpoints"] == "ok"
        assert "2 条档案（1 启用），活动=p1" in r.stdout

    def test_endpoints_quarantined_warn(
        self,
        tmp_path: Path,
        doctor_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """损坏 endpoints.json → load 隔离成 ``*-invalid-*`` 兄弟 → warn 留痕。"""
        data = tmp_path / "data"
        data.mkdir(parents=True)
        (data / "endpoints.json").write_text("{broken", encoding="utf-8")
        r = _RUNNER.invoke(app, ["doctor"])
        assert r.exit_code == 0, r.output
        assert _statuses(r.stdout)["endpoints"] == "warn"
        assert "隔离残件" in r.stdout
        assert list(data.glob("endpoints-invalid-*.json"))
