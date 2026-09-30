"""validate.l0.report — L0 校验 verdict 类型叶 (validate.l0 域缝叶)。

``Severity``/``Issue``/``L0Report``：一对 (src, zh) 校验发现的结构化
verdict——``Issue`` 单条发现（``pos`` zh 侧字符偏移/``expected``/``found``
修复配对），``L0Report`` 聚合（``ok``/``n_error``/``n_warn``/``by_rule``/
``to_dict``/``feedback``）。零依赖叶子，全部 checker 叶与 ``l0.main``
入口共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """问题严重度：error=硬判据（不过 → 重译/回退），warn=软信号（聚合参考）。"""

    ERROR = "error"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class Issue:
    """单条校验发现。

    ``pos`` 是 zh 侧字符偏移（-1 = 无定位）；``expected``/``found``
    承载占位符拼错的修复建议配对。
    """

    rule: str
    severity: Severity
    message: str
    pos: int = -1
    expected: str | None = None
    found: str | None = None

    def to_dict(self) -> dict[str, object]:
        """序列化为 corrector 反馈字段可用的一级字典。"""
        d: dict[str, object] = {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.pos >= 0:
            d["pos"] = self.pos
        if self.expected is not None:
            d["expected"] = self.expected
        if self.found is not None:
            d["found"] = self.found
        return d


@dataclass(slots=True)
class L0Report:
    """一对 (src, zh) 的 L0 校验结果。"""

    src_len: int
    zh_len: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """无 error 级发现即过（warn 不阻塞）。"""
        return not any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def n_error(self) -> int:
        """硬判据（error 级）条数。"""
        return sum(1 for i in self.issues if i.severity is Severity.ERROR)

    @property
    def n_warn(self) -> int:
        """软信号（warn 级）条数。"""
        return sum(1 for i in self.issues if i.severity is Severity.WARN)

    def by_rule(self) -> dict[str, list[Issue]]:
        """按规则名分组。"""
        d: dict[str, list[Issue]] = {}
        for i in self.issues:
            d.setdefault(i.rule, []).append(i)
        return d

    def to_dict(self) -> dict[str, object]:
        """序列化（state.json / errors_report 可落盘）。"""
        return {
            "ok": self.ok,
            "src_len": self.src_len,
            "zh_len": self.zh_len,
            "n_error": self.n_error,
            "n_warn": self.n_warn,
            "issues": [i.to_dict() for i in self.issues],
        }

    def feedback(self) -> str:
        """给带错重翻 corrector 的紧凑错误描述（docs/spec/translate.md 反馈字段化）。"""
        return "\n".join(i.message for i in self.issues if i.severity is Severity.ERROR)

    def __str__(self) -> str:
        """PASS/FAIL 头 + 逐条 ``[级别] 规则：描述``。"""
        head = (
            f"{'PASS' if self.ok else 'FAIL'} (err={self.n_error} warn={self.n_warn})"
        )
        if not self.issues:
            return head
        lines = [
            f"  [{i.severity.value:5s}] {i.rule}: {i.message}" for i in self.issues
        ]
        return head + "\n" + "\n".join(lines)
