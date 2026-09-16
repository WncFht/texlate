"""L1 tree-sitter 层测试 —— node/deps 不在场时整体 skip（可选组件语义本身）。

开发态依赖解析：bench/ts/node_modules 有 tree-sitter + @pfoerster/tree-sitter-latex，
用 TEXLATE_TS_NODE_PATH 指过去即可，不复制不重装。
"""

import shutil
from pathlib import Path

import pytest

from texlate.validate.l1 import TsBaseline, TsValidator

REPO = Path(__file__).resolve().parents[1]
BENCH_NM = REPO / "bench" / "ts" / "node_modules"

# 收集期只查 PATH/纯路径——可用性终判（含 worker.js）放模块 fixture，
# 收集阶段不构造校验器
need_l1 = pytest.mark.skipif(
    shutil.which("node") is None or not (BENCH_NM / "tree-sitter").is_dir(),
    reason="node 或 tree-sitter 依赖不在场（可选组件；bench/ts 跑 npm ci 即恢复）",
)


@pytest.fixture(scope="module")
def v() -> TsValidator:
    val = TsValidator(node_path=BENCH_NM)
    if not val.available():
        pytest.skip("L1 依赖不可用（可选组件）")
    return val


SRC = "We propose [[MATH_1]] in \\begin{equation}\nE=mc^2\n\\end{equation}.\n"
ZH_CLEAN = "我们提出 [[MATH_1]] 于 \\begin{equation}\nE=mc^2\n\\end{equation}。\n"
ZH_BROKEN = "我们提出 于 \\begin{equation}\nE=mc^2\n\\end{equationx}。\n"  # 丢占位符 + \end 改名


@need_l1
def test_batch_clean_and_broken(v: TsValidator) -> None:
    res = v.validate_batch(
        [
            {"id": "ok", "tex": ZH_CLEAN, "expect": ["MATH_1"]},
            {"id": "bad", "tex": ZH_BROKEN, "expect": ["MATH_1"]},
        ]
    )
    ok_r, bad_r = res
    assert ok_r.id == "ok"
    assert ok_r.ok
    assert bad_r.id == "bad"
    assert not bad_r.ok
    assert bad_r.env_mismatches  # \end 改名被 CST 抓到
    assert "MATH_1" in bad_r.placeholders["missing"]


@need_l1
def test_baseline_relative_mode(v: TsValidator) -> None:
    """相对判定：baseline 带 ERROR 的源签名不拖累译文判定。"""
    src_with_gap = "\\inferrule{A}{B} 文本。"  # grammar 空隙命令产生 baseline ERROR
    base = v.sign(src_with_gap)
    assert base.parse_errors >= 0  # 签名可用即对
    res = v.validate(src_with_gap, baseline=base)  # 原样译文 vs 自身基线
    assert res.ok_relative is True


@need_l1
def test_resident_mode() -> None:
    with TsValidator(
        node_path=BENCH_NM if (BENCH_NM / "tree-sitter").is_dir() else None
    ) as daemon:
        base = daemon.sign(SRC)
        res = daemon.validate(ZH_BROKEN, baseline=base, expect=["MATH_1"])
        assert res.ok_relative is False
        res2 = daemon.validate(ZH_CLEAN, baseline=base, expect=["MATH_1"])
        assert res2.ok_relative is True


@need_l1
def test_sign_returns_baseline(v: TsValidator) -> None:
    base = v.sign(SRC)
    assert isinstance(base, TsBaseline)
    assert base.parse_errors == 0


def test_unavailable_degrades() -> None:
    bad = TsValidator(node="/nonexistent-node", worker_dir="/nonexistent")
    assert not bad.available()


def test_baseline_roundtrip() -> None:
    b = TsBaseline(parse_errors=1, env_mismatches=2, unclosed_math=3, brace_balance=-1)
    assert TsBaseline.from_dict(b.to_dict()) == b
