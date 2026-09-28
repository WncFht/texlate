"""``doctor`` 命令：环境自检逐项 ok/warn/fail/n/a。

``find_tool``/``find_spec`` 经 ``_cli.`` 调用期解析——测试 monkeypatch
``cli.find_tool``/``cli.find_spec`` 面守恒。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import typer

import texlate.cli as _cli
from texlate.cli._common import _is_file, app
from texlate.compile import toolchain

if TYPE_CHECKING:
    from typing import Any

    from texlate.server.settings import SettingsStore


@dataclass(frozen=True, slots=True)
class _Check:
    """单项自检结果：``status`` ∈ ``ok|warn|fail|n/a``。"""

    name: str
    status: str
    detail: str


#: 探测子进程（``--version``/kpsewhich/fc-list）上限；网关连通单独 5s。
_DOC_PROBE_TIMEOUT_S = 15.0
_DOC_GATEWAY_TIMEOUT_S = 5.0


def _doc_run(argv: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    """探测子进程：异常/超时归一为 None——doctor 只报告，绝不炸。"""
    try:
        return subprocess.run(  # noqa: S603 -- argv[0] 是 find_tool 定位的绝对路径
            argv,
            capture_output=True,
            timeout=_DOC_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _doc_tool_version(path: str, flag: str = "--version") -> str:
    """``tool --version`` 首个非空行（stdout 优先、stderr 兜底）；跑不出 → ``""``。

    tectonic 0.15 ``--version`` 把 ``tectonic 0.15.0``+``Tectonic 0.15.0``
    无分隔打进同一行——semver 后紧跟大写粘连段即截断。
    """
    r = _doc_run([path, flag])
    if r is None:
        return ""
    for blob in (r.stdout, r.stderr):
        for line in blob.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            m = re.match(r".*?\d+\.\d+\.\d+", line)
            if m and m.end() < len(line) and line[m.end()].isupper():
                return line[: m.end()]
            return line.strip()
    return ""


def _doc_python() -> _Check:
    """``requires-python >=3.12``（v[:2] 比较——兼容测试里的 tuple 桩）。"""
    v = sys.version_info
    ver = ".".join(str(x) for x in v[:3])
    if v[:2] >= (3, 12):
        return _Check("python", "ok", f"{ver}（≥3.12）")
    return _Check("python", "fail", f"{ver}——texlate 需要 Python ≥3.12")


def _doc_engines() -> list[_Check]:
    """编译引擎双探：tectonic（``resolve_tool`` 含托管件）+ xelatex（``find_tool``）。

    与 ``/api/health`` 同探测函数。单缺记 warn（auto 路由还有另一腿）；
    双双缺席升级 fail——``texlate run`` 无引擎可编译。
    """
    tectonic = toolchain.resolve_tool("tectonic")
    xelatex = _cli.find_tool("xelatex")
    none = tectonic is None and xelatex is None
    out: list[_Check] = []
    if tectonic is not None:
        kind = "托管件" if tectonic == toolchain.find_managed() else "系统件"
        ver = _doc_tool_version(tectonic) or "?"
        out.append(_Check("tectonic", "ok", f"{ver}（{kind} {tectonic}）"))
    else:
        hint = "缺失——`texlate tools install-tectonic`"
        out.append(
            _Check(
                "tectonic",
                "fail" if none else "warn",
                hint + ("" if none else "（xelatex 仍可编译）"),
            )
        )
    if xelatex is not None:
        ver = _doc_tool_version(xelatex) or "?"
        out.append(_Check("xelatex", "ok", f"{ver} @ {xelatex}"))
    else:
        hint = (
            "不在 PATH——无任何可用编译引擎" if none else "不在 PATH（auto 走 tectonic）"
        )
        out.append(_Check("xelatex", "fail" if none else "warn", hint))
    return out


def _doc_kpsewhich(kpsewhich: str, what: str) -> bool:
    """``kpsewhich <file>`` 命中（rc==0 且有输出路径）。"""
    r = _doc_run([kpsewhich, what])
    return r is not None and r.returncode == 0 and bool(r.stdout.strip())


def _doc_fc_list_zh(fc_list: str) -> bool:
    """``fc-list :lang=zh`` 有输出 = 系统装了 zh 字体。"""
    r = _doc_run([fc_list, ":lang=zh"])
    return r is not None and bool(r.stdout.strip())


def _doc_cjk_fonts() -> _Check:
    """CJK 字体：fandol 是 TeX 包（``kpsewhich`` 核），系统字体走 ``fc-list :lang=zh``。

    两探测器均缺 → n/a；确认到任一中文字体通路 → ok；可探但全空 → warn
    （xelatex 中文路径断；tectonic bundle 按需拉取或可自救）。
    """
    kp = _cli.find_tool("kpsewhich")
    fc = _cli.find_tool("fc-list")
    if kp is None and fc is None:
        return _Check("cjk-fonts", "n/a", "kpsewhich/fc-list 均不在 PATH——无法探测")
    ctex = kp is not None and _doc_kpsewhich(kp, "ctex.sty")
    fandol = kp is not None and _doc_kpsewhich(kp, "FandolSong-Regular.otf")
    sys_zh = fc is not None and _doc_fc_list_zh(fc)
    if fandol:
        found = "、".join(
            n
            for n, hit in (("ctex", ctex), ("fandol", fandol), ("sys-zh", sys_zh))
            if hit
        )
        if not ctex:
            found += "（ctex.sty 未命中——TeX 集不全？）"
        return _Check("cjk-fonts", "ok", found)
    if sys_zh:
        if kp is not None and not ctex:
            return _Check(
                "cjk-fonts",
                "warn",
                "系统 zh 字体在但 kpsewhich 查无 ctex.sty——xelatex 中文路径断",
            )
        return _Check(
            "cjk-fonts", "ok", "系统 zh 字体在（fandol 缺——ctex fontset 可回落）"
        )
    if ctex:
        return _Check(
            "cjk-fonts", "warn", "ctex 在但 fandol/系统 zh 字体均缺——中文无字可排"
        )
    miss = "kpsewhich 查无 ctex/fandol" if kp else ""
    if fc:
        miss += ("；" if miss else "") + "fc-list 无 zh 字体"
    return _Check(
        "cjk-fonts",
        "warn",
        f"{miss}——xelatex 中文路径不可用（tectonic bundle 按需拉取或可自救）",
    )


def _doc_pdftotext() -> _Check:
    """Poppler ``pdftotext``——judge CJK 核验主判据；缺席降级 log 判据（warn）。"""
    p = _cli.find_tool("pdftotext")
    if p is None:
        return _Check(
            "pdftotext",
            "warn",
            "不在 PATH——judge 中文核验降级为 log 判据（装 poppler-utils）",
        )
    ver = _doc_tool_version(p, "-v") or "?"
    return _Check("pdftotext", "ok", f"{ver} @ {p}")


def _doc_settings_raw(store: SettingsStore) -> dict[str, Any]:
    """``settings.json`` 原始键（缺席/损坏/非 dict → ``{}``）。

    不用 ``store.load()``——它把缺省 ``base_url`` 回填成
    ``DEFAULT_BASE_URL``，判"配没配网关"必须看用户显式写下的键
    （否则空 settings.json 也探测默认网关 = 非 tailnet 用户误诊 fail）。
    """
    if not _is_file(store.path):
        return {}
    try:
        parsed = json.loads(store.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        # UnicodeDecodeError 是 ValueError 非 JSONDecodeError——GBK/UTF-16 存盘
        # 的手改 settings.json 漏它会炸穿 doctor 的只报告不炸契约；RecursionError
        # 罩深嵌套 JSON 炸弹。与 worker/share.py ``dual.json`` 读径同口径。
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _doc_gateway() -> _Check:
    """BYOK 网关连通：``GET {base}/v1/models`` 5s 探活（与 client.py 同端点）。

    配置面 = ``settings.json`` 原始键（``TEXLATE_DATA_DIR``>``~/.texlate``，
    只读定位不 mkdir）+ env 兜底，与 ``resolve_auth`` 同序；什么都没配
    → n/a。key 只进请求头，绝不进输出。
    """
    from texlate.server.settings import (  # noqa: PLC0415 -- server 层延迟 import
        DEFAULT_BASE_URL,
        SettingsStore,
        env_base_url,
        env_dialect,
        env_key_for,
        validate_dialect,
    )
    from texlate.xlat.client import (  # noqa: PLC0415
        dialect_for_url,
        dialect_headers,
        normalize_base_url,
    )

    store = SettingsStore(toolchain.data_root())
    raw = _doc_settings_raw(store)
    base_url = env_base_url() or str(raw.get("base_url") or "")
    api_key = str(raw.get("api_key") or "")
    if not api_key and base_url:
        api_key = env_key_for(base_url)
    if not base_url and not api_key:
        return _Check(
            "gateway",
            "n/a",
            "未配置网关/key——`texlate web` 里配 BYOK"
            "（或 TEXLATE_BASE_URL/TEXLATE_API_KEY）",
        )
    base_url = normalize_base_url(base_url or DEFAULT_BASE_URL)
    # env > settings（同 resolve_auth 序）——非 openai 方言的 /v1/models
    # 缺席属端点形态而非配置坏，输出要带方言语境才不误诊
    try:
        dialect = env_dialect() or validate_dialect(str(raw.get("dialect") or "auto"))
        eff = dialect_for_url(base_url, dialect)
    except ValueError as e:
        return _Check("gateway", "warn", f"dialect 配置非法：{e}")
    tag = f"，dialect={eff}" if eff != "openai" else ""
    url = f"{base_url}/v1/models"
    headers = dialect_headers(eff, api_key) if api_key else {}
    try:
        r = httpx.get(
            url,
            headers=headers,
            timeout=_DOC_GATEWAY_TIMEOUT_S,
            follow_redirects=True,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        return _Check("gateway", "fail", f"连不上 {url}：{e}")
    if r.is_success:
        n = ""
        try:
            data = r.json()
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            n = f"，{len(data['data'])} models"
        suffix = "" if api_key else "（无 key 探活）"
        return _Check("gateway", "ok", f"GET {url} → {r.status_code}{n}{suffix}{tag}")
    if r.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        return _Check(
            "gateway",
            "warn",
            f"GET {url} → {r.status_code}——网关可达但鉴权被拒，查 BYOK key{tag}",
        )
    hint = (
        "——该方言端点可能本就不提供 /v1/models，能翻译即配置无恙"
        if eff != "openai"
        else ""
    )
    return _Check("gateway", "warn", f"GET {url} → {r.status_code}{tag}{hint}")


def _doc_data_dir() -> _Check:
    """``TEXLATE_DATA_DIR`` > ``~/.texlate``：mkdir(0700) + 试写删。"""
    root = toolchain.data_root()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = root / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return _Check("data-dir", "fail", f"{root} 不可写：{e}")
    return _Check("data-dir", "ok", f"{root} 可写")


def _doc_server_extra() -> _Check:
    """``texlate[server]`` extra：fastapi/uvicorn 可 import 性（find_spec 不真 import）。"""
    missing = [m for m in ("fastapi", "uvicorn") if _cli.find_spec(m) is None]
    if missing:
        return _Check(
            "server-extra",
            "warn",
            f"缺 {'/'.join(missing)}——`uv sync --extra server`"
            "（或 pip install 'texlate[server]'），texlate web 不可用",
        )
    return _Check("server-extra", "ok", "fastapi/uvicorn 可 import")


def _doc_babeldoc() -> _Check:
    """babeldoc——PDF 降级通路可选件；缺席 n/a 不算 fail。"""
    p = _cli.find_tool("babeldoc")
    if p is None:
        return _Check(
            "babeldoc",
            "n/a",
            "可选件缺席——PDF 降级通路不可用（pipx install babeldoc）",
        )
    ver = _doc_tool_version(p) or "?"
    return _Check("babeldoc", "ok", f"{ver} @ {p}")


@app.command()
def doctor() -> None:
    """环境自检：逐项 ``ok``/``warn``/``fail``/``n/a`` + 一行说明。

    覆盖：python≥3.12、编译引擎（tectonic/xelatex）、CJK 字体
    （kpsewhich/fc-list）、pdftotext、BYOK 网关连通、数据目录可写、
    server extra、babeldoc。任一 ``fail`` → 退出码 1；全
    ok/warn/n/a → 0。
    """
    checks = [
        _doc_python(),
        *_doc_engines(),
        _doc_cjk_fonts(),
        _doc_pdftotext(),
        _doc_gateway(),
        _doc_data_dir(),
        _doc_server_extra(),
        _doc_babeldoc(),
    ]
    for c in checks:
        typer.echo(f"{c.status:<4} {c.name:<12} {c.detail}")
    tally: dict[str, int] = {}
    for c in checks:
        tally[c.status] = tally.get(c.status, 0) + 1
    typer.echo(
        "—— "
        + " / ".join(f"{tally.get(s, 0)} {s}" for s in ("ok", "warn", "fail", "n/a"))
        + f"（{len(checks)} 项）"
    )
    if tally.get("fail"):
        raise typer.Exit(1)
