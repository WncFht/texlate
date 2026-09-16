"""译文校验层：L0 自写规则 always-on / L1 tree-sitter 可选 / L2 编译 log 回灌（规格 docs/08）。

- ``l0.validate_pair``：九规则 src↔zh 相对判定，stdlib 零依赖 always-on；
- ``l1.TsValidator``：tree-sitter CST 增强层，node 子进程 JSONL，无 node 自动降级；
- ``l2.parse_log``：编译 log 双格式错误计数 + warning 分类 + 首错定位；
- ``report.aggregate``：三级结果聚合成单 verdict（``ok``/``feedback()``/``to_dict()``）。
"""

from texlate.validate.l0 import Issue, L0Report, Severity, validate_pair
from texlate.validate.l1 import L1Error, TsBaseline, TsResult, TsValidator
from texlate.validate.l2 import (
    L2Verdict,
    LogError,
    WarningSummary,
    parse_log,
    parse_log_text,
)
from texlate.validate.report import ValidationReport, aggregate

__all__ = [
    "Issue",
    "L0Report",
    "L1Error",
    "L2Verdict",
    "LogError",
    "Severity",
    "TsBaseline",
    "TsResult",
    "TsValidator",
    "ValidationReport",
    "WarningSummary",
    "aggregate",
    "parse_log",
    "parse_log_text",
    "validate_pair",
]
