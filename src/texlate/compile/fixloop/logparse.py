"""re-export shim —— 实现已上提 ``texlate.compile.logparse``（compile 层共享地基）。

C3 地基归位：log 解析/taxonomy 是 compile 层共享件（``loginfo``/
``judge``/``proc`` 同层消费），不再寄居依赖 compile 的 fixloop 子包。
旧路径 ``texlate.compile.fixloop.logparse`` 名面转口守恒（``engine``/
``ruleset``/``proc``/``judge``/tests 等旧 import 不动，含私名面）；
新代码一律直引 ``texlate.compile.logparse``。

退场名（零消费面死件，不再转口）：``_WARN_FILELINE_RE``/
``_FATAL_TRAILER_RE``（错误行判定并 ``texlog.match_error_line``）、
``_attribute_warns``（第二遍栈走查并进 ``_AttrWarns.feed`` 事件投影）、
texlog 间接名（``ERR_FILELINE_RE``/``file_stack_at`` 等——从来直引
``texlate.texlog``，非本面契约）。
"""

from texlate.compile.logparse import (  # noqa: F401
    _CAP_BRACKET_RX,
    _CAP_BRACKET_TAG,
    _CAP_CS_RX,
    _CAP_HEAD_RX,
    _CAP_LN_ROW_RX,
    _CAP_MACRO_RX,
    _CAP_UPSTREAM_RECURSION_CS,
    _CS_NAME_RE,
    _CTX_HEAD_RE,
    _ERRS_MAX,
    _FILE_ATTRIBUTED_WARNS,
    _LINE_NO_RE,
    _LN_ROW_RE,
    _PAYLOAD_SCANS,
    _PRE_LINES,
    _RUNAWAY_PAGE_MAX,
    _RUNAWAY_PAGE_RX,
    _RUNAWAY_VBOX_DENSITY,
    _RUNAWAY_VBOX_MIN,
    _RUNAWAY_VBOX_RX,
    ErrReport,
    Taxonomy,
    _AttrWarns,
    _cap_bracket_tag,
    _cap_verdict_cat,
    _capacity_payload,
    _capacity_pending,
    _collect_warnings,
    _ctx_tail_css,
    _is_err_line,
    _is_runaway_output,
    _payload,
    parse_log,
    parse_text,
)

__all__ = ["ErrReport", "Taxonomy", "parse_log", "parse_text"]
