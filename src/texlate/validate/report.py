"""三级校验结果聚合输出（L0 规则 / L1 CST / L2 编译 log）。

消费侧两个形态：
- ``ok`` / ``hard_failures()`` —— 管线闸：不过 → corrector 重译 / fallback 原文；
- ``feedback()`` —— corrector 字段化反馈（docs/08 §1.2 ``previous_validation_error``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.validate.l0 import Severity

if TYPE_CHECKING:
    from texlate.validate.l0 import L0Report
    from texlate.validate.l1 import TsResult
    from texlate.validate.l2 import L2Verdict

__all__ = ["ValidationReport", "aggregate"]


@dataclass(slots=True)
class ValidationReport:
    """一块译文的 L0/L1/L2 聚合 verdict。

    ``ok`` = 所有在场层全过（缺层不罚——L1 无 node 降级、L2 无 log 缺信息
    都不算失败，只算"该层没说话"）。``l2.log_missing`` 单独可查。
    """

    chunk_id: str | None = None
    l0: L0Report | None = None
    l1: TsResult | None = None
    l2: L2Verdict | None = None

    @property
    def ok(self) -> bool:
        """三级并集判定：任一在场层不过即不过。"""
        if self.l0 is not None and not self.l0.ok:
            return False
        if self.l1 is not None and not self.l1.verdict_ok:
            return False
        return not (self.l2 is not None and not self.l2.log_missing and not self.l2.ok)

    @property
    def n_error(self) -> int:
        """硬判据（error 级）发现总数（L0 issues + L1 不过 + L2 错误数）。"""
        n = 0
        if self.l0 is not None:
            n += self.l0.n_error
        if self.l1 is not None and not self.l1.verdict_ok:
            n += 1
        if self.l2 is not None and not self.l2.log_missing:
            n += self.l2.n_errors
        return n

    @property
    def n_warn(self) -> int:
        """软信号（warn 级）发现总数。"""
        n = 0
        if self.l0 is not None:
            n += self.l0.n_warn
        if self.l2 is not None and not self.l2.log_missing:
            n += self.l2.warnings.total
        return n

    def hard_failures(self) -> list[str]:
        """硬判据（error 级）发现的单层标注列表（人读/聚合统计用）。"""
        out: list[str] = []
        if self.l0 is not None:
            out += [
                f"l0:{i.rule} {i.message}"
                for i in self.l0.issues
                if i.severity is Severity.ERROR
            ]
        if self.l1 is not None and not self.l1.verdict_ok:
            det = []
            if self.l1.parse_errors:
                det.append(f"parse_errors={len(self.l1.parse_errors)}")
            if self.l1.env_mismatches:
                det.append(f"env={len(self.l1.env_mismatches)}")
            if self.l1.unclosed_math:
                det.append(f"math={self.l1.unclosed_math}")
            if self.l1.brace_balance:
                det.append(f"brace={self.l1.brace_balance}")
            ph = self.l1.placeholders
            bad = (
                len(ph.get("missing", []))
                + len(ph.get("unexpected", []))
                + len(ph.get("typos", []))
            )
            if bad:
                det.append(f"ph={bad}")
            out.append(f"l1:cst {' '.join(det) or 'failed'}")
        if self.l2 is not None and not self.l2.log_missing and not self.l2.ok:
            first = self.l2.first_error.head if self.l2.first_error else "?"
            out.append(f"l2:compile ×{self.l2.n_errors} first={first}")
        return out

    def feedback(self) -> str:
        """给 corrector 的字段化错误描述（对应 ``[Error]`` 三段式的第三段）。"""
        parts: list[str] = []
        if self.l0 is not None:
            fb = self.l0.feedback()
            if fb:
                parts.append(fb)
        if self.l1 is not None and not self.l1.verdict_ok:
            parts.extend(
                f"CST {e.get('type', 'ERROR')} at row {e.get('row', '?')}: {e.get('snippet', '')}"
                for e in self.l1.parse_errors[:5]
            )
            parts.extend(
                f"CST env {e.get('kind', '?')}: "
                f"begin={e.get('begin_env')} end={e.get('end_env')} line {e.get('line')}"
                for e in self.l1.env_mismatches[:5]
            )
            ph = self.l1.placeholders
            parts.extend(
                f"placeholder missing: [[{m_}]]" for m_ in ph.get("missing", [])
            )
            parts.extend(
                f"placeholder typo: [[{t.get('found')}]] should be [[{t.get('expected')}]]"
                for t in ph.get("typos", [])
            )
        if (
            self.l2 is not None
            and not self.l2.log_missing
            and self.l2.first_error is not None
        ):
            fe = self.l2.first_error
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
            "l0": self.l0.to_dict() if self.l0 else None,
            "l1": self.l1.to_dict() if self.l1 else None,
            "l2": self.l2.to_dict() if self.l2 else None,
        }

    def summary(self) -> str:
        """单行汇总（看板/日志用）。"""
        cid = self.chunk_id or "?"
        marks = []
        marks.append(
            "L0✗"
            if (self.l0 and not self.l0.ok)
            else ("L0-" if self.l0 is None else "L0✓")
        )
        if self.l1 is None:
            marks.append("L1-")
        else:
            marks.append("L1✓" if self.l1.verdict_ok else "L1✗")
        if self.l2 is None:
            marks.append("L2-")
        elif self.l2.log_missing:
            marks.append("L2?")
        else:
            marks.append("L2✓" if self.l2.ok else "L2✗")
        return f"{cid} {' '.join(marks)} err={self.n_error} warn={self.n_warn}"


def aggregate(
    chunk_id: str | None = None,
    *,
    l0: L0Report | None = None,
    l1: TsResult | None = None,
    l2: L2Verdict | None = None,
) -> ValidationReport:
    """把各层结果聚成 ``ValidationReport``；缺层传 None。"""
    return ValidationReport(chunk_id=chunk_id, l0=l0, l1=l1, l2=l2)
