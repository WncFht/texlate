"""spike 回放验证 —— tests/fixtures/ 入库真 log 常跑 + bench/work_fixloop/ 终态 .log 走 taxonomy 分类。

入库 fixture（干净 clone 也跑）:
  - fixtures/logs/manifest.json 全行 fixloop 锚点（n_bang/category/payload 由
    extractor 实算生成）——本表直接派生自 manifest，不另手写漂移
  - fixtures/ 顶级两件（不在 logs/ 内, 保持手写）:
    xelatex-missing-file.log → missing_file:setstack.sty
    xelatex-fileline-syntax.log → syntax
work_* 是 gitignored 重产物, 缺席时仅跳过 work 扫描用例; 在本地实证:
  - 全量主 log 可解析不崩 (ErrReport 字段健全)
  - 两个已知识别锚点: 2005.11401/zh → soul_err (soul 残留错),
    2106.09685/ctex → missing_tfm:phvb (metric TFM 缺)
"""

import json
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.logparse import parse_log

WORK = Path(__file__).resolve().parents[1] / "bench/work_fixloop"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOGS = FIXTURES / "logs"


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（坏 yaml 报 test fail 而非 collection error）。"""
    return load_ruleset()


NEED_WORK = pytest.mark.skipif(
    not WORK.is_dir(), reason="bench/work_fixloop 不在本机 (gitignored 重产物)"
)

# 入库真 log 锚点: 路径 → (n_bang, taxonomy 类, payload)
# fixtures/logs/ 行派生自 manifest.json fixloop 字段；顶级两件为 manifest 前
# 入库的早期 fixture, 不在 logs/ 内故保持手写。
_FIXTURE_CATS: dict[Path, tuple[int, str, str | None]] = {
    LOGS / row["file"]: (
        row["fixloop"]["n_bang"],
        row["fixloop"]["category"],
        row["fixloop"]["payload"],
    )
    for row in json.loads((LOGS / "manifest.json").read_text(encoding="utf-8"))
}
_FIXTURE_CATS[FIXTURES / "xelatex-missing-file.log"] = (
    2,
    "missing_file",
    "setstack.sty",
)
_FIXTURE_CATS[FIXTURES / "xelatex-fileline-syntax.log"] = (2, "syntax", None)


def _main_logs() -> list[Path]:
    """``work_fixloop/<corpus>/<cond>/*.log`` —— 排除 missfont 侧log 与 _texmf 家务目录。"""
    out = []
    for p in sorted(WORK.rglob("*.log")):
        if p.name == "missfont.log" or any(part.startswith("_") for part in p.parts):
            continue
        out.append(p)
    return out


def test_fixture_logs_classify() -> None:
    """入库真 log 走 taxonomy —— manifest 全行 + 顶级两件, 干净 clone 常跑。"""
    for path, (n_bang, cat, pay) in _FIXTURE_CATS.items():
        rep = parse_log(path, _rs().warn_patterns)
        assert rep.n_bang == n_bang
        assert rep.tail is not None
        got_cat, got_pay = _rs().taxonomy.classify(rep)
        assert got_cat == cat
        assert got_pay == pay


@NEED_WORK
def test_all_main_logs_parseable() -> None:
    logs = _main_logs()
    assert len(logs) >= 16  # noqa: PLR2004 - spike 22 格, 至少 16 篇的量
    cats: dict[str, list[Path]] = {}
    for p in logs:
        rep = parse_log(p, _rs().warn_patterns)
        assert rep.n_bang >= 0
        assert rep.tail is not None
        cat, _pay = _rs().taxonomy.classify(rep)
        cats.setdefault(cat, []).append(p)
    # 多数格救回后终态 clean (spike 口径 21/22 clean + 1 dirty_pdf)
    assert len(cats.get("clean", [])) >= 15  # noqa: PLR2004


@NEED_WORK
def test_known_residual_categories() -> None:
    soul = WORK / "2005.11401/zh/neurips_2020.log"
    tfm = WORK / "2106.09685/ctex/iclr2022_conference.log"
    if soul.exists():
        cat, _ = _rs().taxonomy.classify(parse_log(soul, _rs().warn_patterns))
        assert cat == "soul_err"  # spike 唯一未救回残错
    if tfm.exists():
        cat, pay = _rs().taxonomy.classify(parse_log(tfm, _rs().warn_patterns))
        assert cat == "missing_tfm"
        assert pay == "phvb"
