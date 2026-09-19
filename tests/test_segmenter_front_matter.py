r"""preamble 前置发射（``front_matter``）黑盒测试。

背景：``\begin{abstract}``/``\title``/``\author`` 常见地出现在
``\begin{document}`` **之前**（cls 延迟到 ``\maketitle`` 渲染）——
segmenter preamble 档历史上整段盖过不发块。``front_matter`` 白名单
（``ScanState.front_matter``）开启后逐项前置发射：

- ``abstract`` env → ``context="abstract"`` chunk（env 体走正常主流 emit）
- ``\title{…}``/``\author{…}`` → ``_preamble_chunk_arg`` 子扫描发射，
  context 各为 ``"title"``/``"author"``（KIND_ALIASES→caption/para）

未开项维持整段盖过零行为变化。每条用例过 ``check_invariants``
（恒等重建 + 校验零告警 + pieces 无缝平铺 vtex）——preamble 档内
emit 的「已盖未发前缀补 literal」不变式主要靠平铺断言盯。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from conftest import check_invariants

from texlate.latex import parse_tex
from texlate.pipecore import (
    ENV_FRONT_MATTER,
    default_front_matter,
    front_matter_of,
)

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.latex.model import ScanResult

#: preamble 三件齐活的样张（abstract env 在 \begin{document} 前）
PRE_DOC = (
    "\\documentclass{article}\n"
    "\\title{My Great Paper}\n"
    "\\author{Alice \\and Bob}\n"
    "\\begin{abstract}\n"
    "We propose a method. It works well.\n"
    "\\end{abstract}\n"
    "\\usepackage{amsmath}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\section{Intro}\n"
    "Body para here.\n"
    "\\end{document}\n"
)


def scan(tex: str, fm: frozenset[str]) -> ScanResult:
    """``parse_tex(front_matter=fm)`` + 公共不变式。"""
    res = parse_tex(tex, front_matter=fm)
    check_invariants(res, tex)
    return res


def ctxs(res: ScanResult) -> dict[str, list[str]]:
    """``{context: [content…]}``——按 context 归集 chunk 文面。"""
    out: dict[str, list[str]] = {}
    for c in res.chunks:
        out.setdefault(c.context, []).append(c.content)
    return out


# ------------------------------------------------------------- 单项开/关


def test_fm_empty_keeps_preamble_silent() -> None:
    """``front_matter={}``（历史行为）：前置三件全盖过，只剩正文 chunk。"""
    res = scan(PRE_DOC, frozenset())
    got = ctxs(res)
    assert "abstract" not in got
    assert "title" not in got
    assert "author" not in got
    assert got["section"] == ["Intro"]


def test_fm_abstract_env_emits_chunk() -> None:
    """``{'abstract'}``：preamble abstract env 出 ``context="abstract"`` 块。"""
    res = scan(PRE_DOC, frozenset({"abstract"}))
    got = ctxs(res)
    assert got["abstract"] == ["We propose a method. It works well."]
    assert "title" not in got
    assert "author" not in got


def test_fm_title_arg_emits_chunk() -> None:
    """``{'title'}``：``\\title{…}`` 出 ``context="title"`` 块（→caption kind）。"""
    res = scan(PRE_DOC, frozenset({"title"}))
    got = ctxs(res)
    assert got["title"] == ["My Great Paper"]
    assert "abstract" not in got
    assert "author" not in got


def test_fm_author_arg_emits_chunk() -> None:
    """``{'author'}``：``\\author{…}`` 出 ``context="author"`` 块（→para kind）。"""
    res = scan(PRE_DOC, frozenset({"author"}))
    got = ctxs(res)
    assert got["author"] == ["Alice \\and Bob"]
    assert "abstract" not in got
    assert "title" not in got


def test_fm_all_three() -> None:
    """三件齐开：abstract+title+author 各一块，正文不受影响。"""
    res = scan(PRE_DOC, frozenset({"abstract", "title", "author"}))
    got = ctxs(res)
    assert got["abstract"] == ["We propose a method. It works well."]
    assert got["title"] == ["My Great Paper"]
    assert got["author"] == ["Alice \\and Bob"]
    assert got["section"] == ["Intro"]


# ------------------------------------------------------------- 边界形态


def test_fm_abstract_after_other_front_matter() -> None:
    """``\\title`` 发射后再遇 abstract env：交错 literal 仍无缝平铺。"""
    res = scan(PRE_DOC, frozenset({"title", "abstract"}))
    got = ctxs(res)
    assert got["title"] == ["My Great Paper"]
    assert got["abstract"] == ["We propose a method. It works well."]
    assert "author" not in got  # 未开项依旧盖过


def test_fm_doc_mode_abstract_gets_abstract_ctx() -> None:
    r"""document 内 ``\begin{abstract}`` 同样给 ``context="abstract"``。

    ``_flush_run`` 的 env_stack 判定——此前 doc 内 abstract env 只产
    ``context="para"``（透明 env 直穿），K3 摘要条款够不着。doc 内
    形态不依赖 ``front_matter``（主流 env_begin 本来就 dispatch）。
    """
    tex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{abstract}\n"
        "Doc-mode abstract body.\n"
        "\\end{abstract}\n"
        "After text.\n"
        "\\end{document}\n"
    )
    res = scan(tex, frozenset())
    got = ctxs(res)
    assert got["abstract"] == ["Doc-mode abstract body."]


def test_fm_title_missing_arg_falls_back_cover() -> None:
    r"""``\title`` 无 ``{arg}``（裸 token）：回放+字面盖过，不出块不崩。"""
    tex = (
        "\\documentclass{article}\n"
        "\\title\n"
        "\\begin{document}\n"
        "Body.\n"
        "\\end{document}\n"
    )
    res = scan(tex, frozenset({"title"}))
    assert not [c for c in res.chunks if c.context == "title"]


def test_fm_empty_title_arg_falls_back_cover() -> None:
    r"""``\title{}`` 空参数：同走盖过 bail，不出空块。"""
    tex = (
        "\\documentclass{article}\n"
        "\\title{}\n"
        "\\begin{document}\n"
        "Body.\n"
        "\\end{document}\n"
    )
    res = scan(tex, frozenset({"title"}))
    assert not [c for c in res.chunks if c.context == "title"]


def test_fm_abstract_env_unclosed() -> None:
    r"""preamble abstract 无 ``\end{abstract}``：体吃到文末，不崩。

    env 弹栈时 ``_handle_env_end`` 无匹配只记 stray——残缺输入安全退化。
    """
    tex = (
        "\\documentclass{article}\n"
        "\\begin{abstract}\n"
        "Dangling abstract.\n"
    )
    res = parse_tex(tex, front_matter=frozenset({"abstract"}))
    # 重建恒等 + 平铺仍成立（validate 可能有告警——只查不变式前两条）
    from texlate.latex import reconstruct  # noqa: PLC0415

    assert reconstruct(res) == tex


# ------------------------------------------------------------- 选项面


def test_front_matter_of_defaults() -> None:
    """``front_matter_of({})`` → 缺省 ``{abstract,title}``（作者默认关）。"""
    assert front_matter_of({}) == frozenset({"abstract", "title"})
    assert front_matter_of({"front_matter": None}) == frozenset(
        {"abstract", "title"}
    )


def test_front_matter_of_explicit_dict() -> None:
    """显式 dict：缺键按缺省、显式 False 关、显式 True 开。"""
    assert front_matter_of(
        {"front_matter": {"author": True}}
    ) == frozenset({"abstract", "title", "author"})
    assert front_matter_of(
        {"front_matter": {"abstract": False}}
    ) == frozenset({"title"})
    assert (
        front_matter_of(
            {"front_matter": {"abstract": False, "title": False, "author": False}}
        )
        == frozenset()
    )


def test_default_front_matter_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``TEXLATE_FRONT_MATTER`` 逗号清单 → frozenset；非法名滤掉。"""
    monkeypatch.delenv(ENV_FRONT_MATTER, raising=False)
    assert default_front_matter() == frozenset({"abstract", "title"})
    monkeypatch.setenv(ENV_FRONT_MATTER, "abstract,author,bogus")
    assert default_front_matter() == frozenset({"abstract", "author"})
    monkeypatch.setenv(ENV_FRONT_MATTER, "")
    assert default_front_matter() == frozenset({"abstract", "title"})


# ------------------------------------------------------------- worker 链


def _mk_ctx(tmp_path: Path, options: dict) -> tuple:
    """真实任务行 + TaskCtx + worker（test_fuzz_worker._mk 同形精简版）。"""
    from texlate.server.events import EventBus  # noqa: PLC0415
    from texlate.server.store import Store, new_task_id  # noqa: PLC0415
    from texlate.server.worker import PipelineWorker, Secrets, TaskCtx  # noqa: PLC0415

    store = Store(tmp_path / "t.db")
    store.open()
    bus = EventBus(store)
    worker = PipelineWorker(store, bus, tmp_path)
    task_id = new_task_id()
    row = store.create_task(
        task_id=task_id,
        kind="arxiv",
        target_lang="zh-CN",
        model="m",
        options=options,
    )
    ctx = TaskCtx(
        store=store,
        bus=bus,
        task_id=task_id,
        row=row,
        secrets=Secrets(),
        root=tmp_path / "tasks" / task_id,
    )
    return ctx, worker, store


@pytest.mark.parametrize(
    ("fm_opt", "expect_abs", "expect_caption_min"),
    [
        # 显式 abstract 开 → 摘要块入库（kind=abstract）
        ({"front_matter": {"abstract": True, "title": False}}, True, 0),
        # 全关 → 零摘要零标题
        (
            {
                "front_matter": {
                    "abstract": False,
                    "title": False,
                    "author": False,
                }
            },
            False,
            0,
        ),
        # 空 options → 服务端缺省 abstract+title
        ({}, True, 1),
    ],
)
def test_worker_parse_all_front_matter(
    tmp_path: Path,
    fm_opt: dict,
    *,
    expect_abs: bool,
    expect_caption_min: int,
) -> None:
    """``options.front_matter`` 经 ``ctx.options()`` 进 ``scan_tex_tree``：
    kind=abstract 行出现与否即开/关裁决；title 开时 kind=caption 行 ≥1。
    """
    ctx, worker, _store = _mk_ctx(tmp_path, fm_opt)
    ctx.base_dir.mkdir(parents=True)
    (ctx.base_dir / "main.tex").write_text(PRE_DOC, encoding="utf-8")
    rows, _scans = worker._parse_all(ctx)  # noqa: SLF001 -- 段级直调面（同 test_fuzz_worker）
    kinds = [r["kind"] for r in rows]
    assert ("abstract" in kinds) is expect_abs
    assert sum(1 for k in kinds if k == "caption") >= expect_caption_min
