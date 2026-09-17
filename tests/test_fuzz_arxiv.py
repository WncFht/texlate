"""arxiv/ 非 unpack 模块对抗性 fuzz——unpack 侧由 test_fuzz_unpack.py 覆盖。

核心不变量（独立 oracle，不复用实现代码断言）：

- ``normalize_arxiv_id`` 任意输入不抛；输出 (base, ver) 满足：ver 非 None ⇒
  base 是合法 **ASCII** arXiv id 且 ver ≥ 1；两次应用必达不动点。
- ``sniff`` 只抛 ``SniffError``；kind↔payload 契约一致（PDF/UNKNOWN 无
  payload；TAR/SINGLE payload=解压字节）；``oversized`` ⇒ payload None。
- ``check_pdf_wrapper`` 不抛；``is_wrapper ⇔ has_includepdf ∧ is_stub``；
  ``is_stub ⇔ n_sections==0 ∧ body_text_bytes < cap``。
- ``strip_comments`` 不抛、行数守恒、幂等、行尾无空白。
- ``RateLimiter``：acquire 只抛 ParkedError/BudgetExhaustedError；预算计数
  不超过 daily_budget；状态文件损坏 → 干净起步不抛（ValueError 族内）。
- ``SourceCache``：``find_versions`` 不抛且输出升序；``get`` 对损坏
  meta.json 按未命中处理（docstring 契约）；commit→get round-trip；
  任何 acquire 之后缓存根不留 ``.staging-*``/``.old-*`` 残渣。
- ``Fetcher.head_src``/``acquire_source``：任意线缆响应只归约为
  HeadInfo/AcquireResult——ValueError 逃逸即崩溃路径（服务器可控字段）。
- ``fetch_metadata``/``resolve_version``/``degrade``：任意 XML/HTTP 响应
  不抛（除坏入参的 ValueError）；返回 None 或满足字段契约的对象。
- ``locate``：任意文件树不抛；main ∈ candidates、order 无重复且以 main
  开头、dead_files == nodes ∖ order、edges ⊆ fileset、warning 前缀已登记；
  同树两次调用结果全等（进程内确定性）。

全离线：一律 ``httpx.MockTransport`` + 注入 clock/sleep，零真网络零真等待。
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import math
import random
import re
import tarfile
import time
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from conftest import make_targz

from texlate.arxiv._texutil import strip_comments
from texlate.arxiv.cache import CacheError, SourceCache
from texlate.arxiv.fetch import (
    DL_CAP,
    AcquireResult,
    AcquireStatus,
    Fetcher,
    HeadInfo,
    _parse_head,
    _retry_delay,
    _valid_id,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.arxiv.locate import DocKind, LocateResult, _norm_arg, locate
from texlate.arxiv.meta import (
    DegradeReason,
    DegradeTier,
    PaperMeta,
    _rfc822_to_iso,
    degrade,
    fetch_metadata,
    resolve_version,
)
from texlate.arxiv.ratelimit import (
    DAILY_BUDGET,
    BudgetExhaustedError,
    ParkedError,
    RateLimiter,
    jitter,
    path_class,
)
from texlate.arxiv.sniff import (
    BlobKind,
    SniffError,
    SniffResult,
    check_pdf_wrapper,
    sniff,
)

_SEED = 0xA217
_NORM_ITERS = 2000
_SNIFF_ITERS = 800
_WRAP_ITERS = 500
_STRIP_ITERS = 400
_RL_OPS = 400
_CACHE_ITERS = 300
_HEAD_ITERS = 400
_ACQ_ITERS = 150
_META_ITERS = 400
_LOCATE_TREES = 120
_GZIP_CAP = 4096
_INT_DIGIT_CAP = 4300  # sys.get_int_max_str_digits() 默认上限
_MAX_ATTEMPTS = 4  # len(RETRY_DELAYS)+1
_MULTI_ROOT_MIN = 2
_J_LO = 0.8
_J_HI = 1.2
_J2_LO = 0.5
_J2_HI = 1.5
_OAI_LATEST = 3  # _OAI_OK 版本史 v1/v3/v2 的真最新版

# 概率旋钮
_P_GZIP_MAGIC = 0.3
_P_PDF_MAGIC = 0.1
_P_USTAR = 0.4
_P_BINARY_BODY = 0.15
_P_SELF_INPUT = 0.2
_P_DANGLE_SYM = 0.3
_P_DIR_SYM = 0.2
_P_SEEDED = 0.3
_P_OFFLINE = 0.2
_P_OP_ACQUIRE = 0.55
_P_OP_REPORT = 0.9
_P_SEED_OK = 0.4
_P_SEED_BADJSON = 0.7
_P_HAVE_CD = 0.8
_P_HAVE_CL = 0.7
_P_HAVE_ETAG = 0.5
_P_HAVE_LM = 0.3
_HUGE_RA = 999999999.0


class _Clock:
    """注入限速器/重试的 fake 时钟：sleep 即前进，零真等待。"""

    def __init__(self) -> None:
        self.t = 1_700_000_000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.sleeps.append(d)
        self.t += d


def _no_sleep(_d: float) -> None:
    return None


def _fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    clk: _Clock,
    *,
    hosts: tuple[str, ...] = ("arxiv.org", "export.arxiv.org"),
) -> Fetcher:
    return Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        hosts=hosts,
        sleep=clk.sleep,
    )


_TINY_TEX = b"\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
_TINY_TGZ = make_targz({"main.tex": _TINY_TEX})


# ---------------------------------------------------------------- normalize

#: 随机汤 token 池——unicode 十进制数字（²٣９ 等）定向覆盖在
#: test_normalize_unicode_digit_id_rejected；其余脏字符（unicode 非数字、
#: 控制符、括号、URL 碎片）照常放。
_ID_TOKENS = (
    "1412.6980",
    "2001.00001",
    "0000.00000",
    "hep-th/9901001",
    "cond-mat/0408438",
    "nucl-ex/0203009",
    "v1",
    "v0",
    "v00",
    "v01",
    "v999",
    "v1000",
    "V2",
    ".pdf",
    ".PDF",
    "arxiv.org",
    "www.arxiv.org",
    "abs",
    "pdf",
    "src",
    "e-print",
    "html",
    "format",
    "/",
    "//",
    "..",
    ".",
    "?",
    "#",
    "%",
    "\\",
    ":",
    ";",
    " ",
    "\t",
    "\n",
    "@",
    "[",
    "]",
    "{",
    "}",
    "arXiv:",
    "arxiv :",
    "http://",
    "https://",
    "ftp://",
    "é",
    "☃",
    "αβγ",
    "x",
    "-",
    "_",
    "~",
    "=",
    "&",
    "'",
    '"',
)

_ASCII_NEW_ID = re.compile(r"^\d{4}\.\d{4,5}$", re.ASCII)
_ASCII_OLD_ID = re.compile(r"^[a-zA-Z-]+(?:\.[A-Z][a-zA-Z]+)?/\d{7}$", re.ASCII)


def _valid_id_ascii(base: str) -> bool:
    """独立 oracle：arXiv id 只可能由 ASCII 构成。"""
    return bool(_ASCII_NEW_ID.match(base) or _ASCII_OLD_ID.match(base))


def _soup(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_ID_TOKENS) for _ in range(n))


def test_fuzz_normalize_never_raises_and_contract() -> None:
    """随机汤：不抛；ver 钉出 ⇒ base 必为 ASCII 合法 id 且 ver ≥ 1。"""
    rng = random.Random(_SEED)  # noqa: S311 -- 确定性种子
    for _ in range(_NORM_ITERS):
        s = _soup(rng, rng.randint(0, 14))
        base, ver = normalize_arxiv_id(s)
        assert isinstance(base, str)
        if ver is not None:
            assert ver >= 1, (s, base, ver)
            assert _valid_id_ascii(base), (s, base, ver)


def test_fuzz_normalize_two_step_fixed_point() -> None:
    """normalize(base) 至多再产出一次 URL 前缀残留——两次应用后 base 是不动点。

    断言形式：B = normalize(normalize(s)[0])；B 的 base 再 normalize 必得
    (自身, None)。若 B 还带 ver 或 base 仍可被改写，说明前缀剥离可无限推进
    或钉版判断不自洽。
    """
    rng = random.Random(_SEED + 1)  # noqa: S311 -- 确定性种子
    for _ in range(_NORM_ITERS):
        s = _soup(rng, rng.randint(0, 12))
        b1, _v1 = normalize_arxiv_id(s)
        b2, v2 = normalize_arxiv_id(b1)
        assert v2 is None
        assert normalize_arxiv_id(b2) == (b2, None), (s, b1, b2, v2)


def test_normalize_valid_roundtrip() -> None:
    """合法 (base, ver) 钉版串 round-trip：normalize(f"{base}v{ver}") 原样回。"""
    cases = [
        ("1412.6980", 1),
        ("1412.6980", 99),
        ("2001.00001", 3),
        ("hep-th/9901001", 2),
        ("cond-mat/0408438", 1),
        ("cs.AI/0301024", 7),
        ("math.GT/0309136", 12),
    ]
    for base, ver in cases:
        assert normalize_arxiv_id(f"{base}v{ver}") == (base, ver)
        assert normalize_arxiv_id(base) == (base, None)


def test_normalize_unicode_digit_id_rejected() -> None:
    """全角/阿拉伯-印度数字 id 不应通过合法性校验（fetch.py:148-149 ``\\d``）。"""
    for s in ["２００１.００００１", "٢٠٠١.٠٠٠٠١", "１２３４.５６７８"]:
        base, _ver = normalize_arxiv_id(s)
        assert not _valid_id(base), s
    base, ver = normalize_arxiv_id("２００１.００００１v３")
    assert not (_valid_id(base) and ver is not None)


def test_normalize_unicode_digit_offline_blindness(tmp_path: Path) -> None:
    """unicode 数字 id 可 commit（entry_dir 放行）但 find_versions 全拒 →
    离线未钉版 lookup 对已存在缓存失明。

    上游 ``_valid_id`` 已按 ASCII 拒 unicode 数字 id，此不对称仅存在于缓存层
    接口面——commit 不校验 id 合法性（合法形状由上游保证），这里记录该事实。
    """
    uid = "２００１.００００１"
    cache = SourceCache(tmp_path)
    staging = cache.stage()
    (staging / "meta.json").write_text("{}", encoding="utf-8")
    entry = cache.commit(staging, uid, 1)
    assert entry.dir.is_dir()
    assert cache.get(uid, 1) is not None  # 钉版路径可达
    assert cache.find_versions(uid) == []  # glob 白名单全拒
    assert cache.get_latest(uid) is None  # 未钉版路径失明


# ---------------------------------------------------------------- sniff


def _sniff_oracle(res: SniffResult, blob: bytes, cap: int) -> None:
    assert res.raw_size == len(blob)
    if res.oversized:
        assert res.payload is None
        assert res.inflated_size is not None
        assert res.inflated_size > cap
    elif res.kind in (BlobKind.TAR, BlobKind.SINGLE):
        assert res.payload is not None
        assert res.inflated_size == len(res.payload)
    else:
        assert res.payload is None


def test_fuzz_sniff_random_blobs() -> None:
    """随机字节汤：只抛 SniffError；返回结果满足 kind↔payload 契约。"""
    rng = random.Random(_SEED + 2)  # noqa: S311 -- 确定性种子
    for _ in range(_SNIFF_ITERS):
        blob = rng.randbytes(rng.randint(0, 4000))
        if rng.random() < _P_GZIP_MAGIC:
            blob = b"\x1f\x8b" + blob  # 强制 gzip 魔数前缀
        if rng.random() < _P_PDF_MAGIC:
            blob = b"%PDF" + blob
        try:
            res = sniff(blob, max_inflated=_GZIP_CAP)
        except SniffError:
            continue
        _sniff_oracle(res, blob, _GZIP_CAP)


def test_fuzz_sniff_gzip_roundtrip() -> None:
    """gzip 往返：未超限 ⇒ payload 逐字节等于原始；tar 与否按 ustar@257 判。"""
    rng = random.Random(_SEED + 3)  # noqa: S311 -- 确定性种子
    for _ in range(300):
        payload = rng.randbytes(rng.randint(0, 3000))
        if rng.random() < _P_USTAR:
            # 在 257 偏移埋 ustar → 应判 TAR
            payload = payload[:257].ljust(257, b"\0") + b"ustar" + payload[262:]
        blob = gzip.compress(payload)
        res = sniff(blob, max_inflated=_GZIP_CAP)
        if len(payload) > _GZIP_CAP:
            assert res.oversized
            continue
        assert not res.oversized
        assert res.payload == payload
        want = BlobKind.TAR if payload[257:262] == b"ustar" else BlobKind.SINGLE
        assert res.kind is want


def test_sniff_cap_boundary() -> None:
    """解压上限边界：恰 cap 不拒，cap+1 即 oversized。"""
    exact = gzip.compress(b"x" * _GZIP_CAP)
    over = gzip.compress(b"x" * (_GZIP_CAP + 1))
    assert not sniff(exact, max_inflated=_GZIP_CAP).oversized
    assert sniff(over, max_inflated=_GZIP_CAP).oversized


def test_fuzz_sniff_mutated_gzip() -> None:
    """gzip 流字节变异：SniffError 或自洽结果，绝不抛其他异常。"""
    rng = random.Random(_SEED + 4)  # noqa: S311 -- 确定性种子
    base = bytearray(gzip.compress(b"payload-bytes" * 40))
    for _ in range(400):
        blob = bytearray(base)
        for _ in range(rng.randint(1, 8)):
            blob[rng.randrange(len(blob))] = rng.randrange(256)
        try:
            res = sniff(bytes(blob), max_inflated=_GZIP_CAP)
        except SniffError:
            continue
        _sniff_oracle(res, bytes(blob), _GZIP_CAP)


def _zlib_error_blob() -> bytes:
    """确定性 zlib.error 复现：gzip 头 10B 后 deflate 流首字节置 0。"""
    blob = bytearray(gzip.compress(b"payload-bytes" * 40))
    blob[10] = 0x00  # deflate stream 首字节 → "invalid stored block lengths"
    return bytes(blob)


def test_sniff_zlib_error_escape() -> None:
    """sniff.py:83——中段损坏 gzip 应归 SniffError，不是 zlib.error 穿透。"""
    with pytest.raises(SniffError):
        sniff(_zlib_error_blob(), max_inflated=_GZIP_CAP)


def test_acquire_corrupt_gzip_body_e2e(tmp_path: Path) -> None:
    """GET 200 + 中段损坏 gzip body → 应归 ERROR，不是崩溃。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers={
                    "content-disposition": 'attachment; filename="arXiv-2001.00001v1.tar.gz"',
                    "etag": '"E1"',
                },
            )
        return httpx.Response(HTTPStatus.OK, content=_zlib_error_blob())

    clk = _Clock()
    f = _fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


# ---------------------------------------------------------------- pdf_wrapper

_TEXT_POOL = (
    "\\documentclass{article}",
    "\\begin{document}",
    "\\end{document}",
    "\\section{A}",
    "\\subsection{B}",
    "\\includepdf{paper.pdf}",
    "\\includepdfmerge{x}",
    "% comment \\includepdf{ghost.pdf}",
    "\\begin{verbatim}\\includepdf{v}\\end{verbatim}",
    "plain text paragraph ",
    "é☃中文 ",
    "\n\n",
    "{}",
    "\\input{other}",
)


def test_fuzz_wrapper_invariants() -> None:
    """随机 TeX 文本汤：不抛；verdict 字段间逻辑恒真。"""
    rng = random.Random(_SEED + 5)  # noqa: S311 -- 确定性种子
    for _ in range(_WRAP_ITERS):
        src = "".join(rng.choice(_TEXT_POOL) for _ in range(rng.randint(0, 24)))
        cap = rng.choice([0, 1, 100, 2048])
        v = check_pdf_wrapper(src, text_cap=cap)
        assert v.is_stub == (v.n_sections == 0 and v.body_text_bytes < cap)
        assert v.is_wrapper == (v.has_includepdf and v.is_stub)
        assert v.n_sections >= 0
        assert v.body_text_bytes >= 0
        assert v.matched == sorted(set(v.matched))
        for m in v.matched:
            assert m.startswith("\\includepdf")


def test_wrapper_directed() -> None:
    """定向：includepdf+章节不判 wrapper；空正文判 stub。"""
    v = check_pdf_wrapper(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includepdf{paper.pdf}\n\\section{S}\n\\end{document}\n"
    )
    assert not v.is_wrapper
    assert v.has_includepdf
    v2 = check_pdf_wrapper(
        "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    )
    assert v2.is_stub
    assert not v2.is_wrapper


# ---------------------------------------------------------------- strip_comments


def test_fuzz_strip_comments() -> None:
    """任意文本：不抛、行数守恒、幂等、行尾无空白。"""
    rng = random.Random(_SEED + 6)  # noqa: S311 -- 确定性种子
    pieces = [*_TEXT_POOL, "%", "\\%", "%%", "\r\n", "\t", "verb|x|"]
    for _ in range(_STRIP_ITERS):
        src = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        for kv in (True, False):
            out = strip_comments(src, keep_verbatim=kv)
            assert out.count("\n") == src.count("\n")
            assert strip_comments(out, keep_verbatim=kv) == out
            for line in out.split("\n"):
                assert line == line.rstrip()


# ---------------------------------------------------------------- ratelimit

_RL_URLS = (
    "https://arxiv.org/src/2001.00001",
    "https://arxiv.org/pdf/2001.00001",
    "https://export.arxiv.org/api/query?id_list=x",
    "https://export.arxiv.org/src/1412.6980",
    "https://oaipmh.arxiv.org/oai?verb=GetRecord",
    "https://arxiv.org/abs/2001.00001",
    "https://weird.example.com/other/path",
    "not-a-url",
    "https://arxiv.org",
)
_RL_STATUSES = (200, 200, 200, 301, 404, 406, 429, 500, 502, 503, 999, 0)


def test_fuzz_path_class() -> None:
    """任意 path → 四类之一；不抛。"""
    rng = random.Random(_SEED + 7)  # noqa: S311 -- 确定性种子
    chars = "/abcdefghijklmnopqrstuvwxyz.?=&%"
    for _ in range(1000):
        p = "".join(rng.choice(chars) for _ in range(rng.randint(0, 30)))
        assert path_class(p) in {"api", "oai", "content", "other"}
    assert path_class("") == "other"
    assert path_class("/api") == "api"
    assert path_class("/oai2") == "oai"
    assert path_class("/src/x") == "content"


def test_fuzz_jitter_bounds() -> None:
    """jitter 确定性且恒在 [1-span, 1+span]。"""
    rng = random.Random(_SEED + 8)  # noqa: S311 -- 确定性种子
    for _ in range(500):
        seed = str(rng.random())
        j1, j2 = jitter(seed), jitter(seed)
        assert j1 == j2
        assert _J_LO <= j1 <= _J_HI
        assert _J2_LO <= jitter(seed, span=0.5) <= _J2_HI


def test_fuzz_ratelimit_ops() -> None:
    """随机 acquire/report/clock 推进：异常集封闭 + 预算上界 + park 自洽。"""
    rng = random.Random(_SEED + 9)  # noqa: S311 -- 确定性种子
    clk = _Clock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    for _ in range(_RL_OPS):
        op = rng.random()
        url = rng.choice(_RL_URLS)
        if op < _P_OP_ACQUIRE:
            try:
                rl.acquire(url)
            except ParkedError:
                assert rl.parked_until(url) > clk.t
            except BudgetExhaustedError:
                assert rl.requests_today >= DAILY_BUDGET
        elif op < _P_OP_REPORT:
            rl.report(url, rng.choice(_RL_STATUSES))
        else:
            clk.t += rng.choice([0.0, 1.0, 60.0, 4000.0, 90000.0])
        assert 0 <= rl.requests_today <= DAILY_BUDGET
        p = rl.parked_until(url)
        assert p == 0.0 or p > clk.t


def test_ratelimit_state_roundtrip(tmp_path: Path) -> None:
    """状态落盘→重载：同日同计数、桶位一致。"""
    clk = _Clock()
    sp = tmp_path / "rl.json"
    rl = RateLimiter(sp, clock=clk.now, sleep=clk.sleep)
    for url in _RL_URLS[:5]:
        rl.acquire(url)
        rl.report(url, 200)
    rl.report(_RL_URLS[0], 429)
    rl.report(_RL_URLS[0], 429)  # 触发 park
    rl2 = RateLimiter(sp, clock=clk.now, sleep=clk.sleep)
    assert rl2.requests_today == rl.requests_today
    assert rl2.parked_until(_RL_URLS[0]) == rl.parked_until(_RL_URLS[0])


def test_fuzz_ratelimit_corrupt_state(tmp_path: Path) -> None:
    """损坏状态文件（非法 JSON/错型/浮点溢出/垃圾字节）→ 干净起步，不抛。"""
    rng = random.Random(_SEED + 10)  # noqa: S311 -- 确定性种子
    blobs = [
        b"",
        b"{}",
        b"[]",
        b"null",
        b'"str"',
        b"{",
        b'{"day": 123}',
        b'{"requests_today": "abc"}',
        b'{"requests_today": -5}',
        b'{"requests_today": 1e20}',
        b'{"requests_today": 1e999}',
        b'{"buckets": []}',
        b'{"buckets": {"k": 5}}',
        b'{"buckets": {"h|c": {"park_until": "x"}}}',
        b'{"buckets": {"h|c": {"park_until": 1e999}}}',
        b'{"buckets": {"h|c": {"last_ts": -1}}}',
        b'{"buckets": {"h|c": {"consec_429": "2"}}}',
        b'{"buckets": {"h|c": {"consec_429": 1e999}}}',
        b'{"buckets": {"h|c": {"park_step": 1e999}}}',
        b"\xff\xfe corrupt bytes",
    ]
    for i, blob in enumerate(blobs):
        sp = tmp_path / f"rl{i}.json"
        sp.write_bytes(blob)
        RateLimiter(sp, clock=_Clock().now, sleep=_no_sleep)
    for i in range(200):
        sp = tmp_path / f"rz{i}.json"
        sp.write_bytes(rng.randbytes(rng.randint(0, 200)))
        RateLimiter(sp, clock=_Clock().now, sleep=_no_sleep)


def test_ratelimit_state_float_overflow(tmp_path: Path) -> None:
    """ratelimit.py:143/148——``int(float('inf'))`` 逃逸损坏容错。"""
    for field in ("requests_today", "consec_429", "park_step"):
        sp = tmp_path / f"{field.replace('_', '')}.json"
        if field == "requests_today":
            sp.write_text(json.dumps({"requests_today": 1e999}), encoding="utf-8")
        else:
            sp.write_text(
                json.dumps({"buckets": {"h|c": {field: 1e999}}}), encoding="utf-8"
            )
        RateLimiter(sp, clock=_Clock().now, sleep=_no_sleep)


def test_ratelimit_day_rollover_resets_budget() -> None:
    """跨日推进：预算归零重来。"""
    clk = _Clock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    rl.acquire("https://arxiv.org/src/x")  # 建立当日 _day 锚
    rl._requests_today = DAILY_BUDGET  # noqa: SLF001 -- 铺当日满额
    with pytest.raises(BudgetExhaustedError):
        rl.acquire("https://arxiv.org/src/y")
    clk.t += 90000.0  # 跨日（1.7e9 UTC 22:13 → +25h 必过零点）
    rl.acquire("https://arxiv.org/src/z")  # 不抛即过


# ---------------------------------------------------------------- cache


def test_fuzz_find_versions_never_raises(tmp_path: Path) -> None:
    """任意 id 字符串：find_versions 不抛、输出升序非负 int。"""
    rng = random.Random(_SEED + 11)  # noqa: S311 -- 确定性种子
    cache = SourceCache(tmp_path)
    for name in ["2001.00001v1", "2001.00001v3", "2001.00001v2", "xv", "v9", ".v4"]:
        (tmp_path / name).mkdir()
    for _ in range(_CACHE_ITERS):
        i = _soup(rng, rng.randint(0, 10))
        vs = cache.find_versions(i)
        assert vs == sorted(set(vs))
        assert all(isinstance(v, int) and v >= 0 for v in vs)
    assert cache.find_versions("2001.00001") == [1, 2, 3]
    # "/" 前导与 glob 元字符全拒
    assert cache.find_versions("/etc") == []
    assert cache.find_versions("*") == []
    assert cache.find_versions("a/*/b") == []


def test_fuzz_cache_get_corrupt_meta(tmp_path: Path) -> None:
    """meta.json 任意字节垃圾（含非 UTF-8）→ miss 或合法 entry，绝不抛。"""
    rng = random.Random(_SEED + 12)  # noqa: S311 -- 确定性种子
    cache = SourceCache(tmp_path)
    d = tmp_path / "2001.00001v1"
    d.mkdir()
    for _ in range(_CACHE_ITERS):
        blob = rng.randbytes(rng.randint(0, 300))
        (d / "meta.json").write_bytes(blob)
        e = cache.get("2001.00001", 1)
        if e is not None:
            assert e.arxiv_id == "2001.00001"
            assert e.resolved_version == 1
            assert isinstance(e.meta, dict)


def test_cache_get_nonutf8_meta_crashes(tmp_path: Path) -> None:
    """cache.py 缺陷钉：非 UTF-8 损坏条目应按未命中返回 None。"""
    cache = SourceCache(tmp_path)
    d = tmp_path / "2001.00001v1"
    d.mkdir()
    (d / "meta.json").write_bytes(b'{"etag": "\xff\xfe not utf8"}')
    assert cache.get("2001.00001", 1) is None


def test_acquire_corrupt_meta_crash_e2e(tmp_path: Path) -> None:
    """在线臂：HEAD 200 → cache.get 崩；离线臂：get/get_latest 同崩。"""
    cache = SourceCache(tmp_path)
    d = tmp_path / "2001.00001v1"
    d.mkdir(parents=True)
    (d / "meta.json").write_bytes(b"\xff\xfe")

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            HTTPStatus.OK,
            headers={
                "content-disposition": 'attachment; filename="arXiv-2001.00001v1.tar.gz"',
                "etag": '"E1"',
            },
        )

    clk = _Clock()
    f = _fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.ERROR  # 期望：损坏条目归 error 而非崩

    res_off = acquire_source("2001.00001", fetcher=f, cache=cache, offline=True)
    assert res_off.status is AcquireStatus.ERROR


def test_fuzz_cache_commit_roundtrip(tmp_path: Path) -> None:
    """stage→写 meta→commit→get：meta 原样回读；目录名恒 {id}v{ver}；无残渣。"""
    rng = random.Random(_SEED + 13)  # noqa: S311 -- 确定性种子
    cache = SourceCache(tmp_path)
    ids = ["2001.00001", "hep-th/9901001", "cond-mat/0408438", "a.b/1234567"]
    for _ in range(60):
        aid = rng.choice(ids)
        ver = rng.randint(1, 9)
        meta = {
            "arxiv_id": aid,
            "resolved_version": ver,
            "etag": f'"E{rng.randint(0, 999)}"',
            "status": rng.choice(["ok", "pdf_only", "unknown_format"]),
            "warnings": [str(rng.random())],
        }
        staging = cache.stage()
        (staging / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        (staging / "raw.bin").write_bytes(rng.randbytes(64))
        entry = cache.commit(staging, aid, ver)
        assert entry.dir.name == f"{aid.split('/')[-1]}v{ver}"
        assert entry.dir.resolve().is_relative_to(tmp_path.resolve())
        back = cache.get(aid, ver)
        assert back is not None
        assert back.meta == meta
    leftovers = [
        p.name for p in tmp_path.iterdir() if p.name.startswith((".staging-", ".old-"))
    ]
    assert leftovers == []


def test_cache_entry_dir_escape_matrix(tmp_path: Path) -> None:
    """逃逸形 id 一律 CacheError；折回形/合法形必给 root 内路径。

    ``..`` 折回不逃逸不拒（``..v1`` 是字面名、``a/../b`` 归一回 root 内）
    ——守卫语义是 resolve 后判 is_relative_to，不是文本段检查。
    """
    cache = SourceCache(tmp_path)
    for bad in ("../x", "a/../../b", "/etc/passwd"):
        with pytest.raises(CacheError):
            cache.entry_dir(bad, 1)
    for inside in ("..", "a/../b", "x/./y", "2001.00001", "hep-th/9901001"):
        d = cache.entry_dir(inside, 1)
        assert d.resolve().is_relative_to(tmp_path.resolve())


# ---------------------------------------------------------------- head/parse 层

_CD_TOKENS = (
    'attachment; filename="arXiv-2001.00001v2.tar.gz"',
    'attachment; filename="arXiv-2001.00001v9.gz"',
    'attachment; filename="arXiv-2001.00001v3.pdf"',
    'attachment; filename="arXiv-2001.00001V2.TAR.GZ"',
    'attachment; filename="arXiv-2001.00001v0.tar.gz"',
    "attachment",
    "",
    'filename="x.tar.gz"',
    "attachment; filename*=utf8''arXiv-2001.00001v4.tar.gz",
    'attachment; filename="a"; filename="arXiv-2001.00001v5.tar.gz"',
    'attachment; filename="arXiv-2001.00001v7.tar.gz.bak"',
    'attachment; filename="no-version.tar.gz"',
    'attachment; filename="arXiv-hep-th/9901001v2.tar.gz"',
    'inline; filename="v12.pdf"',
)
_CL_TOKENS = ("", "0", "1", "1234", "abc", "12.5", "-5", " 12", "9" * 300, "1e6")
_ETAG_TOKENS = ('"E1"', "", "weak", 'W/"x"')


def _head_oracle(head: HeadInfo, url: str) -> None:
    assert isinstance(head, HeadInfo)
    assert head.kind_hint in {"", "tar.gz", "gz", "pdf"}
    assert head.url == url
    if head.resolved_version is not None:
        assert head.resolved_version >= 0  # cd v0 会产出 0——记录但不为难
    if head.content_length is not None:
        assert head.too_large == (head.content_length > DL_CAP)
    for wstr in (head.cd_filename, head.etag, head.last_modified):
        wstr.encode("utf-8", "surrogatepass")  # header 文本可编码性


def test_fuzz_parse_head() -> None:
    """随机 header 组合的 _parse_head：不抛 + 字段契约。"""
    rng = random.Random(_SEED + 14)  # noqa: S311 -- 确定性种子
    url = "https://arxiv.org/src/2001.00001"
    for _ in range(_HEAD_ITERS):
        headers: dict[str, str] = {}
        if rng.random() < _P_HAVE_CD:
            headers["content-disposition"] = rng.choice(_CD_TOKENS)
        if rng.random() < _P_HAVE_CL:
            headers["content-length"] = rng.choice(_CL_TOKENS)
        if rng.random() < _P_HAVE_ETAG:
            headers["etag"] = rng.choice(_ETAG_TOKENS)
        if rng.random() < _P_HAVE_LM:
            headers["last-modified"] = "Wed, 01 Jan 2020 00:00:00 GMT"
        resp = httpx.Response(rng.choice([200, 301, 404, 500]), headers=headers)
        pin = rng.choice([None, 1, 7])
        _head_oracle(_parse_head(resp, url, pin), url)


def test_head_cd_version_overflow_e2e(tmp_path: Path) -> None:
    """fetch.py:192——恶意 cd filename ``v``+5000 位 → acquire 应归 ERROR。"""
    cd = (
        'attachment; filename="arXiv-2001.00001v'
        + "9" * (_INT_DIGIT_CAP + 700)
        + '.tar.gz"'
    )

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(HTTPStatus.OK, headers={"content-disposition": cd})

    clk = _Clock()
    f = _fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


def test_get_cd_version_overflow_e2e(tmp_path: Path) -> None:
    """HEAD 干净、GET 的 cd 带 5000 位版本 → _body_result→_refresh_head 崩。"""
    good_cd = 'attachment; filename="arXiv-2001.00001v1.tar.gz"'
    evil_cd = (
        'attachment; filename="arXiv-2001.00001v'
        + "9" * (_INT_DIGIT_CAP + 700)
        + '.tar.gz"'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers={"content-disposition": good_cd, "etag": '"E1"'},
            )
        return httpx.Response(
            HTTPStatus.OK, content=_TINY_TGZ, headers={"content-disposition": evil_cd}
        )

    clk = _Clock()
    f = _fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


def test_head_cl_unicode_digit() -> None:
    """fetch.py:197——latin-1 ``²`` 经 bytes header 进入（isdigit 真、int 假）。

    真 wire 上 h11 对 CL 有帧校验会先拒；MockTransport/自定义 client（Fetcher
    公开注入点）可达。修法规整：``int()`` 包 try 或改 ``cl.isascii() and
    cl.isdigit()``。
    """
    resp = httpx.Response(200, headers=[(b"content-length", b"\xb2")])
    head = _parse_head(resp, "https://arxiv.org/src/x", None)
    assert head.content_length is None  # 期望：判不出就当没有


def test_retry_after_inf_crashes(tmp_path: Path) -> None:
    """429 + ``Retry-After: 1e999`` → 首次重试即 OverflowError 逃逸。"""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            HTTPStatus.TOO_MANY_REQUESTS, headers={"retry-after": "1e999"}
        )

    clk = _Clock()
    f = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        hosts=("arxiv.org",),
        sleep=time.sleep,  # 真 sleep——inf 立刻 OverflowError，不会真等
    )
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR  # 期望归类，不是崩


def test_retry_delay_bounded_ra() -> None:
    """Retry-After 巨大有限值按现规格从其值（无封顶——观察项，不是缺陷钉）。"""
    resp = httpx.Response(429, headers={"retry-after": "999999999"})
    assert _retry_delay("https://x/", 1, resp) == _HUGE_RA
    resp2 = httpx.Response(429, headers={"retry-after": "nan"})
    assert math.isfinite(_retry_delay("https://x/", 1, resp2))
    resp3 = httpx.Response(429, headers={"retry-after": "abc"})
    assert math.isfinite(_retry_delay("https://x/", 1, resp3))


# ---------------------------------------------------------------- acquire e2e

_BODY_KINDS = ("targz", "single_gz", "pdf", "garbage", "corrupt_gz", "empty", "rawtar")


def _raw_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("main.tex")
        info.size = len(_TINY_TEX)
        tf.addfile(info, io.BytesIO(_TINY_TEX))
    return buf.getvalue()


def _body_for(kind: str, rng: random.Random) -> bytes:
    body = rng.randbytes(rng.randint(1, 200))
    if kind == "targz":
        body = _TINY_TGZ
    elif kind == "single_gz":
        body = gzip.compress(_TINY_TEX)
    elif kind == "pdf":
        body = b"%PDF-1.4 fake " + rng.randbytes(32)
    elif kind == "corrupt_gz":
        body = b"\x1f\x8b" + rng.randbytes(64)
    elif kind == "rawtar":
        body = _raw_tar()
    elif kind == "empty":
        body = b""
    return body


_ACQ_IDS = (
    "2001.00001",
    "2001.00001v2",
    "1412.6980",
    "hep-th/9901001",
    "cond-mat/0408438",
    "a/../b",  # bad id → ERROR 臂
    "",
    "99999.999999",  # 形状非法（5+6 位）
)
_HEAD_STATUS = (200, 200, 200, 301, 404, 406, 429, 500, 503)
_GET_STATUS = (200, 200, 200, 200, 304, 404, 406, 429, 500)
_ENTRY_STATUSES = {
    AcquireStatus.OK,
    AcquireStatus.HIT,
    AcquireStatus.PDF_ONLY,
    AcquireStatus.UNKNOWN_FORMAT,
}


def _seed_cache(cache: SourceCache, aid: str, ver: int, rng: random.Random) -> None:
    """预铺合法或损坏（UTF-8 可解码）的缓存条目。"""
    d = cache.root / f"{aid}v{ver}"
    d.mkdir(parents=True, exist_ok=True)
    shape = rng.random()
    if shape < _P_SEED_OK:
        (d / "meta.json").write_text(
            json.dumps({"etag": '"SEED"', "status": "ok"}), encoding="utf-8"
        )
    elif shape < _P_SEED_BADJSON:
        (d / "meta.json").write_text("{bad json", encoding="utf-8")
    else:
        (d / "meta.json").write_text("[1,2,3]", encoding="utf-8")


def test_fuzz_acquire_source_scenarios(tmp_path: Path) -> None:
    """端到端情景 fuzz：任意响应组合 → 归约 AcquireResult 不崩 + 缓存不变量。

    前崩溃面（非 UTF-8 meta / 4300+ 位版本 / unicode CL / inf Retry-After /
    zlib.error）已由定向用例覆盖——现一律归 ERROR，不再穿透分类网。
    """
    rng = random.Random(_SEED + 15)  # noqa: S311 -- 确定性种子
    for i in range(_ACQ_ITERS):
        aid = rng.choice(_ACQ_IDS)
        head_status = rng.choice(_HEAD_STATUS)
        get_status = rng.choice(_GET_STATUS)
        body = _body_for(rng.choice(_BODY_KINDS), rng)
        ver = rng.randint(1, 4)
        etag = f'"E{rng.randint(0, 3)}"'
        cd = f'attachment; filename="arXiv-2001.00001v{ver}.tar.gz"'
        if "hep-th" in aid:
            cd = f'attachment; filename="arXiv-hep-th_9901001v{ver}.tar.gz"'
        root = tmp_path / f"i{i}"
        cache = SourceCache(root)
        if rng.random() < _P_SEEDED:
            cache.root.mkdir(parents=True, exist_ok=True)
            _seed_cache(cache, "2001.00001", ver, rng)
        offline = rng.random() < _P_OFFLINE

        def handler(
            req: httpx.Request,
            _s: int = head_status,
            _g: int = get_status,
            _b: bytes = body,
            _cd: str = cd,
            _e: str = etag,
        ) -> httpx.Response:
            if req.method == "HEAD":
                return httpx.Response(
                    _s, headers={"content-disposition": _cd, "etag": _e}
                )
            return httpx.Response(_g, content=_b, headers={"etag": _e})

        clk = _Clock()
        f = _fetcher(handler, clk)
        res = acquire_source(aid, fetcher=f, cache=cache, offline=offline)
        # —— 结果契约 ——
        assert isinstance(res, AcquireResult)
        assert res.status in AcquireStatus
        if res.status in _ENTRY_STATUSES:
            assert res.entry is not None
            assert res.entry.dir.is_dir()
            meta = json.loads((res.entry.dir / "meta.json").read_text("utf-8"))
            if meta.get("arxiv_id") is not None:
                # 本 run commit 的条目（预铺的缺字段）才全量断言
                assert meta["arxiv_id"] == res.arxiv_id
                assert meta["resolved_version"] == res.resolved_version
                datetime.strptime(meta["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=UTC
                )
        else:
            assert res.entry is None
        # —— 无 staging/old 残渣 ——
        if root.exists():
            leftovers = [
                p.name
                for p in root.iterdir()
                if p.name.startswith((".staging-", ".old-"))
            ]
            assert not leftovers, (i, res.status, leftovers)


def test_acquire_retry_attempt_cap() -> None:
    """瞬态码重试上界：单 host 至多 len(RETRY_DELAYS)+1 次请求。

    顺带钉住语义：failover 只对异常/park 发生——瞬态 status 不触发换 host
    （docs/06 §1.3：park 键是 (host,path) 桶，未 park 的 host 不换）。
    """
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        return httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE)

    clk = _Clock()
    f = _fetcher(handler, clk, hosts=("arxiv.org", "export.arxiv.org"))
    head = f.head_src("2001.00001")
    assert head.http_status == HTTPStatus.SERVICE_UNAVAILABLE
    assert calls == ["arxiv.org"] * _MAX_ATTEMPTS
    assert len(clk.sleeps) <= _MAX_ATTEMPTS - 1


# ---------------------------------------------------------------- meta 层

_ATOM_OK = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2001.00001v2</id>
    <title>T</title><summary>S</summary>
    <author><name>A One</name></author>
    <published>2020-01-01T00:00:00Z</published>
    <updated>2020-01-02T00:00:00Z</updated>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <link rel="alternate" href="http://arxiv.org/abs/2001.00001v2"/>
    <link title="pdf" rel="related" href="http://arxiv.org/pdf/2001.00001v2"/>
  </entry>
</feed>"""

_OAI_OK = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><metadata>
  <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
   <id>2001.00001</id><title>T</title><authors>A and B</authors>
   <categories>cs.LG</categories>
   <version version="v1"><date>Wed, 01 Jan 2020 00:00:00 GMT</date><size>1kb</size></version>
   <version version="v3"><date>Thu, 02 Jan 2020 00:00:00 GMT</date><size>2kb</size></version>
   <version version="v2"><date>Thu, 02 Jan 2020 00:00:01 GMT</date><size>2kb</size></version>
  </arXivRaw>
 </metadata></record></GetRecord>
</OAI-PMH>"""

_ENTITY_BOMB = (
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "'
    + b"x" * 500
    + b'"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    + b'"><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2001.00001v1</id>'
    + b"<title>&c;&c;&c;&c;</title></entry></feed>"
)

_META_BODIES = (
    _ATOM_OK.encode(),
    _OAI_OK.encode(),
    _ENTITY_BOMB,
    b"",
    b"<",
    b"not xml at all",
    b'<?xml version="1.0"?><feed/>',
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Error</title><id>http://arxiv.org/api/errors</id></entry></feed>',
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>garbage</id></entry></feed>',
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2001.00001v5000</id><title>x</title></entry></feed>',
    b'<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="idDoesNotExist">x</error></OAI-PMH>',
    b'<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><header status="deleted"/></record></GetRecord></OAI-PMH>',
    b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>http://arxiv.org/abs/\xef\xbf\xbdv1</id></entry></feed>",
)


def _meta_handler(
    atom_body: bytes,
    oai_body: bytes,
    *,
    atom_status: int = 200,
    oai_status: int = 200,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/query" in req.url.path:
            return httpx.Response(atom_status, content=atom_body)
        if req.url.path == "/oai":
            return httpx.Response(oai_status, content=oai_body)
        return httpx.Response(HTTPStatus.NOT_FOUND)

    return handler


def _check_paper_meta(m: PaperMeta | None) -> None:
    if m is None:
        return
    assert m.source in {"atom", "oai-raw"}
    assert m.arxiv_id
    if m.resolved_version is not None:
        assert m.resolved_version >= 1
    if m.latest_version is not None:
        assert m.latest_version >= 1
    vers = [v.version for v in m.versions]
    assert vers == sorted(vers)
    for a in m.authors:
        assert isinstance(a, str)


def test_fuzz_fetch_metadata_bodies() -> None:
    """Atom/OAI 任意响应体组合：None 或合法 PaperMeta，绝不抛。"""
    rng = random.Random(_SEED + 16)  # noqa: S311 -- 确定性种子
    for _ in range(_META_ITERS):
        atom = rng.choice(_META_BODIES)
        oai = rng.choice(_META_BODIES)
        astat = rng.choice([200, 200, 200, 404, 500])
        ostat = rng.choice([200, 200, 404])
        clk = _Clock()
        f = _fetcher(_meta_handler(atom, oai, atom_status=astat, oai_status=ostat), clk)
        m = fetch_metadata("2001.00001", fetcher=f)
        _check_paper_meta(m)


def test_fetch_metadata_bomb_falls_back_to_oai() -> None:
    """实体炸弹打 Atom → defusedxml 拦 → OAI 兜底仍出结果。"""
    clk = _Clock()
    f = _fetcher(_meta_handler(_ENTITY_BOMB, _OAI_OK.encode()), clk)
    m = fetch_metadata("2001.00001", fetcher=f)
    assert m is not None
    assert m.source == "oai-raw"
    assert m.latest_version == _OAI_LATEST


def test_fuzz_resolve_version_contract() -> None:
    """resolve_version：want 给定时结果 ∈ {want, None}；裸调 ∈ {None, ≥1}。"""
    rng = random.Random(_SEED + 17)  # noqa: S311 -- 确定性种子
    for _ in range(200):
        atom = rng.choice(_META_BODIES)
        oai = rng.choice(_META_BODIES)
        clk = _Clock()
        f = _fetcher(_meta_handler(atom, oai), clk)
        want = rng.choice([None, 1, 2, 3, 99])
        got = resolve_version("2001.00001", want, fetcher=f)
        if want is None:
            assert got is None or got >= 1
        else:
            assert got in {want, None}


def _degrade_fetcher(statuses: dict[str, int], clk: _Clock) -> Fetcher:
    def handler(req: httpx.Request) -> httpx.Response:
        for prefix, st in statuses.items():
            if req.url.path.startswith(prefix):
                if st == HTTPStatus.MOVED_PERMANENTLY:
                    return httpx.Response(
                        HTTPStatus.MOVED_PERMANENTLY,
                        headers={"location": str(req.url) + "v2"},
                    )
                return httpx.Response(st)
        if "/api/query" in req.url.path or req.url.path == "/oai":
            return httpx.Response(HTTPStatus.OK, content=_ATOM_OK.encode())
        return httpx.Response(HTTPStatus.NOT_FOUND)

    return Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ),
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )


def test_fuzz_degrade_contract() -> None:
    """degrade：任意原因串 + 随机 HEAD 结局 → 契约一致或 ValueError（坏入参）。"""
    rng = random.Random(_SEED + 18)  # noqa: S311 -- 确定性种子
    valid = {r.value for r in DegradeReason}
    reasons = [*sorted(valid), "bogus", "", "PDF_ONLY ", "stub!"]
    for _ in range(200):
        reason = rng.choice(reasons)
        statuses = {
            "/html/": rng.choice(
                [
                    HTTPStatus.OK,
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                ]
            ),
            "/pdf/": rng.choice(
                [
                    HTTPStatus.OK,
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.NOT_FOUND,
                    HTTPStatus.MOVED_PERMANENTLY,
                ]
            ),
        }
        clk = _Clock()
        f = _degrade_fetcher(statuses, clk)
        version = rng.choice([None, 1, 3])
        if reason not in valid:
            with pytest.raises(ValueError, match="is not a valid DegradeReason"):
                degrade("2001.00001", fetcher=f, reason=reason, version=version)
            continue
        res = degrade("2001.00001", fetcher=f, reason=reason, version=version)
        assert res.arxiv_id == "2001.00001"
        if res.tier is DegradeTier.NONE:
            assert res.url == ""
        else:
            assert res.url.startswith("http")
            assert ("/html/" in res.url) == (res.tier is DegradeTier.HTML)
        if res.version is not None:
            assert res.version >= 1
        for p in res.probed:
            assert isinstance(p, str)


def test_fuzz_rfc822_to_iso() -> None:
    """任意日期串：不抛；输出要么原样、要么 ISO Z 形。"""
    rng = random.Random(_SEED + 19)  # noqa: S311 -- 确定性种子
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    pool = (
        "Wed, 01 Jan 2020 00:00:00 GMT",
        "Mon, 32 Dec 2014 13:54:29 GMT",
        "garbage",
        "",
        "2014-12-22",
        "Fri, 99 Foo 99999 99:99:99 XXX",
        "1 Jan 2020",
        "é☃",
        "Mon, 22 Dec 2014 13:54:29 +0800",
        "Mon, 22 Dec 2014 13:54:29",
    )
    for _ in range(600):
        s = rng.choice(pool) + rng.choice(["", " ", "x"])
        out = _rfc822_to_iso(s)
        assert out == s or iso.fullmatch(out), (s, out)


# ---------------------------------------------------------------- locate

_LOCATE_NAMES = (
    "main.tex",
    "paper.tex",
    "ms.tex",
    "2001.00001.tex",
    "other.tex",
    "inc1.tex",
    "sub/inc2.tex",
    "sub/deep/inc3.tex",
    "sp ace.tex",
    "UPPER.TEX",
    "x.ltx",
    "y.latex",
    "plain.tex",
    "figs/g.eps",
    "refs.bib",
    "main.bbl",
    "noext",
    "README",
    "üñí.tex",
)

_LOCATE_SNIPPETS = (
    "\\documentclass{article}\n",
    "\\documentclass[11pt]{revtex}\n",
    "\\documentstyle{article}\n",
    "\\begin{document}\n",
    "\\end{document}\n",
    "\\section{S}\n",
    "body text paragraph here\n",
    "\\bye\n",
    "\\starttext\n",
    "% \\documentclass{commented}\n",
    "\\begin{verbatim}\n\\documentclass{fake}\n\\input{fake}\n\\end{verbatim}\n",
    "\\begin{comment}\n\\documentclass{fake2}\n\\end{comment}\n",
    "\\input{inc1}\n",
    "\\input{inc1.tex}\n",
    "\\input inc1\n",
    "\\include{sub/inc2}\n",
    "\\import{sub}{inc2}\n",
    "\\subimport{sub}{deep/inc3}\n",
    "\\InputIfFileExists{missing}{\\typeout{y}}{}\n",
    "\\input{/abs/path}\n",
    "\\input{../escape}\n",
    "\\input{a/../fold}\n",
    "\\bibliography{refs}\n",
    "\\bibliography{refs,missing}\n",
    "\\verb|\\input{fakeverb}|\n",
    "\n\n",
    "%%%%%\n",
)


def _build_tree(root: Path, rng: random.Random) -> None:
    names = rng.sample(list(_LOCATE_NAMES), rng.randint(1, min(14, len(_LOCATE_NAMES))))
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if rng.random() < _P_BINARY_BODY:
            p.write_bytes(rng.randbytes(rng.randint(0, 800)))
            continue
        body = "".join(rng.choice(_LOCATE_SNIPPETS) for _ in range(rng.randint(0, 14)))
        # 自环/互环 input：取树内已有名构造环
        if rng.random() < _P_SELF_INPUT and names:
            tgt = PurePosixPath(rng.choice(names)).stem
            body += f"\\input{{{tgt}}}\n"
        p.write_text(body, encoding="utf-8")
    # 对抗 symlink：dangling / 指目录
    if rng.random() < _P_DANGLE_SYM:
        with contextlib.suppress(OSError):
            (root / "dangling.tex").symlink_to("ghost.tex")
    if rng.random() < _P_DIR_SYM:
        (root / "d").mkdir(exist_ok=True)
        with contextlib.suppress(OSError):
            (root / "dlink.tex").symlink_to("d", target_is_directory=True)


_LOCATE_WARN_PREFIXES = frozenset(
    {
        "no_tex_files",
        "all_tex_unreadable",
        "no_documentclass",
        "unreadable",
        "pdf_wrapper",
        "stub_body",
        "max_depth",
        "cycle",
    }
)


def _locate_invariants(res: LocateResult) -> None:
    assert res.kind in DocKind
    for w in res.warnings:
        w.encode("utf-8")
        prefix = w.split(":", 1)[0]
        assert prefix in _LOCATE_WARN_PREFIXES, w
    if res.main is not None:
        assert res.main in res.candidates
        assert res.kind is DocKind.LATEX
        assert res.order[0] == res.main
    else:
        assert res.kind is not DocKind.LATEX or not res.candidates
    assert len(res.order) == len(set(res.order))
    assert set(res.dead_files).isdisjoint(res.order)
    nodes_in_order = set(res.order) | set(res.dead_files)
    # candidates ⊆ nodes；dead+order 覆盖全部 node
    assert set(res.candidates) <= nodes_in_order
    for src, dsts in res.edges.items():
        assert isinstance(src, str)
        for d in dsts:
            assert isinstance(d, str)
    for r in res.unresolved:
        assert r.resolved is None
    assert res.multi_doc == (len(res.independent_roots) >= _MULTI_ROOT_MIN)


def test_fuzz_locate_trees(tmp_path: Path) -> None:
    """随机文件树：不抛 + 全套结构不变量 + 进程内确定性。"""
    rng = random.Random(_SEED + 20)  # noqa: S311 -- 确定性种子
    for i in range(_LOCATE_TREES):
        root = tmp_path / f"t{i}"
        root.mkdir()
        _build_tree(root, rng)
        res = locate(root, arxiv_id="2001.00001")
        _locate_invariants(res)
        res2 = locate(root, arxiv_id="2001.00001")
        assert (
            res.main,
            res.order,
            res.edges,
            res.dead_files,
        ) == (res2.main, res2.order, res2.edges, res2.dead_files)


def test_fuzz_norm_arg() -> None:
    """\\input 参数归一化：不抛；输出恒为 POSIX 相对路径（无 .. 段、非绝对）。"""
    rng = random.Random(_SEED + 21)  # noqa: S311 -- 确定性种子
    for _ in range(1500):
        arg = _soup(rng, rng.randint(0, 8))
        out = _norm_arg(arg)
        if out is None:
            continue
        assert not out.startswith(("/", "~"))
        assert ".." not in out.split("/")
        assert "\\" not in out
        assert not PurePosixPath(out).is_absolute()


def test_locate_missing_and_file_root(tmp_path: Path) -> None:
    """root 不存在/是文件：返回 no_tex_files 而非抛。"""
    res = locate(tmp_path / "nonexistent")
    assert res.kind is DocKind.NONE
    f = tmp_path / "afile"
    f.write_text("x")
    res2 = locate(f)
    assert res2.kind is DocKind.NONE
