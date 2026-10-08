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

import httpx
import typer

import texlate.cli as _cli
from texlate.cli._common import _is_file, app
from texlate.compile import toolchain


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


def _doc_gateway() -> _Check:
    """BYOK 网关连通：``GET {base}/v1/models`` 5s 探活（与 client.py 同端点）。

    配置面 = ``resolve_route()`` 决议渠道 + env 兜底（env > 渠道，与
    ``resolve_auth`` 同序）；什么都没配 → n/a。key 只进请求头，
    绝不进输出。
    """
    from texlate.server.channels import (  # noqa: PLC0415 -- 检查项内延迟载入
        ChannelStore,
    )
    from texlate.server.settings import (  # noqa: PLC0415
        env_base_url,
        env_dialect,
        env_key_for,
        validate_dialect,
    )
    from texlate.xlat.client import (  # noqa: PLC0415
        DEFAULT_BASE_URL,
        dialect_for_url,
        dialect_headers,
        normalize_base_url,
    )

    cstore = ChannelStore(toolchain.data_root())
    resolved = cstore.resolve_route()
    ch = resolved["channel"] if resolved else None
    env_url = env_base_url()
    if env_url:
        # env 换端点 → 渠道内联 key 绝不跨地址发（exfil 墙），凭据只认 env 阶梯
        base_url = env_url
        api_key = env_key_for(env_url)
    else:
        base_url = str(ch["base_url"]) if ch else ""
        api_key = str(resolved["api_key"]) if resolved else ""
    if not base_url and not api_key:
        return _Check(
            "gateway",
            "n/a",
            "未配置渠道/key——`texlate channels` 或 web 设置页配渠道"
            "（或 TEXLATE_BASE_URL/TEXLATE_API_KEY）",
        )
    base_url = normalize_base_url(base_url or DEFAULT_BASE_URL)
    # env > 渠道（同 resolve_auth 序）——非 openai 方言的 /v1/models
    # 缺席属端点形态而非配置坏，输出要带方言语境才不误诊
    try:
        dialect = env_dialect() or validate_dialect(
            str((ch or {}).get("protocol") or "auto")
        )
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
        probe.write_text("ok", encoding="utf-8", newline="")
        probe.unlink()
    except OSError as e:
        return _Check("data-dir", "fail", f"{root} 不可写：{e}")
    return _Check("data-dir", "ok", f"{root} 可写")


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


def _doc_service() -> _Check:
    """本地 web 服务实况——``service`` 动词同探测件（``_cli._probe_service`` 缝）。

    running → ok；应答实例数据目录他属 → warn（端口被别家占用）；
    pid 活但 health 不应答 → warn（起服中/卡死）；未在运行 → n/a
    （常驻服务是可选项，缺席非环境缺陷）。
    """
    st = _cli._probe_service(  # noqa: SLF001 -- 调用期解析 monkeypatch 缝（tests 打 cli._probe_service）
        toolchain.data_root()
    )
    if st.state == "running":
        if st.foreign:
            return _Check(
                "service",
                "warn",
                f"{st.url} 应答实例属 {st.foreign}（≠ {st.root}）——端口被别家占用",
            )
        age = f"，up {st.uptime}" if st.uptime else ""
        pid = f"pid {st.pid}" if st.pid is not None else "无锁"
        return _Check("service", "ok", f"v{st.version or '?'} @ {st.url}（{pid}{age}）")
    if st.state == "degraded":
        return _Check(
            "service",
            "warn",
            f"pid {st.pid} 存活但 {st.url} 不应答——起服中或卡死",
        )
    return _Check("service", "n/a", "未在运行——`texlate service start` 拉起")


def _doc_channels() -> _Check:
    """``channels.json`` 渠道静态面——只盘点不联网（探针是 ``channels test`` 的活）。

    缺席 → n/a（首个写点会 ``bootstrap`` 物化旧配置/播种缺省渠道）；
    在场 → 条数/启用数/路由决议命中；load 隔离出的 ``*-invalid-*``
    兄弟在场 → warn（坏表被 quarantine 过，值得人看一眼）。旧
    ``endpoints.json`` 残件在而 channels.json 缺席 → 待迁移件，
    按在场渠道表口径盘点并提示。
    """
    from texlate.server.channels import ChannelStore  # noqa: PLC0415 -- 同上延迟载入

    root = toolchain.data_root()
    cstore = ChannelStore(root)
    quarantined = sorted(root.glob("channels-invalid-*.json"))
    quarantined += sorted(root.glob("endpoints-invalid-*.json"))
    if not _is_file(cstore.path) and not _is_file(cstore.legacy_path):
        tail = f"；隔离残件 {len(quarantined)}" if quarantined else ""
        return _Check(
            "channels",
            "n/a" if not quarantined else "warn",
            "未建渠道——首次 `texlate channels`/web 启动时物化" + tail,
        )
    data = cstore.load()  # load 先跑——坏表此刻才改名隔离
    quarantined = sorted(root.glob("channels-invalid-*.json"))
    quarantined += sorted(root.glob("endpoints-invalid-*.json"))
    tail = f"；隔离残件 {len(quarantined)}" if quarantined else ""
    channels = data["channels"]
    enabled = sum(1 for c in channels if c.get("enabled"))
    resolved = cstore.resolve_route()
    act = str(resolved["channel"]["id"]) if resolved else ""
    route = data["route"]["channel_id"]
    return _Check(
        "channels",
        "warn" if quarantined else "ok",
        f"{len(channels)} 条渠道（{enabled} 启用）"
        + (f"，路由钉 {route}" if route != "auto" else f"，活动={act or '无命中'}")
        + tail,
    )


@app.command()
def doctor() -> None:
    """环境自检：逐项 ``ok``/``warn``/``fail``/``n/a`` + 一行说明。

    覆盖：python≥3.12、编译引擎（tectonic/xelatex）、CJK 字体
    （kpsewhich/fc-list）、pdftotext、BYOK 网关连通、数据目录可写、
    babeldoc、本地服务实况、渠道盘点。任一 ``fail`` → 退出码 1；
    全 ok/warn/n/a → 0。
    """
    checks = [
        _doc_python(),
        *_doc_engines(),
        _doc_cjk_fonts(),
        _doc_pdftotext(),
        _doc_gateway(),
        _doc_data_dir(),
        _doc_babeldoc(),
        _doc_service(),
        _doc_channels(),
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
