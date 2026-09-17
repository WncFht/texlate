import json
import logging
import time
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path

import httpx
import pytest

from texlate.arxiv.fetch import DL_CAP, Fetcher, FetchStatus
from texlate.arxiv.locate import _iter_files, locate
from texlate.arxiv.ratelimit import BudgetExhaustedError, RateLimiter

MAIN_TEX = "\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
UNDER_BUDGET_REQUESTS = 50


class _Clock:
    """注入限速器的假时钟：sleep 即前进。"""

    def __init__(self) -> None:
        self.t = 1_700_000_000.0  # 一个真实 epoch（day rollover 语义正常）

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def test_iter_files_dir_symlink_loop(tmp_path: Path) -> None:
    """A8：in-tree 目录符号链成环——os.walk 不 follow，不再 rglob 炸栈。"""
    root = tmp_path / "pkg"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (root / "main.tex").write_text(MAIN_TEX)
    (sub / "loop").symlink_to("..", target_is_directory=True)
    files = _iter_files(root)
    assert "main.tex" in files
    # 环链目录本身按 is_symlink 叶条目收进（原 is_file/is_symlink 口径同款）
    assert "sub/loop" in files
    res = locate(root)
    assert res.main == "main.tex"


def test_iter_files_file_and_dangling_symlinks(tmp_path: Path) -> None:
    """文件符号链与断链同属收编面；断链 .tex 读败记 unreadable 不炸。"""
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "main.tex").write_text(MAIN_TEX)
    (root / "alias.tex").symlink_to("main.tex")
    (root / "dangling.tex").symlink_to("nonexistent.tex")
    files = _iter_files(root)
    assert {"main.tex", "alias.tex", "dangling.tex"} <= set(files)
    res = locate(root)
    assert res.main == "main.tex"
    assert any("unreadable:dangling.tex" in w for w in res.warnings)


def test_get_src_body_streaming_cap() -> None:
    """A13：body > DL_CAP → TOO_LARGE；流式臂 cap+1 即断，不整量收进内存。"""
    pulled = 0
    chunk = b"x" * 65536
    total_chunks = DL_CAP // len(chunk) + 8  # 生成器总量远超 cap

    def gen() -> Iterator[bytes]:
        nonlocal pulled
        for _ in range(total_chunks):
            pulled += 1
            yield chunk

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "HEAD":
            return httpx.Response(
                HTTPStatus.OK,
                headers={
                    "content-disposition": 'attachment; filename="arXiv-1234.5678v1.tar.gz"'
                },
            )
        return httpx.Response(HTTPStatus.OK, content=gen())

    clk = _Clock()
    fetcher = Fetcher(
        RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        hosts=("arxiv.org",),
        sleep=clk.sleep,
    )
    res = fetcher.get_src("1234.5678")
    assert res.status is FetchStatus.TOO_LARGE
    assert pulled < total_chunks  # 提前断流——生成器未被穷尽


def test_requests_today_clamped_to_budget(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A14：腐坏巨值计数钳回日预算——仍 fail-closed 但值域收拢 + warning。"""
    clk = _Clock()
    day = time.strftime("%Y-%m-%d", time.gmtime(clk.t))
    state = tmp_path / "rl.json"
    state.write_text(
        json.dumps({"day": day, "requests_today": 9_000_000_000, "buckets": {}})
    )
    with caplog.at_level(logging.WARNING, logger="texlate.arxiv.ratelimit"):
        rl = RateLimiter(state, clock=clk.now, sleep=clk.sleep)
    assert rl.requests_today == rl.policy.daily_budget
    assert "clamped" in caplog.text
    with pytest.raises(BudgetExhaustedError):
        rl.acquire("https://arxiv.org/src/1234.5678")


def test_requests_today_under_budget_untouched(tmp_path: Path) -> None:
    """合法计数原样加载——钳制只作用于越域值。"""
    clk = _Clock()
    day = time.strftime("%Y-%m-%d", time.gmtime(clk.t))
    state = tmp_path / "rl.json"
    state.write_text(
        json.dumps(
            {"day": day, "requests_today": UNDER_BUDGET_REQUESTS, "buckets": {}}
        )
    )
    rl = RateLimiter(state, clock=clk.now, sleep=clk.sleep)
    assert rl.requests_today == UNDER_BUDGET_REQUESTS
