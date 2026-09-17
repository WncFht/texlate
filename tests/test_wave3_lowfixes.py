"""wave3 回归 LOW 修复钉。

- ``epub._sanitize_dom`` raw-text（Script/Stylesheet/TemplateString）转义幂等：
  ``&amp;`` 不再逐轮累积 ``amp;``；裸 ``&``/``<``/``>`` 仍转义保 XML 良构；
- ``l1.TsResult/TsBaseline.from_dict``：``1e999`` 类 inf 字段 ``int()`` 的
  ``OverflowError`` 归入 ``L1Error`` 通道契约，不泄内建异常；
- ``normalize.use_bundled_bibliography``：bbl 读失败只弃书目步（不连坐整文件
  手术）；幂等探针认 ``./`` 前缀与引号形；``../``/绝对 ``\\bibliography``
  按 openin_any 缺席计；
- ``arxiv.ratelimit._load``：非有限/越界状态值逐字段钳回合法域；
- ``xlat`` 外部 JSON 面（网关响应体/SSE 行/模型 slots 输出）：超深嵌套
  ``json.loads`` 的 ``RecursionError`` 收进既有坏 JSON 处理，不裸逃；
- ``arxiv.fetch._retry_delay``：有限但不可兑现的 ``Retry-After``（1e6s
  ≈11.5 天）视同 inf 归终态，不再真 ``sleep``。
"""

from __future__ import annotations

import asyncio
import json
import math
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from conftest import mk_chunk, run_pipeline
from lxml import etree

from texlate.arxiv import fetch as fetch_mod
from texlate.arxiv.fetch import Fetcher
from texlate.arxiv.ratelimit import ParkedError, RateLimiter
from texlate.compile.normalize import normalize_project, use_bundled_bibliography
from texlate.export import epub as epub_mod
from texlate.validate.l1 import L1Error, TsBaseline, TsResult
from texlate.xlat import client as xlat_client
from texlate.xlat import pipeline as pl
from texlate.xlat.client import ChatClient, MalformedResponseError, RetryableHTTPError
from texlate.xlat.retry import SLOTS_MAX_ROUNDS

# ----------------------------------------------------------------- epub raw-text


@pytest.mark.parametrize("tag", ["script", "style"])
def test_sanitize_dom_raw_text_entity_idempotent(tag: str) -> None:
    """``&amp;`` 过 ``_sanitize_dom`` 不再翻倍；二次净化输出逐字节不变。"""
    src = f'<html><body><{tag}>a = "&amp;" && b < c;</{tag}></body></html>'
    soup = BeautifulSoup(src, "html.parser")
    epub_mod._sanitize_dom(soup)  # noqa: SLF001 -- 白盒钉净化契约
    out = str(soup.find(tag))
    assert 'a = "&amp;"' in out  # 源实体不翻倍
    assert "&amp;amp;" not in out
    assert "&amp;&amp;" in out  # 裸 & 仍转义
    assert "&lt; c;" in out  # < 防提前终结
    # texlate 产出重进管线：逐字节幂等（不再累积 amp;）
    soup2 = BeautifulSoup(out, "html.parser")
    epub_mod._sanitize_dom(soup2)  # noqa: SLF001
    assert str(soup2.find(tag)) == out


def test_sanitize_dom_script_xml_semantics() -> None:
    """合法 XHTML ``&amp;`` 净化后 XML 解析仍得 ``&``——语义不变。"""
    soup = BeautifulSoup(
        '<html><body><script>a = "&amp;";</script></body></html>',
        "html.parser",
    )
    epub_mod._sanitize_dom(soup)  # noqa: SLF001
    root = etree.fromstring(str(soup).encode())
    script = root.find(".//script")
    assert script is not None
    assert script.text == 'a = "&";'


def test_sanitize_dom_raw_text_bogus_entity_literal() -> None:
    """非预定义实体转字面量：``&bogus;``/``&nbsp;`` 输出仍是良构 XML。"""
    soup = BeautifulSoup(
        "<html><body><script>a = '&bogus;' + '&nbsp;';</script></body></html>",
        "html.parser",
    )
    epub_mod._sanitize_dom(soup)  # noqa: SLF001
    root = etree.fromstring(str(soup).encode())
    text = root.find(".//script").text
    assert "&bogus;" in text
    assert "&nbsp;" in text


# ------------------------------------------------------------------ l1 from_dict


def test_ts_result_from_dict_inf_fields() -> None:
    """worker 输出 ``1e999``（JSON→inf float）→ int() OverflowError 归 L1Error。"""
    with pytest.raises(L1Error):
        TsResult.from_dict({"unclosed_math": 1e999})
    with pytest.raises(L1Error):
        TsResult.from_dict({"brace_balance": float("-inf")})


def test_ts_baseline_from_dict_inf_fields() -> None:
    """baseline 反序列化同契约硬化：inf/类型违例 → L1Error。"""
    with pytest.raises(L1Error):
        TsBaseline.from_dict({"parse_errors": 1e999})
    with pytest.raises(L1Error):
        TsBaseline.from_dict({"env_mismatches": "abc"})
    assert TsBaseline.from_dict({}) == TsBaseline()  # 正常路径不受影响


# ------------------------------------------- normalize bundled .bbl 粒度与边界


def _mk_bbl(tmp_path: Path) -> Path:
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}\n"
    )
    return tmp_path / "main.tex"


def _deny_bytes(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """让 ``target`` 的 ``read_bytes`` 抛 EACCES（chmod 在 root/ACL 环境会失效）。"""
    real_read = Path.read_bytes

    def _patched(self: Path) -> bytes:
        if self == target:
            raise PermissionError(13, "EACCES")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", _patched)


def test_bbl_unreadable_skips_bib_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bbl 在但读不动 → 书目步返回原文而非抛 OSError。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n")
    _deny_bytes(monkeypatch, tmp_path / "main.bbl")
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


def test_normalize_project_bbl_eacces_keeps_other_surgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程级实证：bbl 读失败不再连坐——转码手术仍落盘、``\\bibliography`` 保留。"""
    main = tmp_path / "main.tex"
    main.write_bytes("caf\xe9\n\\bibliography{gone}\n".encode("latin-1"))
    (tmp_path / "main.bbl").write_text("\\begin{thebibliography}{9}x\n")
    _deny_bytes(monkeypatch, tmp_path / "main.bbl")
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["rewritten"] == 1  # 转码手术没丢
    text = main.read_text()
    assert "café" in text
    assert r"\bibliography{gone}" in text  # 书目步跳过——未注入 \input


@pytest.mark.parametrize(
    "prior",
    [
        r"\input{main.bbl}",
        r"\input{./main.bbl}",
        r"\input { ./main.bbl }",
        r'\input"main.bbl"',
        r'\input"./main.bbl"',
        r"\input main.bbl",
        r"\input ./main.bbl",
        "\\input\tmain.bbl",
        r"\input main.bbl\relax",
        r"\input main.bbl trailing",
    ],
)
def test_bbl_input_probe_variants(tmp_path: Path, prior: str) -> None:
    """已注入形态（``./`` 前缀、引号形、裸名形）被幂等探针认出——不再二次注入。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n" + prior + "\n")
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


@pytest.mark.parametrize(
    "prior",
    [
        r'\input{main.bbl"',  # { 开 " 收——失配对，\@iinput 扫描错读不出本 bbl
        r'\input"main.bbl}',  # " 开 } 收——同理
        r"\input{main.bbl",  # 未闭合组
        r'\input"main.bbl',  # 未闭合引号
        r"\input main.bblx",  # 前缀撞名——真读的是 main.bblx（异文件）
        r"\input main.bbl}",  # } 是文件名成分——真读 main.bbl}
        r"\input main.bbl]",
        r"\input main.bbl_x",
        r'\input main.bbl"x"',  # " 切引号模——拼出 main.bblx
        r"\input main.bbl'x'",
        r"\inputmain.bbl",  # 控制词 \inputmain 不是 \input
    ],
)
def test_bbl_input_probe_noninput_forms_still_inject(
    tmp_path: Path, prior: str
) -> None:
    """失配对/前缀撞名/假 ``\\input`` 均非真输入——``\\bibliography`` 照换不误。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n" + prior + "\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert out.startswith("\\input{main.bbl}\n")


def test_bbl_input_probe_other_file_still_injects(tmp_path: Path) -> None:
    """``\\input{other.bbl}`` 不是本 bbl——书目位照换不误。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n\\input{other.bbl}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out


def test_bbl_bibliography_parent_ref_counts_as_missing(tmp_path: Path) -> None:
    """``\\bibliography{../outside/x}``：盘上在也按缺席计（openin_any=p 够不着）。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.bib").write_text("@article{a,title={t}}\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.bbl").write_text("\\begin{thebibliography}{9}y\n")
    main = proj / "main.tex"
    main.write_text("\\bibliography{../outside/x}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert out == "\\input{main.bbl}\n"


def test_bbl_bibliography_absolute_ref_counts_as_missing(tmp_path: Path) -> None:
    """绝对路径 .bib 盘上存在也按缺席计——同 openin_any=p 口径。"""
    bib = tmp_path / "real.bib"
    bib.write_text("@article{a,title={t}}\n")
    main = _mk_bbl(tmp_path)
    main.write_text(f"\\bibliography{{{bib}}}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out


# ----------------------------------------------------------------- ratelimit load


class _Clock:
    def __init__(self) -> None:
        self.t = 1_700_000_000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.slept.append(d)
        self.t += d


def test_load_nonfinite_and_out_of_range_state(tmp_path: Path) -> None:
    """inf/1e30/巨 park_step 状态 → 逐字段钳回：不睡爆、不炸、park 有界。"""
    state = tmp_path / "rl.json"
    state.write_text(
        json.dumps(
            {
                "day": "2020-01-01",
                "requests_today": -5,
                "buckets": {
                    "arxiv.org|content": {
                        "last_ts": float("inf"),
                        "consec_429": -3,
                        "park_until": 1e30,
                        "park_step": 2000,
                    },
                    "export.arxiv.org|api": {
                        "last_ts": 1e18,
                        "consec_429": 0,
                        "park_until": float("nan"),
                        "park_step": 0,
                    },
                },
            }
        )
    )
    clk = _Clock()
    rl = RateLimiter(state, clock=clk.now, sleep=clk.sleep)
    assert rl.requests_today == 0  # -5 → 0
    # park_until=1e30 → 钳到有界 horizon（仍视为在 park——保守不锤被罚路径）
    until = rl.parked_until("https://arxiv.org/src/x")
    assert 0 < until <= clk.t + rl.policy.park_max * 1.25
    with pytest.raises(ParkedError):
        rl.acquire("https://arxiv.org/src/x")
    assert not clk.slept  # ParkedError 先于 pacing——没有 inf 睡眠
    # export/api 桶：last_ts 1e18→钳 now、park_until NaN→0 —— 正常放行
    rl.acquire("https://export.arxiv.org/api/query")
    assert clk.slept == pytest.approx([3.05])  # 只睡一个 gap


def test_report_high_park_step_no_overflow() -> None:
    """``2**park_step`` 读侧钳 ``_PARK_STEP_MAX``——巨 step 不再 int→float 炸。"""
    clk = _Clock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    url = "https://arxiv.org/src/x"
    rl.acquire(url)
    rl._buckets["arxiv.org|content"].park_step = 5000  # noqa: SLF001 -- 构造损坏中间态
    clk.t += 4
    rl.acquire(url)
    for _ in range(2):
        rl.report(url, HTTPStatus.TOO_MANY_REQUESTS)
    assert rl.parked_until(url) > 0  # 封顶 park_max*jitter——不炸即证


# ------------------------------------------------ xlat 外部 JSON 超深嵌套防御

#: ~100KB 即撞 json C 扫描器递归上限（实测阈值 ~20000 层，此处 50000 留足余量）。
_DEEP_JSON = "[" * 50000 + "]" * 50000


def test_body_retry_after_deep_json_returns_none() -> None:
    """429 body 超深嵌套 → ``_body_retry_after`` 归 None，RecursionError 不逃逸。"""
    assert xlat_client._body_retry_after(_DEEP_JSON) is None  # noqa: SLF001


def test_classify_429_deep_json_body() -> None:
    """``classify_status`` 端到端：深 body 仍归 retryable 429、retry_after=None。"""
    err = xlat_client.classify_status(429, _DEEP_JSON, httpx.Headers())
    assert isinstance(err, RetryableHTTPError)
    assert err.retry_after is None


def test_sse_events_deep_json_line_skipped() -> None:
    """SSE ``data:`` 行超深嵌套 → 按坏行跳过（同坏 JSON 口径），不杀流。"""
    events, done = ChatClient._sse_events(f"data: {_DEEP_JSON}")  # noqa: SLF001
    assert events == []
    assert done is False


@pytest.mark.parametrize("call", ["chat", "list_models", "panel_models"])
def test_client_deep_json_success_body_is_malformed(call: str) -> None:
    """200 成功体超深嵌套 → ``MalformedResponseError``（原 RecursionError 裸逃）。

    ``chat``/``list_models``/``panel_models`` 三处 ``resp.json()`` 同型修复。
    """

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_DEEP_JSON.encode())

    async def go() -> None:
        c = ChatClient(
            "http://gw.test",
            "k",
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        if call == "chat":
            coro = c.chat("m", [{"role": "user", "content": "hi"}])
        elif call == "list_models":
            coro = c.list_models()
        else:
            coro = c.panel_models()
        with pytest.raises(MalformedResponseError):
            await coro
        await c.aclose()

    asyncio.run(go())


def test_slots_fn_deep_model_output_counts_as_bad_json() -> None:
    """slots 阶段模型吐超深 JSON → 同坏 JSON 计：``{}`` → 槽全败带反馈重问。

    修复前 ``RecursionError`` 逃逸到阶梯兜底 catch——``failures`` 不记录、
    次轮 ``slot_validation_failures`` 反馈字段缺失（钉：次轮 payload 带该字段）。
    """

    class DeepSlots(pl.MockTranslator):
        def __init__(self) -> None:
            super().__init__()
            self.slot_payloads: list[str] = []

        async def translate(
            self,
            *,
            user: str,
            response_format: dict[str, str] | None = None,
            **_kw: object,
        ) -> str:
            if response_format and response_format.get("type") == "json_object":
                self.slot_payloads.append(user)
                return _DEEP_JSON
            return "whatever"  # whole/lines 译文——validator 恒败照样进 slots

    spy = DeepSlots()
    out = run_pipeline(
        [mk_chunk("Long prose " + "x" * 400, "deep")],
        translator=spy,
        validator=lambda _s, _z: "always fails",
    )
    assert out[0].status == "fault"
    assert len(spy.slot_payloads) == SLOTS_MAX_ROUNDS  # 单批槽：每轮一次调用
    assert "slot_validation_failures" in spy.slot_payloads[1]


# ----------------------------------------------------- fetch Retry-After 上限


def test_retry_delay_huge_finite_retry_after_terminal() -> None:
    """``Retry-After: 1000000``（≈11.5 天）视同不可兑现 → 归 inf 终态不真睡。

    ≤``MAX_RETRY_AFTER_S`` 仍从其值；nan 沿用 ``max(delay, nan)=delay`` 回落。
    """
    huge = httpx.Response(429, headers={"retry-after": "1000000"})
    assert math.isinf(fetch_mod._retry_delay("https://arxiv.org/src/x", 1, huge))  # noqa: SLF001
    ok = httpx.Response(429, headers={"retry-after": "60"})
    d_ok = fetch_mod._retry_delay("https://arxiv.org/src/x", 1, ok)  # noqa: SLF001
    assert d_ok == pytest.approx(60.0)
    nan = httpx.Response(429, headers={"retry-after": "nan"})
    d = fetch_mod._retry_delay("https://arxiv.org/src/x", 1, nan)  # noqa: SLF001
    assert d == pytest.approx(10.0, rel=0.2)  # 回落 10s±20% jitter 区间


def test_request_huge_retry_after_sleeps_nothing() -> None:
    """端面实证：429+``Retry-After: 1e6`` → 不睡巨值、429 原样上交终态。"""
    clk = _Clock()

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "1000000"})

    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    resp = f._request("GET", "https://arxiv.org/src/x", {})  # noqa: SLF001
    assert resp.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert clk.slept == []  # 首请求无 pacing 等待、inf 退避 break——零睡眠
