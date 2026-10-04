"""dossier — per-id 跨阶段案卷：标记→证据→历史→规则链 一键出卷（index 版）。

``bench dossier ID [--run RUN] [--diff RUN] [--all-runs] [--json] [-o OUT]``

数据源映射（旧 report/dossier.py → index）:
  results/*/records/{stage}.jsonl → records 表 ``WHERE idc IN (变体)`` 全量
    append 史（(run_seq, seq) 序——波次可辨）;
  cases.jsonl                    → cases 表 payload 列;
  tickets*.jsonl                 → RUNDIR/derived/tickets*.jsonl（triage 动
    词产物，缺席容忍——动词单向依赖，不在线重算）;
  work/{safe_id}/                → RUNDIR/work/{safe_id(idc)}/，被 prune 收
    档时降级 vault.query(idc) 列副本（「现场已收档」语义）;
  run_meta.json                  → runs 表行 + RUNDIR/invocations.jsonl
    （flags 是整 run 级 spec params——无 per-stage argv）;
  RESULTS glob                   → runs 表 run_seq 序。

id 归一经 ``idnorm.canon_id`` 单源：canon 不可解（invalid/ambig）直接报错
exit 2——不猜；查无此人（canon ok 但无账）另行报 exit 2。
VENDORED_INV 面按 dossier 决议丢弃（老物随 results/ 死，新 run 无 vendored
概念）。只读：不改任何 index/vault。

拆分：实现体按子域下沉同包私有叶 —— ``dossier.env`` (常量面/texlate
taxonomy 桥/triage 桥/ruleset 懒装/venv 重入/registry 装载)、
``dossier.fetch`` (run 账组解析/records+cases index 投影/阶段分组/末条
胜/tickets+invocations 读取)、``dossier.work`` (work/{safe}/ 现场盘点/
texmf 落装/日志 + 文本 taxonomy 归类)、``dossier.sections`` (案卷节
identity/signature/evidence/history/rules/gap_flags + 共助)、
``dossier.attrib`` (跨 run 出现史/断点归因/醒目行/end-state+diff)、
``dossier.render`` (build_dossier 组卷 + render_md 出文)、
``dossier._main`` (add_args + main 编排——叶干取 ``_`` 前缀脱导出名
碰撞，否则叶件 import 把子模块绑上门面遮蔽同名惰性属性)。本文件是
PEP 562 惰性门面
(同 ``kernel.kernel``/``kernel.cli`` 门面形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``dossier.main``/``dossier.work_inventory``/``dossier._fetch_records``
等公私名面不变 (test_verbs/test_dossier_selftest 钉的私有名面全保)。
``verbs.REGISTRY`` 装载契约 (``main``/``add_args``) 经惰性解析不变。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from verbs.dossier._main import (
        _open_index,
        _rundir,
        _stem_of,
        add_args,
        main,
        paths,
        vault,
    )
    from verbs.dossier.attrib import (
        _attribution,
        _cross_run,
        _diff,
        _end_state,
        _rundir_for_name,
        _salient,
    )
    from verbs.dossier.env import (
        _EXCERPT_HEAD,
        _FAIL_WORDS,
        _RULESET,
        _STAGE_SUFFIXES,
        _SUBCLASS_SIGS,
        _TAX_OK,
        _WONTFIX_CATS,
        BENCH,
        CORPUS,
        REPO,
        STAGES,
        Path,
        _load_registry,
        _maybe_reexec_venv,
        _ruleset,
        _triage_fn,
        _triage_mod,
        contextlib,
        idnorm,
        load_ruleset,
        os,
        parse_log,
        parse_text,
    )
    from verbs.dossier.fetch import (
        _all_runs,
        _fetch_cases,
        _fetch_records,
        _group_stages,
        _invocations,
        _iter_jsonl,
        _latest,
        _rec_cols,
        _rec_key,
        _resolve_run_group,
        _row_to_rec,
        _seed_match,
        _stem_group,
        json,
        load_tickets,
    )
    from verbs.dossier.render import build_dossier, render_md
    from verbs.dossier.sections import (
        _candidate_rules,
        _err0,
        _evidence,
        _fix_class_hint,
        _gap_flags,
        _history,
        _identity,
        _is_fail,
        _latest_of,
        _manifest_row,
        _primary_compile,
        _rules_section,
        _signature,
    )
    from verbs.dossier.work import (
        _classify_log,
        _classify_text,
        _rec_taxo,
        _texmf_installed,
        _tree_stats,
        _xlat_chunk_stats,
        work_inventory,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "env": (
        "BENCH",
        "CORPUS",
        "REPO",
        "STAGES",
        "_EXCERPT_HEAD",
        "_FAIL_WORDS",
        "_RULESET",
        "_STAGE_SUFFIXES",
        "_SUBCLASS_SIGS",
        "_TAX_OK",
        "_WONTFIX_CATS",
        "_load_registry",
        "_maybe_reexec_venv",
        "_ruleset",
        "_triage_fn",
        "_triage_mod",
        "contextlib",
        "idnorm",
        "load_ruleset",
        "os",
        "parse_log",
        "parse_text",
        "Path",
    ),
    "fetch": (
        "_fetch_cases",
        "_fetch_records",
        "_group_stages",
        "_invocations",
        "_latest",
        "_rec_key",
        "_resolve_run_group",
        "_row_to_rec",
        "_all_runs",
        "_iter_jsonl",
        "_rec_cols",
        "_seed_match",
        "_stem_group",
        "json",
        "load_tickets",
    ),
    "work": (
        "_classify_log",
        "_classify_text",
        "_rec_taxo",
        "_texmf_installed",
        "_tree_stats",
        "_xlat_chunk_stats",
        "work_inventory",
    ),
    "sections": (
        "_candidate_rules",
        "_err0",
        "_evidence",
        "_fix_class_hint",
        "_gap_flags",
        "_history",
        "_identity",
        "_is_fail",
        "_latest_of",
        "_manifest_row",
        "_primary_compile",
        "_rules_section",
        "_signature",
    ),
    "attrib": (
        "_attribution",
        "_cross_run",
        "_diff",
        "_end_state",
        "_rundir_for_name",
        "_salient",
    ),
    "render": (
        "build_dossier",
        "render_md",
    ),
    "_main": (
        "_open_index",
        "_rundir",
        "_stem_of",
        "add_args",
        "main",
        "paths",
        "vault",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集 +
# 门面自持名 (``sys``/``annotations``)。新增导出两侧同步
# (``_export_drift`` 是三表同步闸)。
__all__ = [
    "BENCH",
    "CORPUS",
    "REPO",
    "STAGES",
    "_EXCERPT_HEAD",
    "_FAIL_WORDS",
    "_RULESET",
    "_STAGE_SUFFIXES",
    "_SUBCLASS_SIGS",
    "_TAX_OK",
    "_WONTFIX_CATS",
    "Path",
    "_all_runs",
    "_attribution",
    "_candidate_rules",
    "_classify_log",
    "_classify_text",
    "_cross_run",
    "_diff",
    "_end_state",
    "_err0",
    "_evidence",
    "_fetch_cases",
    "_fetch_records",
    "_fix_class_hint",
    "_gap_flags",
    "_group_stages",
    "_history",
    "_identity",
    "_invocations",
    "_is_fail",
    "_iter_jsonl",
    "_latest",
    "_latest_of",
    "_load_registry",
    "_manifest_row",
    "_maybe_reexec_venv",
    "_open_index",
    "_primary_compile",
    "_rec_cols",
    "_rec_key",
    "_rec_taxo",
    "_resolve_run_group",
    "_row_to_rec",
    "_rules_section",
    "_ruleset",
    "_rundir",
    "_rundir_for_name",
    "_salient",
    "_seed_match",
    "_signature",
    "_stem_group",
    "_stem_of",
    "_texmf_installed",
    "_tree_stats",
    "_triage_fn",
    "_triage_mod",
    "_xlat_chunk_stats",
    "add_args",
    "annotations",
    "build_dossier",
    "contextlib",
    "idnorm",
    "json",
    "load_ruleset",
    "load_tickets",
    "main",
    "os",
    "parse_log",
    "parse_text",
    "paths",
    "render_md",
    "sys",
    "vault",
    "work_inventory",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(
            importlib.import_module(f"{__package__ or 'verbs.dossier'}.{leaf}"), name
        )
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
