"""译文校验层：rules 自写规则 always-on / cst tree-sitter 可选 / logattr 编译 log 回灌（规格 docs/spec/compile.md）。

- ``rules.validate_pair``/``pair_feedback``：``_CHECKERS`` 全表 src↔zh 相对
  判定（条数不手维护——表序即执行序），stdlib 零依赖 always-on；
- ``cst.TsValidator``：tree-sitter CST 增强层，node 子进程 JSONL，无 node 自动降级；
- ``logattr.parse_log``：编译 log 双格式错误计数 + warning 分类 + 首错定位；
- ``report.aggregate``：三级结果聚合成单 verdict（``ok``/``feedback()``/``to_dict()``）。
"""

from texlate.validate.cst import CstError, TsBaseline, TsResult, TsValidator
from texlate.validate.logattr import (
    LogError,
    LogVerdict,
    WarningSummary,
    parse_log,
    parse_log_text,
)
from texlate.validate.report import ValidationReport, aggregate
from texlate.validate.rules import (
    Issue,
    RulesReport,
    Severity,
    pair_feedback,
    validate_pair,
)

__all__ = [
    "CstError",
    "Issue",
    "LogError",
    "LogVerdict",
    "RulesReport",
    "Severity",
    "TsBaseline",
    "TsResult",
    "TsValidator",
    "ValidationReport",
    "WarningSummary",
    "aggregate",
    "pair_feedback",
    "parse_log",
    "parse_log_text",
    "validate_pair",
]
