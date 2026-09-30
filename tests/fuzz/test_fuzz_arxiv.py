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
- ``html``（o2-b9 补面）：``fetch_html`` 异常集封闭（HtmlError/Parked/
  Budget/RequestError/ValueError）；``parse_arxiv_html``/``marked_html``
  任意 DOM 不抛非 HtmlError、块 key 唯一且两侧 data-chunk 1:1；
  ``doc_chunks`` 只产 TRANSLATE_CTX 非空块；``reinsert`` 单趟不级联。
- e-print e2e 敌意包（o2-b9）：``acquire_source`` 对嵌套 tar 不递归、
  ``../``/非 UTF-8 原名/超限成员告警透传进 meta.json 且零逃逸。

全离线：一律 ``httpx.MockTransport`` + 注入 clock/sleep，零真网络零真等待。
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import math
import re
import tarfile
import time
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import httpx
import pytest
from _fuzzkit import fuzz_rng

if TYPE_CHECKING:
    import random
    from collections.abc import Callable

from conftest import FakeClock, make_targz, mk_fetcher

from texlate.arxiv._texutil import strip_comments
from texlate.arxiv.cache import CacheError, SourceCache
from texlate.arxiv.fetch import (
    DL_CAP,
    MAX_RETRY_AFTER_S,
    AcquireResult,
    AcquireStatus,
    Fetcher,
    HeadInfo,
    _parse_head,
    _retry_delay,
    acquire_source,
    normalize_arxiv_id,
    valid_id,
)
from texlate.arxiv.html import (
    TRANSLATE_CTX,
    HtmlDoc,
    HtmlError,
    HtmlFetchError,
    HtmlNotAvailableError,
    doc_chunks,
    fetch_html,
    marked_html,
    parse_arxiv_html,
    reinsert,
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
from texlate.latex.placeholder import PH_RX
from texlate.xlat.prompts import normalize_kind

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


def _no_sleep(_d: float) -> None:
    return None


def _park_bucket(rl: RateLimiter, url: str) -> None:
    """429×2 → parked：断路器触发阈值的唯一写法（阈值改动只动这里）。"""
    for _ in range(2):
        rl.acquire(url)
        rl.report(url, HTTPStatus.TOO_MANY_REQUESTS)


_TINY_TEX = b"\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
_TINY_TGZ = make_targz({"main.tex": _TINY_TEX})


# ---------------------------------------------------------------- normalize

#: 随机汤 token 池——unicode 十进制数字（²٣9 等）定向覆盖在
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
    rng = fuzz_rng(_SEED)
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
    (自身，None)。若 B 还带 ver 或 base 仍可被改写，说明前缀剥离可无限推进
    或钉版判断不自洽。
    """
    rng = fuzz_rng(_SEED + 1)
    for _ in range(_NORM_ITERS):
        s = _soup(rng, rng.randint(0, 12))
        b1, _v1 = normalize_arxiv_id(s)
        b2, v2 = normalize_arxiv_id(b1)
        assert v2 is None
        assert normalize_arxiv_id(b2) == (b2, None), (s, b1, b2, v2)


def test_normalize_valid_roundtrip() -> None:
    """合法 (base, ver) 钉版串 round-trip：normalize(f"{base}v{ver}") 原样回。

    旧形 classful 输入的 ``base`` 期望是 canon 规范形（class 段剥除：
    ``cs.AI``→``cs``、``math.GT``→``math``）——归一是 spec 特性非 drift。
    """
    cases = [
        ("1412.6980", "1412.6980", 1),
        ("1412.6980", "1412.6980", 99),
        ("2001.00001", "2001.00001", 3),
        ("hep-th/9901001", "hep-th/9901001", 2),
        ("cond-mat/0408438", "cond-mat/0408438", 1),
        ("cs.AI/0301024", "cs/0301024", 7),
        ("math.GT/0309136", "math/0309136", 12),
    ]
    for raw, base, ver in cases:
        assert normalize_arxiv_id(f"{raw}v{ver}") == (base, ver)
        assert normalize_arxiv_id(raw) == (base, None)


def test_normalize_unicode_digit_id_rejected() -> None:
    """全角/阿拉伯 - 印度数字 id 不应通过合法性校验（fetch.py:148-149 ``\\d``）。"""
    for s in ["２００１.００００１", "٢٠٠١.٠٠٠٠١", "１２３４.５６７８"]:
        base, _ver = normalize_arxiv_id(s)
        assert not valid_id(base), s
    base, ver = normalize_arxiv_id("２００１.００００１v３")
    assert not (valid_id(base) and ver is not None)


def test_normalize_unicode_digit_offline_blindness(tmp_path: Path) -> None:
    """unicode 数字 id 可 commit（entry_dir 放行）但 find_versions 全拒 →
    离线未钉版 lookup 对已存在缓存失明。

    上游 ``valid_id`` 已按 ASCII 拒 unicode 数字 id，此不对称仅存在于缓存层
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
    rng = fuzz_rng(_SEED + 2)
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


def _tar_oracle(payload: bytes) -> bool:
    """tar 独立 oracle：stdlib ``tarfile`` 能否开流（全零非空 = 零成员包）。"""
    if payload and payload.count(0) == len(payload):
        return True
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:"):
            return True
    except (tarfile.TarError, OSError, EOFError, ValueError):
        return False


def test_fuzz_sniff_gzip_roundtrip() -> None:
    """gzip 往返：未超限 ⇒ payload 逐字节等于原始；tar 与否按可解析性判。"""
    rng = fuzz_rng(_SEED + 3)
    for _ in range(300):
        payload = rng.randbytes(rng.randint(0, 3000))
        if rng.random() < _P_USTAR:
            # 在 257 偏移埋 ustar 字面——撞字面的非 tar payload 应判 SINGLE
            payload = payload[:257].ljust(257, b"\0") + b"ustar" + payload[262:]
        blob = gzip.compress(payload)
        res = sniff(blob, max_inflated=_GZIP_CAP)
        if len(payload) > _GZIP_CAP:
            assert res.oversized
            continue
        assert not res.oversized
        assert res.payload == payload
        want = BlobKind.TAR if _tar_oracle(payload) else BlobKind.SINGLE
        assert res.kind is want


def test_sniff_cap_boundary() -> None:
    """解压上限边界：恰 cap 不拒，cap+1 即 oversized。"""
    exact = gzip.compress(b"x" * _GZIP_CAP)
    over = gzip.compress(b"x" * (_GZIP_CAP + 1))
    assert not sniff(exact, max_inflated=_GZIP_CAP).oversized
    assert sniff(over, max_inflated=_GZIP_CAP).oversized


def test_fuzz_sniff_mutated_gzip() -> None:
    """gzip 流字节变异：SniffError 或自洽结果，绝不抛其他异常。"""
    rng = fuzz_rng(_SEED + 4)
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

    clk = FakeClock()
    f = mk_fetcher(handler, clk)
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
    rng = fuzz_rng(_SEED + 5)
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
    """定向：includepdf+ 章节不判 wrapper；空正文判 stub。"""
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
    rng = fuzz_rng(_SEED + 6)
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
    rng = fuzz_rng(_SEED + 7)
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
    rng = fuzz_rng(_SEED + 8)
    for _ in range(500):
        seed = str(rng.random())
        j1, j2 = jitter(seed), jitter(seed)
        assert j1 == j2
        assert _J_LO <= j1 <= _J_HI
        assert _J2_LO <= jitter(seed, span=0.5) <= _J2_HI


def test_fuzz_ratelimit_ops() -> None:
    """随机 acquire/report/clock 推进：异常集封闭 + 预算上界 + park 自洽。"""
    rng = fuzz_rng(_SEED + 9)
    clk = FakeClock()
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
    clk = FakeClock()
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
    rng = fuzz_rng(_SEED + 10)
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
        RateLimiter(sp, clock=FakeClock().now, sleep=_no_sleep)
    for i in range(200):
        sp = tmp_path / f"rz{i}.json"
        sp.write_bytes(rng.randbytes(rng.randint(0, 200)))
        RateLimiter(sp, clock=FakeClock().now, sleep=_no_sleep)


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
        RateLimiter(sp, clock=FakeClock().now, sleep=_no_sleep)


def test_ratelimit_day_rollover_resets_budget() -> None:
    """跨日推进：预算归零重来。"""
    clk = FakeClock()
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
    rng = fuzz_rng(_SEED + 11)
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
    rng = fuzz_rng(_SEED + 12)
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


def test_cache_get_nonutf8_meta_returns_none(tmp_path: Path) -> None:
    """cache.py 曾崩缺陷钉：非 UTF-8 损坏条目应按未命中返回 None。"""
    cache = SourceCache(tmp_path)
    d = tmp_path / "2001.00001v1"
    d.mkdir()
    (d / "meta.json").write_bytes(b'{"etag": "\xff\xfe not utf8"}')
    assert cache.get("2001.00001", 1) is None


def test_acquire_corrupt_meta_error_e2e(tmp_path: Path) -> None:
    """在线臂：HEAD 200 → 损坏 meta 曾令 cache.get 崩出；应归 ERROR。离线臂同。"""
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

    clk = FakeClock()
    f = mk_fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=cache)
    assert res.status is AcquireStatus.ERROR  # 期望：损坏条目归 error 而非崩

    res_off = acquire_source("2001.00001", fetcher=f, cache=cache, offline=True)
    assert res_off.status is AcquireStatus.ERROR


def test_fuzz_cache_commit_roundtrip(tmp_path: Path) -> None:
    """stage→写 meta→commit→get：meta 原样回读；目录名恒 {id}v{ver}；无残渣。"""
    rng = fuzz_rng(_SEED + 13)
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
    rng = fuzz_rng(_SEED + 14)
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

    clk = FakeClock()
    f = mk_fetcher(handler, clk)
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

    clk = FakeClock()
    f = mk_fetcher(handler, clk)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


def test_head_cl_unicode_digit() -> None:
    """fetch.py:197——latin-1 ``²`` 经 bytes header 进入（isdigit 真、int 假）。

    真 wire 上 h11 对 CL 有帧校验会先拒；MockTransport/自定义 client（Fetcher
    公开注入点）可达。修法规整：``int()`` 包 try 或改 ``cl.isascii() and
    cl.isdigit()``.
    """
    resp = httpx.Response(200, headers=[(b"content-length", b"\xb2")])
    head = _parse_head(resp, "https://arxiv.org/src/x", None)
    assert head.content_length is None  # 期望：判不出就当没有


def test_retry_after_inf_returns_error(tmp_path: Path) -> None:
    """429 + ``Retry-After: 1e999`` → 重试退避 OverflowError 曾逃逸——应归 ERROR。"""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            HTTPStatus.TOO_MANY_REQUESTS, headers={"retry-after": "1e999"}
        )

    clk = FakeClock()
    # 真 sleep——inf 立刻 OverflowError，不会真等（假睡会吞掉这条路径）
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",), sleep=time.sleep)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR  # 期望归类，不是崩


def test_retry_delay_bounded_ra() -> None:
    """Retry-After 超 ``MAX_RETRY_AFTER_S`` 归 inf 终态；界内从其值；坏值回落。"""
    over = httpx.Response(429, headers={"retry-after": "999999999"})
    assert math.isinf(_retry_delay("https://x/", 1, over))
    at_cap = httpx.Response(429, headers={"retry-after": str(int(MAX_RETRY_AFTER_S))})
    assert _retry_delay("https://x/", 1, at_cap) == MAX_RETRY_AFTER_S
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
    rng = fuzz_rng(_SEED + 15)
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

        clk = FakeClock()
        f = mk_fetcher(handler, clk)
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
    （docs/spec/arxiv-source.md：park 键是 (host,path) 桶，未 park 的 host 不换）。
    """
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        return httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE)

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org", "export.arxiv.org"))
    head = f.head_src("2001.00001")
    assert head.http_status == HTTPStatus.SERVICE_UNAVAILABLE
    assert calls == ["arxiv.org"] * _MAX_ATTEMPTS
    assert len(clk.slept) <= _MAX_ATTEMPTS - 1


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
    rng = fuzz_rng(_SEED + 16)
    for _ in range(_META_ITERS):
        atom = rng.choice(_META_BODIES)
        oai = rng.choice(_META_BODIES)
        astat = rng.choice([200, 200, 200, 404, 500])
        ostat = rng.choice([200, 200, 404])
        clk = FakeClock()
        f = mk_fetcher(
            _meta_handler(atom, oai, atom_status=astat, oai_status=ostat), clk
        )
        m = fetch_metadata("2001.00001", fetcher=f)
        _check_paper_meta(m)


def test_fetch_metadata_bomb_falls_back_to_oai() -> None:
    """实体炸弹打 Atom → defusedxml 拦 → OAI 兜底仍出结果。"""
    clk = FakeClock()
    f = mk_fetcher(_meta_handler(_ENTITY_BOMB, _OAI_OK.encode()), clk)
    m = fetch_metadata("2001.00001", fetcher=f)
    assert m is not None
    assert m.source == "oai-raw"
    assert m.latest_version == _OAI_LATEST


def test_fuzz_resolve_version_contract() -> None:
    """resolve_version：want 给定时结果 ∈ {want, None}；裸调 ∈ {None, ≥1}。"""
    rng = fuzz_rng(_SEED + 17)
    for _ in range(200):
        atom = rng.choice(_META_BODIES)
        oai = rng.choice(_META_BODIES)
        clk = FakeClock()
        f = mk_fetcher(_meta_handler(atom, oai), clk)
        want = rng.choice([None, 1, 2, 3, 99])
        got = resolve_version("2001.00001", want, fetcher=f)
        if want is None:
            assert got is None or got >= 1
        else:
            assert got in {want, None}


def _degrade_fetcher(statuses: dict[str, int], clk: FakeClock) -> Fetcher:
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

    return mk_fetcher(handler, clk, hosts=("arxiv.org",), follow_redirects=True)


def test_fuzz_degrade_contract() -> None:
    """degrade：任意原因串 + 随机 HEAD 结局 → 契约一致或 ValueError（坏入参）。"""
    rng = fuzz_rng(_SEED + 18)
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
        clk = FakeClock()
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
    rng = fuzz_rng(_SEED + 19)
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
    rng = fuzz_rng(_SEED + 20)
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
    rng = fuzz_rng(_SEED + 21)
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


# ==================================================================== 批 o2-b9
# e-print e2e 敌意包 / Fetcher 传输纪律 / ratelimit 细分 / locate 补面 /
# degrade 回退 / html.py 降级链（此前零 fuzz 覆盖）

_TINY_TEX_FULL = b"\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"
_CD_V1 = 'attachment; filename="arXiv-2001.00001v1.tar.gz"'
_VER_FLIPPED = 3  # GET cd 翻转到的新版号
_NTP_WAIT_MIN = 9000.0  # 回拨后 pacing wait 的保守下界（回拨 10000s - gap）
_CHAIN_SEGS = 79  # 深链段数（> _MAX_DEPTH 触发截断）
_ORDER_CAP = 65  # depth 0..64 → order 长度上界
_OAI_PAD_LATEST = 8  # 零填充版本号折叠后的真 latest
_REDIRECT_CALLS_BOUND = 30  # httpx 单次 send 内部重定向环上界（不重试语义）


def _ok_200(_req: httpx.Request) -> httpx.Response:
    """MockTransport 全 200 应答。"""
    return httpx.Response(HTTPStatus.OK)


def _acq_fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[Fetcher, FakeClock]:
    """单 host acquire 用 fetcher（复用 conftest ``FakeClock``/``mk_fetcher`` 同族约定）。"""
    clk = FakeClock()
    return mk_fetcher(handler, clk, hosts=("arxiv.org",)), clk


def _src_handler(
    body: bytes,
    *,
    head_cd: str = _CD_V1,
    get_cd: str = "",
    get_status: int = HTTPStatus.OK,
) -> Callable[[httpx.Request], httpx.Response]:
    """HEAD/GET 双段应答——GET 的 cd 可与 HEAD 不同（版本翻转/畸形）。"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            headers = {"content-disposition": head_cd} if head_cd else {}
            return httpx.Response(HTTPStatus.OK, headers=headers)
        headers = {"content-disposition": get_cd} if get_cd else {}
        return httpx.Response(get_status, content=body, headers=headers)

    return handler


def _extracted_files(res: AcquireResult) -> list[str]:
    """committed entry 的 extracted/ 文件名表（无条目/无目录 → 空）。"""
    if res.entry is None:
        return []
    ext = res.entry.dir / "extracted"
    if not ext.is_dir():
        return []
    return sorted(p.relative_to(ext).as_posix() for p in ext.rglob("*") if p.is_file())


# ---------------------------------------------------------------- D1 空 tar.gz


def test_empty_targz_phantom_tex(tmp_path: Path) -> None:
    """D1 回归：空 tar.gz e-print 判 TAR→空树，不落幻影 {stem}.tex。"""
    f, _clk = _acq_fetcher(_src_handler(make_targz({})))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    if res.status is AcquireStatus.OK:
        assert _extracted_files(res) == []


def test_empty_targz_empty_tree(tmp_path: Path) -> None:
    """D1 回归钉：零成员 tar 走 unpack 空树——OK 且 extracted 零文件。"""
    f, _clk = _acq_fetcher(_src_handler(make_targz({})))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert _extracted_files(res) == []


# ---------------------------------------------------------------- D2 ustar 误判


def test_ustar_in_tex_payload_misclassified(tmp_path: Path) -> None:
    """D2 回归：payload[257:262]=='ustar' 的 .tex 回退 SINGLE，不是 tar 硬拒。"""
    tex = b"\\documentclass{article}\n" + b"a" * 300
    tex = tex[:257].ljust(257, b"a") + b"ustar" + tex[262:]
    tex += b"\n\\begin{document}hi\\end{document}\n"
    f, _clk = _acq_fetcher(_src_handler(gzip.compress(tex)))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK


def test_ustar_in_tex_lands_single(tmp_path: Path) -> None:
    """D2 回归钉：ustar 字面误撞的 .tex 按单文件落盘（唯一 .tex 成员）。"""
    tex = b"\\documentclass{article}\n" + b"a" * 300
    tex = tex[:257].ljust(257, b"a") + b"ustar" + tex[262:]
    tex += b"\n\\begin{document}hi\\end{document}\n"
    f, _clk = _acq_fetcher(_src_handler(gzip.compress(tex)))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    files = _extracted_files(res)
    assert len(files) == 1
    assert files[0].endswith(".tex")
    assert (res.entry.dir / "extracted" / files[0]).read_bytes() == tex


# ---------------------------------------------------------------- e2e 敌意包


def test_e2e_nested_tar_and_traversal(tmp_path: Path) -> None:
    """嵌套 tar.gz 不递归（落盘为普通文件）；``../`` 成员拒径且零逃逸。"""
    inner = make_targz({"inner.tex": "\\documentclass{article}"})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in {
            "../evil.tex": b"ESCAPED",
            "inner.tar.gz": inner,
            "main.tex": _TINY_TEX_FULL,
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    f, _clk = _acq_fetcher(_src_handler(buf.getvalue()))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert "reject_path:../evil.tex" in res.warnings
    assert not (tmp_path / "evil.tex").exists()
    ext_files = _extracted_files(res)
    assert sorted(ext_files) == ["inner.tar.gz", "main.tex"]
    meta = json.loads((res.entry.dir / "meta.json").read_text("utf-8"))
    assert "reject_path:../evil.tex" in meta["warnings"]
    # 嵌套包按字节留存不展开
    assert (res.entry.dir / "extracted" / "inner.tar.gz").read_bytes() == inner


def test_e2e_latin1_member_name_rejected(tmp_path: Path) -> None:
    """非 UTF-8 原名（裸 latin-1 字节）→ reject_path 告警进 meta.json。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in (("cafX.tex", b"z" * 200), ("main.tex", _TINY_TEX_FULL)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    raw = bytearray(buf.getvalue())
    raw[0:8] = b"caf\xe9.tex"  # USTAR name 字段塞裸 latin-1 字节
    raw[148:156] = b"        "  # 重算 checksum 让改名生效
    raw[148:156] = f"{sum(raw[0:512]):06o}\x00 ".encode()
    f, _clk = _acq_fetcher(_src_handler(gzip.compress(bytes(raw))))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert _extracted_files(res) == ["main.tex"]
    meta = json.loads((res.entry.dir / "meta.json").read_text("utf-8"))
    assert any(w.startswith("reject_path:caf") for w in meta["warnings"])


def test_e2e_member_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """成员/总量上限 e2e：超限成员告警透传，整包仍 OK。"""
    monkeypatch.setattr("texlate.arxiv.unpack.MAX_FILE_BYTES", 100)
    body = make_targz({"main.tex": _TINY_TEX_FULL, "big.tex": b"b" * 500})
    f, _clk = _acq_fetcher(_src_handler(body))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert "reject_filesize:big.tex:500" in res.warnings
    assert _extracted_files(res) == ["main.tex"]


def test_e2e_too_many_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """成员数硬上限 → 整包 UnpackError → UNPACK_ERROR 终态。"""
    monkeypatch.setattr("texlate.arxiv.unpack.MAX_MEMBERS", 3)
    body = make_targz({f"f{i}.tex": _TINY_TEX_FULL for i in range(4)})
    f, _clk = _acq_fetcher(_src_handler(body))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.UNPACK_ERROR
    assert "too_many_members" in res.detail


# ---------------------------------------------------------------- e2e cd/版本面


def test_e2e_get_cd_version_flip(tmp_path: Path) -> None:
    """HEAD v1 → GET cd v3（两请求间发新版）：以 GET 为准落 v3 目录。"""
    body = make_targz({"main.tex": _TINY_TEX_FULL})
    f, _clk = _acq_fetcher(
        _src_handler(
            body,
            get_cd='attachment; filename="arXiv-2001.00001v3.tar.gz"',
        )
    )
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == _VER_FLIPPED
    assert res.entry.dir.name == "2001.00001v3"


def test_e2e_get_cd_version_lost(tmp_path: Path) -> None:
    """GET cd 无版本标记 → 沿用 HEAD 钉版（不盲丢版本号）。"""
    body = make_targz({"main.tex": _TINY_TEX_FULL})
    f, _clk = _acq_fetcher(_src_handler(body, get_cd="attachment"))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == 1


def test_e2e_huge_cd_version_clean_error(tmp_path: Path) -> None:
    """300 位版本号 cd：int 可解析但目录名超 NAME_MAX → 归 ERROR 不崩。

    D5 回归：entry_dir 对越界版本回哨兵（get→miss、exists→False），
    commit 写闸硬拒 CacheError → _commit_phase 兜成干净 ERROR。
    """
    cd = 'attachment; filename="arXiv-2001.00001v' + "9" * 300 + '.tar.gz"'
    f, _clk = _acq_fetcher(
        _src_handler(make_targz({"m.tex": _TINY_TEX_FULL}), head_cd=cd)
    )
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR


def test_e2e_hostile_stem_sanitized(tmp_path: Path) -> None:
    """single_gz cd 名带 ``../``：stem 取末段，落盘不出 extracted。"""
    body = gzip.compress(_TINY_TEX_FULL + b"z" * 200)
    f, _clk = _acq_fetcher(
        _src_handler(body, head_cd='attachment; filename="../evilv2.gz"')
    )
    res = acquire_source("2001.00001v2", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert _extracted_files(res) == ["evilv2.tex"]
    assert not (tmp_path / "evilv2.tex").exists()


def test_e2e_single_gz_no_cd_stem_fallback(tmp_path: Path) -> None:
    """无 cd 时 stem 退化为 base 去斜杠：hep-th/9901001 → hep-th9901001.tex。"""
    body = gzip.compress(_TINY_TEX_FULL + b"z" * 200)
    f, _clk = _acq_fetcher(_src_handler(body, head_cd=""))
    res = acquire_source("hep-th/9901001v2", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert _extracted_files(res) == ["hep-th9901001.tex"]


def test_e2e_bare_304_no_cache_is_error(tmp_path: Path) -> None:
    """无条件 GET 收到 304（服务器异常）：无缓存可命中 → 归 ERROR 不落盘。"""
    f, _clk = _acq_fetcher(_src_handler(b"", get_status=HTTPStatus.NOT_MODIFIED))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR
    assert res.entry is None


def test_e2e_head_no_cd_bare_id(tmp_path: Path) -> None:
    """HEAD 200 但无 content-disposition 且未钉版 → unresolved_version ERROR。"""
    f, _clk = _acq_fetcher(_src_handler(b"", head_cd=""))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.ERROR
    assert res.detail == "unresolved_version"


def test_e2e_too_large_skips_get(tmp_path: Path) -> None:
    """HEAD content-length 超 DL_CAP → TOO_LARGE 且不发 GET。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.method)
        assert req.method == "HEAD"
        return httpx.Response(
            HTTPStatus.OK,
            headers={
                "content-disposition": _CD_V1,
                "content-length": str(200 * 1024 * 1024),
            },
        )

    f, _clk = _acq_fetcher(handler)
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.TOO_LARGE
    assert calls == ["HEAD"]


def test_acquire_version_param_overrides_pin(tmp_path: Path) -> None:
    """``version`` 形参与 id 内钉版冲突时形参赢——``2001.00001v2`` + version=3 → v3。"""
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers={
                    "content-disposition": 'attachment; filename="arXiv-2001.00001v3.tar.gz"'
                },
            )
        return httpx.Response(
            HTTPStatus.OK, content=make_targz({"m.tex": _TINY_TEX_FULL})
        )

    f, _clk = _acq_fetcher(handler)
    res = acquire_source(
        "2001.00001v2", version=3, fetcher=f, cache=SourceCache(tmp_path)
    )
    assert res.status is AcquireStatus.OK
    assert res.resolved_version == _VER_FLIPPED
    assert seen == ["/src/2001.00001v3", "/src/2001.00001v3"]


def test_e2e_gzipped_pdf_becomes_tex_quirk(tmp_path: Path) -> None:
    """观察钉：gzip 包 %PDF 体（老式 single-file 形态）落为 .tex 内容垃圾——
    SINGLE 臂不验 TeX 性，PDF_ONLY 只对裸 %PDF 魔数生效。"""
    body = gzip.compress(b"%PDF-1.4 fake\n" + b"p" * 300)
    f, _clk = _acq_fetcher(_src_handler(body))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    files = _extracted_files(res)
    assert len(files) == 1
    assert (res.entry.dir / "extracted" / files[0]).read_bytes().startswith(b"%PDF")


def test_e2e_multi_main_resolution(tmp_path: Path) -> None:
    """多主文件裁决 e2e：multi_doc 置位 + main 取自 candidates + 确定性。"""
    body = make_targz(
        {
            "main.tex": "\\documentclass{article}\n\\begin{document}\n\\section{S}\nbody\n\\end{document}\n",
            "paper.tex": "\\documentclass{article}\n\\begin{document}\n\\section{S}\nbody\n\\end{document}\n",
        }
    )
    f, _clk = _acq_fetcher(_src_handler(body))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    meta = json.loads((res.entry.dir / "meta.json").read_text("utf-8"))
    loc = meta["locate"]
    assert loc["multi_doc"] is True
    assert loc["main"] == "main.tex"  # prior+ 深度平 → 路径序最小
    assert set(loc["candidates"]) == {"main.tex", "paper.tex"}


def test_e2e_casefold_dup_mains(tmp_path: Path) -> None:
    """main.tex/Main.tex 大小写撞名：解包改名 ``~c2`` 后双候选均可见。"""
    body = make_targz(
        {
            "main.tex": _TINY_TEX_FULL + b"\\section{S}\nbody\n",
            "Main.tex": _TINY_TEX_FULL + b"\\section{S}\nbody\n",
        }
    )
    f, _clk = _acq_fetcher(_src_handler(body))
    res = acquire_source("2001.00001", fetcher=f, cache=SourceCache(tmp_path))
    assert res.status is AcquireStatus.OK
    assert any(w.startswith("casefold_rename:Main.tex") for w in res.warnings)


# ---------------------------------------------------------------- Fetcher 传输纪律


def test_transport_error_retries_then_raises() -> None:
    """ConnectError 走满 RETRY_DELAYS 重试表（4 发）后以 TransportError 上抛。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        msg = "boom"
        raise httpx.ConnectError(msg, request=req)

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",))
    with pytest.raises(httpx.TransportError):
        f.head_src("2001.00001")
    assert len(calls) == _MAX_ATTEMPTS


def test_deterministic_request_error_not_retried() -> None:
    """TooManyRedirects 属确定性 RequestError——立即上抛，不重试烧预算。"""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            HTTPStatus.MOVED_PERMANENTLY,
            headers={"location": str(req.url)},
        )

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",), follow_redirects=True)
    with pytest.raises(httpx.TooManyRedirects):
        f.head_src("2001.00001")
    # httpx 内部重定向环（max_redirects）单次 send 内烧穿——不走退避表
    assert len(calls) <= _REDIRECT_CALLS_BOUND


def test_across_hosts_park_failover() -> None:
    """主 host 被 park → 同路径自动走 export 镜像桶拿 200。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    _park_bucket(rl, "https://arxiv.org/src/x")
    assert rl.parked_until("https://arxiv.org/src/x") > clk.t

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "export.arxiv.org"
        return httpx.Response(
            HTTPStatus.OK,
            headers={"content-disposition": _CD_V1},
        )

    f = mk_fetcher(handler, clk, rl=rl)
    head = f.head_src("2001.00001")
    assert head.http_status == HTTPStatus.OK
    assert head.resolved_version == 1


def test_across_hosts_park_beats_transport_error() -> None:
    """观察钉：host1 parked + host2 transport-error → ParkedError 优先上抛。"""

    def handler(req: httpx.Request) -> httpx.Response:
        msg = "down"
        raise httpx.ConnectError(msg, request=req)

    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    _park_bucket(rl, "https://arxiv.org/src/x")
    f = mk_fetcher(handler, clk, rl=rl)
    with pytest.raises(ParkedError):
        f.head_src("2001.00001")


def test_across_hosts_all_parked_raises_first() -> None:
    """全 host park → 首个 ParkedError（failover 穷尽语义）。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    for host in ("arxiv.org", "export.arxiv.org"):
        _park_bucket(rl, f"https://{host}/src/x")
    f = mk_fetcher(_ok_200, clk, rl=rl)
    with pytest.raises(ParkedError, match=r"arxiv\.org"):
        f.head_src("2001.00001")


# ---------------------------------------------------------------- ratelimit 细分钉


def test_path_class_isolation_pin() -> None:
    """park 键带 path-class：/api 被 park 不挡 /src（实测口径 docs/spec/arxiv-source.md 勘误）。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    _park_bucket(rl, "https://export.arxiv.org/api/query?id_list=x")
    assert rl.parked_until("https://export.arxiv.org/api/query?id_list=x") > clk.t
    rl.acquire("https://export.arxiv.org/src/2001.00001")  # content 桶放行
    with pytest.raises(ParkedError):
        rl.acquire("https://export.arxiv.org/api/query?id_list=y")


def test_park_escalation_doubles() -> None:
    """断路器逐次翻倍 + consec_429 不随 park 过期清零——过期后单发 429 即再触，
    时长 2^1×base×jitter（≥1.6×base）。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    url = "https://arxiv.org/src/x"
    _park_bucket(rl, url)
    first = rl.parked_until(url) - clk.t
    assert 0 < first <= 1800 * 1.25
    clk.t += first + 1  # park 过期（consec_429=2 仍在桶上）
    rl.acquire(url)  # 放行
    rl.report(url, HTTPStatus.TOO_MANY_REQUESTS)  # consec=3 ≥2 → 即刻再触
    second = rl.parked_until(url) - clk.t
    assert second >= 1800 * 1.6  # step=1 → 2×base×jitter(≥0.8)
    assert second <= 7200 * 1.25  # jitter 在 cap 外乘——有效上界 park_max×1.2
    with pytest.raises(ParkedError):  # 新 park 立即生效
        rl.acquire(url)


def test_budget_boundary_exact() -> None:
    """日预算边界：恰 DAILY_BUDGET 发通过，第 N+1 发 BudgetExhausted。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    for i in range(DAILY_BUDGET):
        rl.acquire(f"https://arxiv.org/src/p{i}")
    with pytest.raises(BudgetExhaustedError):
        rl.acquire("https://arxiv.org/src/over")


def test_backward_clock_inflates_pacing() -> None:
    """观察钉：墙钟回拨 → pacing wait 吃满回拨量（docstring 已记代价）。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    rl.acquire("https://arxiv.org/src/a")
    clk.t -= 10000.0  # NTP 回拨 ~2.8h
    rl.acquire("https://arxiv.org/src/b")
    assert clk.slept[-1] > _NTP_WAIT_MIN


# ---------------------------------------------------------------- locate 补面


def test_locate_deep_chain_and_cycle(tmp_path: Path) -> None:
    """深链截断 + 环告警（重构在飞件——只钉稳定不变量）。"""
    deep = tmp_path / "deep"
    deep.mkdir()
    (deep / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{c1}\n\\end{document}\n"
    )
    for i in range(1, _CHAIN_SEGS):
        nxt = f"\\input{{c{i + 1}}}" if i < _CHAIN_SEGS - 1 else ""
        (deep / f"c{i}.tex").write_text(f"% seg{i}\n{nxt}\n")
    res = locate(deep)
    assert res.main == "main.tex"
    assert len(res.order) == _ORDER_CAP  # depth 0..64
    assert any(w.startswith("max_depth:c65.tex") for w in res.warnings)

    cyc = tmp_path / "cyc"
    cyc.mkdir()
    (cyc / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{b}\n\\end{document}\n"
    )
    (cyc / "b.tex").write_text("\\input{a}\n")
    (cyc / "a.tex").write_text("\\input{b}\n")
    res2 = locate(cyc)
    assert res2.order == ["main.tex", "b.tex", "a.tex"]
    assert "cycle:a.tex->b.tex" in res2.warnings


def test_locate_dangling_symlink_unreadable(tmp_path: Path) -> None:
    """dangling .tex symlink → ``unreadable:`` 告警而非崩。"""
    root = tmp_path / "d"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
    )
    (root / "ghost.tex").symlink_to("nonexistent.tex")
    res = locate(root)
    assert res.main == "main.tex"
    assert any(w.startswith("unreadable:ghost.tex") for w in res.warnings)


def test_locate_out_of_tree_symlink_followed(tmp_path: Path) -> None:
    """PLAUSIBLE 钉：.tex symlink 指树外 → 内容被跟读、成候选。

    arXiv tar 路径不可达（unpack 拒绝对/逃逸链接）；但 upload/直接落盘
    树无此闸——``_scan_nodes`` 的 ``read_bytes`` 随 symlink 出根，树外
    ``\\documentclass`` 文件被采纳为候选。内容不进 LocateResult，但
    「main 落盘选择」被树外内容劫持。
    """
    outside = tmp_path / "outside.tex"
    outside.write_text(
        "\\documentclass{article}\n\\begin{document}OUT\\end{document}\n"
    )
    root = tmp_path / "tree"
    root.mkdir()
    (root / "link.tex").symlink_to(outside)
    (root / "plain.tex").write_text("no docclass\n")
    res = locate(root)
    assert res.main == "link.tex"  # 现行行为钉——修复应拒跟树外 link


def test_locate_arxiv_id_filename_prior(tmp_path: Path) -> None:
    """文件名先验：``{id 去标点}.tex`` 与 main 平级时 id 名胜出依赖排序。"""
    root = tmp_path / "idprior"
    root.mkdir()
    for name in ("zzz.tex", "200100001.tex"):
        (root / name).write_text(
            "\\documentclass{article}\n\\begin{document}\n\\section{S}\nx\n\\end{document}\n"
        )
    res = locate(root, arxiv_id="2001.00001")
    assert res.main == "200100001.tex"
    assert res.multi_doc


# ---------------------------------------------------------------- meta/degrade 补面

_BURN_BOUND = 30  # 版本回退探测的合理上界（真版本史 rarely >30）


def test_degrade_version_fallback_unbounded() -> None:
    """D3 回归：feed 宣告 latest=300 + /html 全 404 → 回退探测有界不烧预算。"""
    atom = (
        b'<?xml version="1.0"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><id>http://arxiv.org/abs/2001.00001v300</id><title>T</title>"
        b"</entry></feed>"
    )
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if "/api/query" in req.url.path:
            return httpx.Response(HTTPStatus.OK, content=atom)
        return httpx.Response(HTTPStatus.NOT_FOUND)

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",))
    res = degrade("2001.00001", fetcher=f, reason=DegradeReason.PARSE_FAILED, version=2)
    assert res.tier is DegradeTier.NONE
    assert len(calls) <= _BURN_BOUND


def test_degrade_fallback_park_aborts() -> None:
    """版本回退中途 park → abort 归 NONE/兜底层，不继续空烧。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    # 预 park content 桶（/html 与 /pdf 同属 content path-class）
    _park_bucket(rl, "https://arxiv.org/src/x")
    assert rl.parked_until("https://arxiv.org/html/x") > clk.t

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(HTTPStatus.OK, content=b"<feed/>")

    f = mk_fetcher(handler, clk, hosts=("arxiv.org",), rl=rl)
    res = degrade("2001.00001", fetcher=f, reason=DegradeReason.PARSE_FAILED, version=2)
    assert res.tier is DegradeTier.NONE
    assert any("abort" in p for p in res.probed)


def test_oai_version_zero_padded_collapses() -> None:
    """OAI ``version="v007"`` → int 折叠为 7——与 v7 重复记录并存不炸。"""
    oai = b"""<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><metadata>
  <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
   <id>2001.00001</id><title>T</title><authors>A</authors>
   <version version="v7"/><version version="v007"/><version version="v08"/>
  </arXivRaw>
 </metadata></record></GetRecord>
</OAI-PMH>"""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oai":
            return httpx.Response(HTTPStatus.OK, content=oai)
        return httpx.Response(HTTPStatus.NOT_FOUND)

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",))
    m = fetch_metadata("2001.00001", fetcher=f)
    assert m is not None
    assert [v.version for v in m.versions] == [7, 7, _OAI_PAD_LATEST]
    assert m.latest_version == _OAI_PAD_LATEST
    assert m.has_version(7)


# ---------------------------------------------------------------- html.py 降级链

_HTML_FRAGS = (
    '<div class="ltx_para">',
    "</div>",
    "<math><mi>x</mi></math>",
    '<span class="ltx_ERROR">',
    "</span>",
    "text ",
    "<p>",
    "</p>",
    "<h1 class='ltx_title ltx_title_document'>T</h1>",
    "<h6 class='ltx_title ltx_title_subparagraph'>s</h6>",
    "[[MATH_1]]",
    "[[CITE_9]]",
    "<figcaption class='ltx_caption'>c</figcaption>",
    "<div class='ltx_figure'>",
    "<li class='ltx_bibitem'>b</li>",
    "<a href='#x'>r</a>",
    "<a class='ltx_url' href='http://e'>u</a>",
    "<span class='ltx_note'>",
    "<span class='ltx_note_content'>n</span>",
    "<ul><li>",
    "</li></ul>",
    "<br>",
    "<table class='ltx_tabular'>",
    "</table>",
    "<div class='ltx_listing'>",
    "<div class='ltx_authors'>",
    "<div class='ltx_dates'>",
    "<div class='ltx_abstract'>",
    "<div class='ltx_classification'>",
    "<table class='ltx_equation'>",
    "<img src='f.png'>",
    "<svg></svg>",
    "<span class='ltx_note_mark'>m</span>",
    "<div class='ltx_titlepage'>",
    "<span style='font-size: 144%'>FT</span>",
    "<em>it</em>",
    "<span id='dup'>a</span><span id='dup'>b</span>",
    "\x00",
    "☃é",
)

_HTML_ITERS = 300


def test_fuzz_parse_html_random_soup() -> None:
    """随机 DOM 汤：不抛非 HtmlError；块 key 唯一；marked data-chunk 1:1。"""
    rng = fuzz_rng(_SEED + 30)
    for i in range(_HTML_ITERS):
        body = "".join(rng.choice(_HTML_FRAGS) for _ in range(rng.randint(0, 40)))
        doc = f'<article class="ltx_document">{body}</article>'
        try:
            res = parse_arxiv_html(doc, arxiv_id="x")
        except HtmlNotAvailableError:
            continue
        keys = [b.key for b in res.blocks]
        assert len(keys) == len(set(keys)), f"dup keys: {keys}"
        for b in res.blocks:
            assert isinstance(b.context, str)
            for t, frag in b.ph.items():
                assert PH_RX.fullmatch(t)
                assert res.ph_map[t] == frag
        marked = marked_html(doc)
        anchors = set(re.findall(r'data-chunk="([^"]+)"', marked))
        assert anchors == set(keys), f"iter{i}: anchor/block 错位"
        ctx_of_key = {b.key: b.context for b in res.blocks}
        chunks = doc_chunks(res, id_prefix="h:")
        for c in chunks:
            src_ctx = ctx_of_key[c.chunk_id.removeprefix("h:")]
            assert src_ctx in TRANSLATE_CTX  # 白名单外 context 不产 chunk
            assert c.kind == normalize_kind(src_ctx)
            assert c.content.strip()
            if c.ph_fragments:
                assert set(c.ph_fragments) <= set(res.ph_map)


def test_parse_html_deep_inline_nesting() -> None:
    """D4 回归：深嵌套行内元素应降级处理（HtmlError 或截断），不是 RecursionError。"""
    doc = (
        '<article class="ltx_document"><div class="ltx_para">'
        + "<span>" * 2000
        + "x"
        + "</span>" * 2000
        + "</div></article>"
    )
    try:
        res = parse_arxiv_html(doc)
    except HtmlError:
        return
    assert isinstance(res, HtmlDoc)
    with contextlib.suppress(HtmlError):
        marked_html(doc)


def test_fetch_html_stub_check_split_brain() -> None:
    """观察钉：fetch 侧 stub 判据是字面 ``ltx_document`` 子串——script/注释
    里出现同名字面即过闸，DOM 层 parse 仍会拒（廉价预检 vs 权威判据）。"""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            HTTPStatus.OK,
            text='<html><body><script>var x="ltx_document";</script></body></html>',
        )

    clk = FakeClock()
    f = mk_fetcher(handler, clk, hosts=("arxiv.org",))
    text = fetch_html("1501.00001", fetcher=f)  # 过闸
    with pytest.raises(HtmlNotAvailableError):
        parse_arxiv_html(text)  # DOM 判据拦


def test_fuzz_fetch_html_statuses() -> None:
    """任意 status/body：异常集封闭 + 200 返回体必含 ltx_document 字面。"""
    rng = fuzz_rng(_SEED + 31)
    bodies = (
        "<article class='ltx_document'></article>",
        "ltx_document",
        "<html/>",
        "",
        "ltx_document stub",
    )
    statuses = (200, 200, 200, 301, 404, 406, 429, 500, 502)
    allowed_exc = (
        HtmlFetchError,  # 非 200/非 404 状态
        HtmlError,  # stub/404 → HtmlNotAvailableError
        ParkedError,
        BudgetExhaustedError,
        httpx.RequestError,
        OSError,
    )
    for _ in range(200):
        status = rng.choice(statuses)
        body = rng.choice(bodies)

        def handler(
            _req: httpx.Request, _s: int = status, _b: str = body
        ) -> httpx.Response:
            return httpx.Response(_s, text=_b)

        clk = FakeClock()
        f = mk_fetcher(handler, clk, hosts=("arxiv.org",))
        try:
            out = fetch_html("1501.00001", fetcher=f)
        except allowed_exc:
            continue
        assert "ltx_document" in out


def test_fetch_html_parked_propagates() -> None:
    """fetch_html 的 park/预算异常原样上抛（不重包装成 HtmlError）。"""
    clk = FakeClock()
    rl = RateLimiter(clock=clk.now, sleep=clk.sleep)
    _park_bucket(rl, "https://arxiv.org/src/x")
    f = mk_fetcher(_ok_200, clk, hosts=("arxiv.org",), rl=rl)
    with pytest.raises(ParkedError):
        fetch_html("1501.00001", fetcher=f)


def test_fetch_html_bad_id_valueerror() -> None:
    """坏 id（含版本 <1）→ ValueError（调用方错误语义，与 head_src 同型）。"""
    clk = FakeClock()
    f = mk_fetcher(_ok_200, clk, hosts=("arxiv.org",))
    with pytest.raises(ValueError, match="bad arxiv id"):
        fetch_html("../etc/passwd", fetcher=f)
    with pytest.raises(ValueError, match="bad arxiv id"):
        fetch_html("1501.00001v0", fetcher=f)


def test_issuer_reserved_token_skips() -> None:
    """源文自带 ``[[MATH_1]]`` 字面 → 签发顺延，原文不被误当占位符。"""
    doc = parse_arxiv_html(
        '<article class="ltx_document"><div class="ltx_para">'
        "literal [[MATH_1]] text <math><mi>y</mi></math></div></article>"
    )
    assert "[[MATH_1]]" not in doc.ph_map
    assert "[[MATH_2]]" in doc.ph_map


def test_reinsert_single_pass_no_cascade() -> None:
    """ph 值内含类 token 字面不级联展开——单趟 sub 语义。"""
    out = reinsert("a [[X_1]] b", {"[[X_1]]": "[[Y_2]]", "[[Y_2]]": "Z"})
    assert out == "a [[Y_2]] b"


def test_marked_parse_key_parity_on_stubs() -> None:
    """stub 页 parse 与 marked 同抛 HtmlNotAvailableError——判据同型。"""
    stub = "<html><body>HTML not available</body></html>"
    with pytest.raises(HtmlNotAvailableError):
        parse_arxiv_html(stub)
    with pytest.raises(HtmlNotAvailableError):
        marked_html(stub)
