"""ruleset._ruleset_vocab — when/condition/action/engines 词表常量簇 (C5 拆叶)。

``_ACTION_KINDS``/``_PHASES``/``_MODES``/``_ACTION_KEYS``/
``_ACTION_PARAM_KEYS``/``_SCAN_PATTERN_KEYS``/``_REWRITE_KEYS``/
``_COND_*``/``_FILESET_KEYS``/``_ENGINE_*``/``_DEGRADE_VALUES``/
``_FALLBACK_VALUES``/``_TAXONOMY_SCOPES``/``_BUILTIN_CATS``/
``_WHEN_*``/``_MATCH_SURFACES``/``_MECH_ID_RX`` 与 ``RULES_PATH``
规则库根——纯数据叶，无 builtins 链依赖 (``loginfo`` 惰性引
``RULES_PATH`` 的轻径保持)。
"""

from __future__ import annotations

import re
from pathlib import Path

#: 规则库根：2026-09-17 起为 ``rules/`` 目录（_yamlish.load_yaml 目录感知
#: 合并多分片; 序敏感段 taxonomy/warnings 各自单文件承载）。``Ruleset.load``
#: 传显式单文件路径仍兼容（部分规则集亦可单独校验装载）。
RULES_PATH = Path(__file__).with_name("rules")

_ACTION_KINDS = {
    "scan_install",
    "install_file",
    "run_tool",
    "regex_rewrite",
    "builtin_transform",
    "reject_route",
    "escalate_llm",
}
_PHASES = {"gate", "precheck", "loop"}
_MODES = {"native", "same", "degrade", "unsupported", "skip"}
#: 可选声明字段 ``mechanisms:`` 的 mech_id 形 (corpus 注册表值域
#: B/T/W 族; 注册表成员核验在 bench/py/report/mech_ids.py --validate)。
_MECH_ID_RX = re.compile(r"^[BTW]\d+$")
#: ``action`` 段合法键——``_apply`` 只读 kind/function/params, 其他键
#: 是死配置 (``param:`` 类 typo 与 ``categry:`` 同型 fail-open 面)。
_ACTION_KEYS = frozenset({"kind", "function", "params"})
#: 各 action.kind 的 ``params`` 合法键——``actions`` 叶实读名 ∪ 出厂
#: 注解键 (verify/batch/once_per_payload/hint/context 不消费但收)。
#: ``builtin_transform`` 缺席有意：词表随 TRANSFORM_FNS 逐函数定义，
#: 各 ``builtins/`` 叶自持，此处不做总表白名单 (造约束)。
_ACTION_PARAM_KEYS: dict[str, frozenset[str]] = {
    "scan_install": frozenset(
        {"scan_patterns", "noise_filter", "vendored", "dir", "batch", "verify"}
    ),
    "install_file": frozenset(
        {
            "file",
            "try_exts",
            "font_related",
            "font_related_exts",
            "file_aliases",
            "already_present_ok",
            "verify",
        }
    ),
    "run_tool": frozenset({"argv", "timeout", "once_per_payload"}),
    "regex_rewrite": frozenset({"rewrites", "exts", "engine_flags"}),
    "reject_route": frozenset({"route", "reason"}),
    "escalate_llm": frozenset({"hint", "context"}),
}
#: ``scan_patterns[]`` 条目合法键——``_scan_names``/``_apply_scan_install``
#: 实读面。
_SCAN_PATTERN_KEYS = frozenset({"regex", "split", "suffix"})
#: ``rewrites[]`` 条目合法键——``_compile_rewrites`` 实读面。
_REWRITE_KEYS = frozenset({"pattern", "repl", "function", "flags", "match_surface"})
#: ``condition`` 取 str 值的键——``_cond_ok`` 分派里 ``str(v)``/``in``/
#: ``re.escape`` 均以 str 为前提 (非 str 静默变形或炸)。
_COND_STR_KEYS = frozenset(
    {
        "tool_available",
        "cap_available",
        "main_head_contains",
        "cache_dir_glob",
        "prim_read_form",
    }
)
#: _COND_STR_KEYS 外取值当正则用的 condition 键 (``regex.search``)——
#: 装载期先编译。
_COND_REGEX_KEYS = frozenset({"source_contains", "ctx_suggests", "payload_pattern"})
#: ``condition.fileset`` 子键——与 ``_cond_ok`` fileset 分派同源。
_FILESET_KEYS = frozenset({"has_ext", "lacks_ext", "sibling_exts"})
#: ``engines.<name>`` 合法引擎名——``ctx.deps.engine_name`` 值域 =
#: 静态路由二引擎 (cli/run.py 同源); 未知名是永不命中的死 spec。
_ENGINE_NAMES = frozenset({"xelatex", "tectonic"})
#: ``engines.<name>`` spec 合法键——mode/degrade/fallback 由
#: ``_match_apply``/``_gate_eval``/``_precheck_phase`` 实读，via/note
#: 是文档性注解。
_ENGINE_SPEC_KEYS = frozenset({"mode", "degrade", "fallback", "via", "note"})
#: ``engines.<name>.degrade`` 合法值——``skip`` 由 ``_match_apply``/``engine``
#: 实读; ``ctan_fetch``/``ctan_fetch_font``/``partial`` 是降级通路文档值。
#: typo 值 (``skpi``) 静默退不脱即 fail-open, 装载期拦。
_DEGRADE_VALUES = frozenset({"skip", "ctan_fetch", "ctan_fetch_font", "partial"})
#: ``engines.<name>.fallback`` 合法值——``escalate_llm``/``advisory`` 由
#: ``_match_apply`` 实读; ``ctan_fetch`` 是降级臂的引擎侧兜底文档值
#: (30-route static_precheck 出厂用例)。
_FALLBACK_VALUES = frozenset({"escalate_llm", "advisory", "ctan_fetch"})
#: taxonomy 条目 ``scope`` 合法值——缺席默认 ``head`` (``Taxonomy.__init__``
#: ``e.get("scope", "head")`` 同口径); 未收名是静默死条目 (不进任一评估表)。
_TAXONOMY_SCOPES = frozenset({"head", "tail", "warnings"})
#: 引擎内建类别——``Taxonomy.classify``/``_round_cat`` 不经 taxonomy 段
#: 直出的终态类 (timed_out/killed_signal/驱动 fatal/兜底)。
_BUILTIN_CATS = frozenset(
    {"timeout", "runaway_output", "driver_fatal", "killed", "other", "clean"}
)
#: ``when:`` 段合法键 (顶层) / ``any:`` 子项键 —— 键名 typo (``categry:``)
#: 旧行为是对全 category 点火 (fail-open), 白名单 load 期拦 + _when_ok
#: 对无可识别键的候选 fail-closed, 与 _cond_ok 未知键语义对称。
_WHEN_KEYS = frozenset(
    {"always", "any", "category", "payload_required", "main_head_contains"}
)
_WHEN_ITEM_KEYS = frozenset({"category", "payload_required", "main_head_contains"})
#: rewrite 条目 ``match_surface`` 合法值——``masked`` = ``mask_tex`` 等长
#: 遮盖面匹配 (注释/逐字/失活区不命中)。typo 值若静默退 raw 属 fail-open
#: (与 ``categry:`` 同类), 装载期拦。
_MATCH_SURFACES = frozenset({"masked"})
#: ``condition:`` 段合法键 —— 与 _cond_ok 分派表一一对应。
_COND_KEYS = frozenset(
    {
        "any",
        "tool_available",
        "cap_available",
        "engine_in",
        "err_outside_fileset",
        "main_head_contains",
        "source_contains",
        "ctx_suggests",
        "fileset",
        "cache_dir_glob",
        "vendored_shadow",
        "package_version_ge",
        "prim_read_form",
        "payload_pattern",
        "shim_known",
    }
)
