"""fixloop llm_hook — escalate_llm 契约层单测 (FakeTranslator, 不触网)。

测面: JSON 契约 (裸/fence/单对象/畸形) + patch 应用闸 (精确一次/路径/
扩展名/banned 构造/no-op) + 调用面 (Translator 异常/超时放弃/空错误短路)
+ engine 集成 (undefined_cs → escalate → patch → clean)。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import pytest
from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

import texlate.compile.fixloop.llm_hook as llm_hook_mod
from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.fixloop.logparse import ErrReport, parse_text

if TYPE_CHECKING:
    from pathlib import Path

MAIN_TEX = (
    "\\documentclass{article}\n\\begin{document}\nhello \\mycs world\n\\end{document}\n"
)
UNDEF_CS_LOG = "! Undefined control sequence.\nl.3 \\mycs\n"
PATCH = {"file": "main.tex", "old": "\\mycs", "new": "\\emph{mycs}"}
#: 超时放弃测试的墙钟余量 (0.1s 预算 + 线程调度抖动)
_ABANDON_SLACK_S = 2.0


class FakeTranslator:
    """MockTranslator 式假后端: 逐次吐编排好的回复 (str) 或抛错 (异常实例)。"""

    def __init__(self, replies: list, *, delay: float = 0.0) -> None:
        self.replies = list(replies)
        self.delay = delay
        self.calls: list[dict[str, str]] = []

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        del temperature, max_tokens, response_format
        self.calls.append({"system": system, "user": user})
        if self.delay:
            await asyncio.sleep(self.delay)
        r = self.replies.pop(0) if self.replies else '{"patches":[]}'
        if isinstance(r, BaseException):
            raise r
        return r


def _ctx(
    tmp_path: Path,
    main: str = MAIN_TEX,
    **kw: Any,  # noqa: ANN401  # LoopCtx 旋钮透传
) -> LoopCtx:
    make_proj(tmp_path, main)
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", **kw)


def _rep(log: str = UNDEF_CS_LOG) -> ErrReport:
    rep = parse_text(log)
    assert rep.first  # 测试前置: 得有错才有 escalate 语义
    return rep


# ---------------------------------------------------------------- 契约: 应用


def test_hook_applies_patch_direct_call(tmp_path: Path) -> None:
    tr = FakeTranslator([json.dumps({"patches": [PATCH]})])
    ctx = _ctx(tmp_path)
    applied, note = make_llm_hook(translator=tr)(ctx, _rep())
    assert applied is True
    assert "llm_hook" in note
    assert "main.tex" in note
    assert "\\emph{mycs}" in (tmp_path / "main.tex").read_text()
    assert tr.calls  # 打了一次模型


def test_hook_json_fence_and_bare_object(tmp_path: Path) -> None:
    fenced = '```json\n{"patches": [{"file": "main.tex", "old": "\\\\mycs", "new": "ok"}]}\n```'
    tr = FakeTranslator([fenced])
    applied, _ = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is True
    assert "ok" in (tmp_path / "main.tex").read_text()


def test_hook_bare_patch_object(tmp_path: Path) -> None:
    tr = FakeTranslator([json.dumps(PATCH)])  # 无 patches 键的裸对象
    applied, _ = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is True


def test_hook_multi_patch_multi_file(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "macros.sty").write_text("\\def\\a{x}\n", encoding="utf-8")
    patches = {
        "patches": [
            PATCH,
            {"file": "macros.sty", "old": "\\def\\a{x}", "new": "\\def\\a{y}"},
        ]
    }
    tr = FakeTranslator([json.dumps(patches)])
    ctx = _ctx(tmp_path)
    applied, note = make_llm_hook(translator=tr)(ctx, _rep())
    assert applied is True
    assert "2/2" in note
    assert "\\def\\a{y}" in (tmp_path / "macros.sty").read_text()


# ---------------------------------------------------------------- 契约: 拒收


def test_hook_old_not_exactly_once(tmp_path: Path) -> None:
    main = MAIN_TEX + "\\mycs\n"  # \mycs 出现两次
    tr = FakeTranslator([json.dumps({"patches": [PATCH]})])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path, main), _rep())
    assert applied is False
    assert "matched 2x" in note


def test_hook_old_missing(tmp_path: Path) -> None:
    bad = {"file": "main.tex", "old": "\\nosuchcs", "new": "x"}
    tr = FakeTranslator([json.dumps({"patches": [bad]})])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is False
    assert "matched 0x" in note


def test_hook_path_escape_and_ext(tmp_path: Path) -> None:
    patches = {
        "patches": [
            {"file": "../evil.tex", "old": "x", "new": "y"},
            {"file": "refs.bib", "old": "x", "new": "y"},
            {"file": "/etc/passwd", "old": "x", "new": "y"},
        ]
    }
    tr = FakeTranslator([json.dumps(patches)])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is False
    assert "escapes workdir" in note  # ../ 与绝对路径同因
    assert "not a .tex/.sty/.cls" in note  # refs.bib 扩展名被拦


def test_hook_noop_patch(tmp_path: Path) -> None:
    noop = {"file": "main.tex", "old": "\\mycs", "new": "\\mycs"}
    tr = FakeTranslator([json.dumps({"patches": [noop]})])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is False
    assert "no-op" in note


@pytest.mark.parametrize(
    "evil_new",
    [
        "\\immediate\\write18{rm -rf /}",
        "\\pdfsystem{ls}",
        "\\input{/etc/passwd}",
        "\\input{../../secret.tex}",
        '\\input|"cat /etc/passwd"',
        "\\directlua{os.execute('id')}",
    ],
    ids=[
        "write18",
        "pdfsystem",
        "abs_input",
        "dotdot_input",
        "pipe_input",
        "directlua",
    ],
)
def test_hook_banned_constructs(tmp_path: Path, evil_new: str) -> None:
    bad = {"file": "main.tex", "old": "\\mycs", "new": evil_new}
    tr = FakeTranslator([json.dumps({"patches": [bad]})])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is False
    assert "banned" in note
    assert "\\mycs" in (tmp_path / "main.tex").read_text()  # 文件未动


def test_hook_empty_and_malformed(tmp_path: Path) -> None:
    for reply in ('{"patches":[]}', "I cannot fix this", "{}", '{"patches": "x"}'):
        tr = FakeTranslator([reply])
        applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
        assert applied is False, reply
        assert "llm_hook" in note


def test_hook_max_patches_cap(tmp_path: Path) -> None:
    patches = [PATCH] + [
        {"file": "main.tex", "old": f"s{i}", "new": "x"} for i in range(10)
    ]
    tr = FakeTranslator([json.dumps({"patches": patches})])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is True
    assert "over cap" in note


# ---------------------------------------------------------------- 调用面


def test_hook_translator_error_recoverable(tmp_path: Path) -> None:
    tr = FakeTranslator([TimeoutError("upstream hang")])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), _rep())
    assert applied is False
    assert "call failed" in note
    assert "TimeoutError" in note


def test_hook_abandoned_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_hook_mod, "_ABANDON_GRACE_S", 0.05)
    tr = FakeTranslator(['{"patches":[]}'], delay=5.0)
    hook = make_llm_hook(translator=tr, timeout_s=0.05)
    t0 = time.monotonic()
    applied, note = hook(_ctx(tmp_path), _rep())
    assert time.monotonic() - t0 < _ABANDON_SLACK_S
    assert applied is False
    assert "exceeded" in note


def test_hook_no_error_shortcircuit(tmp_path: Path) -> None:
    tr = FakeTranslator([])
    applied, note = make_llm_hook(translator=tr)(_ctx(tmp_path), ErrReport())
    assert applied is False
    assert "no error context" in note
    assert not tr.calls  # 无错不烧 token


def test_hook_warn_only_rep_not_blocked(tmp_path: Path) -> None:
    # warn_* 伪类别轮: 无 '!' 行但 tail 有诊断 —— 早退闸不得误杀
    rep = parse_text("Missing character: There is no x in font cmr10!\n")
    tr = FakeTranslator([json.dumps({"patches": [PATCH]})])
    applied, _ = make_llm_hook(translator=tr)(_ctx(tmp_path), rep)
    assert applied is True
    assert tr.calls


def test_hook_prompt_carries_ctx(tmp_path: Path) -> None:
    tr = FakeTranslator(['{"patches":[]}'])
    ctx = _ctx(tmp_path)
    ctx.err_cat, ctx.err_pay = "undefined_cs", "mycs"
    ctx.actions.append({"round": 1, "rule": "cs_targeted_fix", "detail": "miss"})
    make_llm_hook(translator=tr)(ctx, _rep())
    user = tr.calls[0]["user"]
    assert "undefined_cs" in user
    assert "mycs" in user
    assert "cs_targeted_fix" in user  # 已尝试历史进 prompt
    assert "\\documentclass" in user  # 出错文件片段进 prompt


# ---------------------------------------------------------------- engine 集成


def test_fixloop_escalate_llm_recovers(tmp_path: Path) -> None:
    tr = FakeTranslator([json.dumps({"patches": [PATCH]})])
    eng = MockEngine(
        [
            {"log": UNDEF_CS_LOG},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(
        make_proj(tmp_path, MAIN_TEX), eng, llm_hook=make_llm_hook(translator=tr)
    )
    assert cell["verdict"] == "clean"
    assert tr.calls
    # err_cat/err_pay 未挂 (冻结期 engine 不改) → log 摘要担纲诊断信号
    assert "Undefined control sequence" in tr.calls[0]["user"]
    detail = next(
        a["detail"] for a in cell["actions"] if a["rule"] == "undefined_cs_guess"
    )
    assert detail.startswith("llm_hook")


def test_fixloop_escalate_llm_all_rejected_continues(tmp_path: Path) -> None:
    bad = {"file": "main.tex", "old": "ZZZ", "new": "x"}
    tr = FakeTranslator([json.dumps({"patches": [bad]})])
    eng = MockEngine([{"log": UNDEF_CS_LOG}])
    cell = fixloop(
        make_proj(tmp_path, MAIN_TEX), eng, llm_hook=make_llm_hook(translator=tr)
    )
    assert cell["verdict"] == "unfixable:undefined_cs"  # 未修复, 循环按原语义收束
    assert tr.calls  # 但 hook 确实被调过
