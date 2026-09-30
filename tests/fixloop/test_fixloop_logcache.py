"""LoopCtx._texts × compile 重写件 —— stale-log 缓存失效回归 (2403.00013)。

bug 机制：规则在轮内经 ``ctx.read`` 早读 ``{stem}.log`` 即把 pre-fix
内容灌入进程内缓存; 每轮 ``eng.compile`` 重写盘上 log 后，缓存仍供
旧文 —— 后续轮一切扫 log 的规则在残影上判空拒修 (2403.00013 五枚
misschar/font 规则实测全灭)。修复 = 每个 ``eng.compile`` (分类轮/
同轮终编/次级探针/兜底) 后 ``ctx.invalidate_suffixes(_VOLATILE_EXTS)``
失效 volatile 族 (``.log`` + ``_AUX_WRITE_EXTS``——后者同被 compile
重写且被 aux-sweep 清场)。
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from _fixloopkit import MockEngine, make_proj, mini_rs

from texlate.compile.fixloop import builtins, fixloop
from texlate.compile.fixloop.engine import _VOLATILE_EXTS, LoopCtx


# ---------------------------------------------------------------- 单元：缓存语义
def test_read_caches_until_invalidate(tmp_path: Path) -> None:
    """ctx.read 读穿缓存——compile 改盘后 invalidate 才让下读走盘。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    log = tmp_path / "main.log"
    log.write_text("round-1 log\n", encoding="utf-8")
    assert ctx.read(log) == "round-1 log\n"
    log.write_text("round-2 log\n", encoding="utf-8")  # 模拟 compile 重写
    assert ctx.read(log) == "round-1 log\n"  # 缓存直供——失效前即 stale
    ctx.invalidate_suffixes(_VOLATILE_EXTS)
    assert ctx.read(log) == "round-2 log\n"


def test_invalidate_volatile_scope(tmp_path: Path) -> None:
    """失效面只盖 compile/sweep 改盘族 (.log + _AUX_WRITE_EXTS)。

    ``.tex`` 源缓存保留 (compile 不重写源，跨轮复读是缓存本职);
    缺席→新建的 stale-None 条目同失效 (``_texts`` 缓存 None 也挡新读)。
    """
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    tex = tmp_path / "main.tex"
    tex.write_text("src-v1\n", encoding="utf-8")
    volatiles: list[Path] = []
    for name in ("main.log", "main.aux", "main.out", "main.toc"):
        p = tmp_path / name
        p.write_text(f"{name} v1\n", encoding="utf-8")
        volatiles.append(p)
    for f in [tex, *volatiles]:
        assert ctx.read(f) is not None
    absent_log = tmp_path / "missfont.log"
    assert ctx.read(absent_log) is None  # 缺席也入缓存 (stale-None 面)
    n = ctx.invalidate_suffixes(_VOLATILE_EXTS)
    assert n == len(volatiles) + 1  # 4 存在件 + 1 stale-None
    # 行为面断言：volatile 件盘后重写 → 下读即新文; .tex 仍供缓存旧文
    # (compile 不触碰源——保留它的跨轮缓存正是 _texts 本职)。
    for f in volatiles:
        f.write_text(f"{f.name} v2\n", encoding="utf-8")
        assert ctx.read(f) == f"{f.name} v2\n"
    tex.write_text("src-v2\n", encoding="utf-8")
    assert ctx.read(tex) == "src-v1\n"  # 源件缓存保留
    absent_log.write_text("missfont\n", encoding="utf-8")
    assert ctx.read(absent_log) == "missfont\n"  # stale-None → 新建件重读


# ---------------------------------------------------------------- 集成：轮间新鲜
def _sniffer_rule() -> dict:
    """读 ``{stem}.log`` 后即拒修的探针规则——复刻 csfix/misschar 域
    的早读 - 拒修形状; 拒修位让同轮后续规则照常派发。"""
    return {
        "id": "log_sniffer",
        "phase": "loop",
        "order": 1,
        "when": {"always": True},
        "action": {"kind": "builtin_transform", "function": "_test_log_sniffer"},
    }


def _sniffer(sniffs: list[str]) -> Callable:
    def fn(ctx: LoopCtx, eng: object, payload: object, params: object) -> tuple:
        del eng, payload, params
        sniffs.append(ctx.read(ctx.wdir / "main.log") or "")
        return False, "sniffed"

    return fn


def test_round2_rule_reads_fresh_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """r1 早读 log 不毒害 r2——第二轮规则读到新 compile 落盘的 log。

    stale 情形下 r2 的 ``ctx.read(main.log)`` 仍供 r1 旧文，``Missing
    character`` 永不可见——正是 2403.00013 的拒修链。
    """
    make_proj(tmp_path)
    sniffs: list[str] = []
    monkeypatch.setitem(builtins.TRANSFORM_FNS, "_test_log_sniffer", _sniffer(sniffs))
    rs = mini_rs(
        rules=[
            _sniffer_rule(),
            {
                "id": "mark",
                "phase": "loop",
                "order": 2,
                "when": {"category": "boom"},
                "action": {
                    "kind": "regex_rewrite",
                    "params": {
                        "exts": [".tex"],
                        "rewrites": [{"pattern": "hi", "repl": "hi % fixed"}],
                    },
                },
            },
        ],
        taxonomy=[{"id": "boom", "scope": "head", "pattern": "BOOM"}],
    )
    eng = MockEngine(
        [
            {"log": "! BOOM r1\n"},
            {
                "log": "! BOOM r2\n"
                "Missing character: There is no 中 (U+4E2D) in font x\n"
            },
        ]
    )
    cell = fixloop(tmp_path, eng, ruleset=rs)
    # r1 mark 应用进 r2; r2 mark 被 dedup → 候选耗尽 → unfixable
    assert cell["verdict"] == "unfixable:boom"
    assert len(sniffs) >= 2  # noqa: PLR2004 -- r1/r2 各一读
    assert "BOOM r1" in sniffs[0]
    assert "BOOM r2" in sniffs[1]
    assert "Missing character" in sniffs[1]


def test_secondary_dispatch_reads_probe_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """次级派发探针重写了 log——孪生候选上的规则须读探针新 log。

    探针 compile 同写 ``{stem}.log``; 不复读则孪生规则仍在主轮 log
    残影上拒修 (探针即 ``_SEC_PROBE`` 复用臂，白烧一发编译)。
    """
    make_proj(tmp_path)
    sniffs: list[str] = []
    monkeypatch.setitem(builtins.TRANSFORM_FNS, "_test_log_sniffer", _sniffer(sniffs))
    rs = mini_rs(
        rules=[_sniffer_rule()],
        taxonomy=[
            {"id": "boom", "scope": "head", "pattern": "BOOM"},
            {"id": "foo", "scope": "head", "pattern": "FOO"},
        ],
    )
    eng = MockEngine(
        [
            {"log": "! BOOM round\n"},
            {"log": "! FOO probe\n"},  # 探针 (best_effort) 写不同 log
        ]
    )
    eng.halt_on_error = True  # 探针闸门：单错 log 才需探针补全错误面
    cell = fixloop(tmp_path, eng, ruleset=rs)
    assert cell["verdict"] == "unfixable:boom"
    # r1 主派发读主轮 log → 候选耗尽 → 探针后孪生派发读探针 log
    assert sniffs == ["! BOOM round\n", "! FOO probe\n"]
