"""三级校验结果聚合输出（rules 自写规则 / cst tree-sitter / logattr 编译 log）。

消费侧两个形态：
- ``ok`` / ``hard_failures()`` —— 管线闸：不过 → corrector 重译 / fallback 原文；
- ``feedback()`` —— corrector 字段化反馈（docs/spec/translate.md ``previous_validation_error``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.validate.rules import Severity

if TYPE_CHECKING:
    from texlate.validate.cst import TsResult
    from texlate.validate.logattr import LogVerdict
    from texlate.validate.rules import RulesReport

__all__ = ["ValidationReport", "aggregate"]


@dataclass(slots=True)
class ValidationReport:
    """一块译文的三层聚合 verdict。

    ``ok`` = 所有在场层全过（缺层不罚——cst 无 node 降级、logattr 无 log
    缺信息都不算失败，只算"该层没说话"）。``logattr.log_missing`` 单独可查。
    """

    chunk_id: str | None = None
    rules: RulesReport | None = None
    cst: TsResult | None = None
    logattr: LogVerdict | None = None

    @property
    def ok(self) -> bool:
        """三级并集判定：任一在场层不过即不过。"""
        if self.rules is not None and not self.rules.ok:
            return False
        if self.cst is not None and not self.cst.verdict_ok:
            return False
        return not (
            self.logattr is not None
            and not self.logattr.log_missing
            and not self.logattr.ok
        )

    @property
    def n_error(self) -> int:
        """硬判据（error 级）发现总数（rules issues + cst 不过 + logattr 错误数）。"""
        n = 0
        if self.rules is not None:
            n += self.rules.n_error
        if self.cst is not None and not self.cst.verdict_ok:
            n += 1
        if self.logattr is not None and not self.logattr.log_missing:
            n += self.logattr.n_errors
        return n

    @property
    def n_warn(self) -> int:
        """软信号（warn 级）发现总数。"""
        n = 0
        if self.rules is not None:
            n += self.rules.n_warn
        if self.logattr is not None and not self.logattr.log_missing:
            n += self.logattr.warnings.total
        return n

    def hard_failures(self) -> list[str]:
        """硬判据（error 级）发现的单层标注列表（人读/聚合统计用）。"""
        out: list[str] = []
        if self.rules is not None:
            out += [
                f"rules:{i.rule} {i.message}"
                for i in self.rules.issues
                if i.severity is Severity.ERROR
            ]
        if self.cst is not None and not self.cst.verdict_ok:
            det = []
            if self.cst.parse_errors:
                det.append(f"parse_errors={len(self.cst.parse_errors)}")
            if self.cst.env_mismatches:
                det.append(f"env={len(self.cst.env_mismatches)}")
            if self.cst.unclosed_math:
                det.append(f"math={self.cst.unclosed_math}")
            if self.cst.brace_balance:
                det.append(f"brace={self.cst.brace_balance}")
            ph = self.cst.placeholders
            bad = (
                len(ph.get("missing", []))
                + len(ph.get("unexpected", []))
                + len(ph.get("typos", []))
            )
            if bad:
                det.append(f"ph={bad}")
            out.append(f"cst:{' '.join(det) or 'failed'}")
        if (
            self.logattr is not None
            and not self.logattr.log_missing
            and not self.logattr.ok
        ):
            first = self.logattr.first_error.head if self.logattr.first_error else "?"
            out.append(f"logattr:compile ×{self.logattr.n_errors} first={first}")
        return out

    def feedback(self) -> str:
        """给 corrector 的字段化错误描述（对应 ``[Error]`` 三段式的第三段）。"""
        parts: list[str] = []
        if self.rules is not None:
            fb = self.rules.feedback()
            if fb:
                parts.append(fb)
        if self.cst is not None and not self.cst.verdict_ok:
            parts.extend(
                f"CST {e.get('type', 'ERROR')} at row {e.get('row', '?')}: {e.get('snippet', '')}"
                for e in self.cst.parse_errors[:5]
            )
            parts.extend(
                f"CST env {e.get('kind', '?')}: "
                f"begin={e.get('begin_env')} end={e.get('end_env')} line {e.get('line')}"
                for e in self.cst.env_mismatches[:5]
            )
            ph = self.cst.placeholders
            parts.extend(
                f"placeholder missing: [[{m_}]]" for m_ in ph.get("missing", [])
            )
            parts.extend(
                f"placeholder typo: [[{t.get('found')}]] should be [[{t.get('expected')}]]"
                for t in ph.get("typos", [])
            )
        if (
            self.logattr is not None
            and not self.logattr.log_missing
            and self.logattr.first_error is not None
        ):
            fe = self.logattr.first_error
            where = f"{fe.tex_file or '?'}:{fe.tex_line}" if fe.tex_line else ""
            parts.append(f"compile error {where} {fe.head}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """三级全量序列化（state.json / errors_report 可落盘）。"""
        return {
            "chunk_id": self.chunk_id,
            "ok": self.ok,
            "n_error": self.n_error,
            "n_warn": self.n_warn,
            "rules": self.rules.to_dict() if self.rules else None,
            "cst": self.cst.to_dict() if self.cst else None,
            "logattr": self.logattr.to_dict() if self.logattr else None,
        }

    def summary(self) -> str:
        """单行汇总（看板/日志用）。"""
        cid = self.chunk_id or "?"
        marks = []
        marks.append(
            "rules✗"
            if (self.rules and not self.rules.ok)
            else ("rules-" if self.rules is None else "rules✓")
        )
        if self.cst is None:
            marks.append("cst-")
        else:
            marks.append("cst✓" if self.cst.verdict_ok else "cst✗")
        if self.logattr is None:
            marks.append("logattr-")
        elif self.logattr.log_missing:
            marks.append("logattr?")
        else:
            marks.append("logattr✓" if self.logattr.ok else "logattr✗")
        return f"{cid} {' '.join(marks)} err={self.n_error} warn={self.n_warn}"


def aggregate(
    chunk_id: str | None = None,
    *,
    rules: RulesReport | None = None,
    cst: TsResult | None = None,
    logattr: LogVerdict | None = None,
) -> ValidationReport:
    """把各层结果聚成 ``ValidationReport``；缺层传 None。"""
    return ValidationReport(chunk_id=chunk_id, rules=rules, cst=cst, logattr=logattr)
