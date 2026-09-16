"""spike 回放验证 —— tests/fixtures/ 入库真 log 常跑 + bench/work_fixloop/ 终态 .log 走 taxonomy 分类。

入库 fixture（裁自 stagerun-loop1, 干净 clone 也跑）:
  - xelatex-missing-file.log → missing_file:setstack.sty
  - xelatex-fileline-syntax.log → syntax
work_* 是 gitignored 重产物, 缺席时仅跳过 work 扫描用例; 在本地实证:
  - 全量主 log 可解析不崩 (ErrReport 字段健全)
  - 两个已知识别锚点: 2005.11401/zh → soul_err (soul 残留错),
    2106.09685/ctex → missing_tfm:phvb (metric TFM 缺)
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.logparse import parse_log

WORK = Path(__file__).resolve().parents[1] / "bench/work_fixloop"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RS = load_ruleset()

NEED_WORK = pytest.mark.skipif(
    not WORK.is_dir(), reason="bench/work_fixloop 不在本机 (gitignored 重产物)"
)

# 入库真 log 锚点: 文件名 → (n_bang, taxonomy 类, payload)
_FIXTURE_CATS = {
    "xelatex-missing-file.log": (2, "missing_file", "setstack.sty"),
    "xelatex-fileline-syntax.log": (2, "syntax", None),
}


def _main_logs() -> list[Path]:
    """``work_fixloop/<corpus>/<cond>/*.log`` —— 排除 missfont 侧log 与 _texmf 家务目录。"""
    out = []
    for p in sorted(WORK.rglob("*.log")):
        if p.name == "missfont.log" or any(part.startswith("_") for part in p.parts):
            continue
        out.append(p)
    return out


def test_fixture_logs_classify() -> None:
    """入库真 log 走 taxonomy —— 干净 clone 常跑, 锚定 missing_file/syntax 两类。"""
    for name, (n_bang, cat, pay) in _FIXTURE_CATS.items():
        rep = parse_log(FIXTURES / name, RS.warn_patterns)
        assert rep.n_bang == n_bang
        assert rep.tail is not None
        got_cat, got_pay = RS.taxonomy.classify(rep)
        assert got_cat == cat
        assert got_pay == pay


@NEED_WORK
def test_all_main_logs_parseable() -> None:
    logs = _main_logs()
    assert len(logs) >= 16  # noqa: PLR2004 - spike 22 格, 至少 16 篇的量
    cats: dict[str, list[Path]] = {}
    for p in logs:
        rep = parse_log(p, RS.warn_patterns)
        assert rep.n_bang >= 0
        assert rep.tail is not None
        cat, _pay = RS.taxonomy.classify(rep)
        cats.setdefault(cat, []).append(p)
    # 多数格救回后终态 clean (spike 口径 21/22 clean + 1 dirty_pdf)
    assert len(cats.get("clean", [])) >= 15  # noqa: PLR2004


@NEED_WORK
def test_known_residual_categories() -> None:
    soul = WORK / "2005.11401/zh/neurips_2020.log"
    tfm = WORK / "2106.09685/ctex/iclr2022_conference.log"
    if soul.exists():
        cat, _ = RS.taxonomy.classify(parse_log(soul, RS.warn_patterns))
        assert cat == "soul_err"  # spike 唯一未救回残错
    if tfm.exists():
        cat, pay = RS.taxonomy.classify(parse_log(tfm, RS.warn_patterns))
        assert cat == "missing_tfm"
        assert pay == "phvb"
