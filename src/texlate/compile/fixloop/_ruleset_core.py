"""ruleset._ruleset_core — Rule/Ruleset 校验装载 + phase 查询 (C5 拆叶)。

``Rule`` dataclass + ``Ruleset`` (tolerant/严格双模装载，phase 索引)
+ ``load_ruleset`` 函数式入口 + ``_RULESET_CACHE`` 分片指纹缓存 +
``RulesetError``。装载链：``load_yaml`` → ``_expand_family_tokens``
→ 文件级 + 规则级校验 (``_ruleset_validate`` 全簇) → phase 分桶。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.compile._yamlish import load_yaml
from texlate.compile.fixloop import builtins
from texlate.compile.fixloop._ruleset_family import _expand_family_tokens
from texlate.compile.fixloop._ruleset_validate import (
    _action_params_problems,
    _cond_problems,
    _dup_id_problems,
    _producible_categories,
    _taxonomy_problems,
    _warnings_problems,
    _when_problems,
)
from texlate.compile.fixloop._ruleset_vocab import (
    _ACTION_KEYS,
    _ACTION_KINDS,
    _DEGRADE_VALUES,
    _ENGINE_NAMES,
    _ENGINE_SPEC_KEYS,
    _FALLBACK_VALUES,
    _MECH_ID_RX,
    _MODES,
    _PHASES,
    RULES_PATH,
)
from texlate.compile.logparse import Taxonomy

if TYPE_CHECKING:
    from pathlib import Path


class RulesetError(ValueError):
    """``rules/`` 规则库结构校验失败。"""


@dataclass(slots=True)
class Rule:
    """单条规则 (rules/ ``rules:`` 列表元素的校验视图)。"""

    raw: dict[str, Any]

    @property
    def id(self) -> str:
        """规则 id。"""
        return self.raw["id"]

    @property
    def phase(self) -> str:
        """Gate | precheck | loop."""
        return self.raw["phase"]

    @property
    def order(self) -> float:
        """同 phase 内升序键 (缺省 0; 允许 11.5 类插位小数)。"""
        return float(self.raw.get("order", 0))

    @property
    def mechanisms(self) -> list[str]:
        """声明式机制标签 (corpus mech_id 表; 缺省 [])。"""
        return list(self.raw.get("mechanisms") or [])

    @property
    def when(self) -> dict[str, Any]:
        """触发条件 (category/payload_required/main_head_contains/any/always)。"""
        return self.raw.get("when") or {}

    @property
    def condition(self) -> dict[str, Any]:
        """执行前置条件原语 dict (全键 AND)。"""
        return self.raw.get("condition") or {}

    @property
    def action(self) -> dict[str, Any]:
        """``{kind, function?, params?}`` 动作描述。"""
        return self.raw.get("action") or {}

    @property
    def engines(self) -> dict[str, Any]:
        """``engines.<name>`` 执行规格表 (mode/degrade/fallback)。"""
        return self.raw.get("engines") or {}

    @property
    def status(self) -> str:
        """stats.status, 缺省 active。"""
        return str((self.raw.get("stats") or {}).get("status", "active"))

    def engine_spec(self, engine_name: str) -> dict[str, Any]:
        """该引擎下的执行规格; 未声明的引擎按 native 处理。"""
        return self.engines.get(engine_name) or {"mode": "native"}


#: ``Ruleset.load`` 进程内缓存 —— ``{str(path): (分片指纹，展开后纯数据)}``。
#: 指纹 = load_yaml 选片口径下每件分片的 ``(name, mtime_ns, size)`` 元组，
#: 任一分片增删改即漂移重载 (B14 fix#8: 每格 ~300ms yaml 装载 → ~3ms
#: deepcopy)。缓存的是展开后 *数据* 而非 Ruleset, 返回一律 deepcopy:
#: ``repair.ruleset_with_baseline`` 会原地改写 ``rule.raw`` 注 baseline_dir,
#: 共享对象会把 per-task 态漏回缓存。
_RULESET_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], dict[str, Any]]] = {}
_RULESET_CACHE_MAX = 16


def _ruleset_fingerprint(p: Path) -> tuple[tuple[str, int, int], ...] | None:
    """``load_yaml`` 实际会读到的分片集快照; ``None`` = 不确定，别缓存。

    选片口径与 ``load_yaml`` 严格对齐 (目录：排序 *.yaml/*.yml 普通文件;
    否则自身单文件)。stat/iterdir OSError、目录无分片 (load_yaml 会抛错)
    都返回 ``None`` —— 错误态走原路径照常抛，不进缓存。
    """
    try:
        if p.is_dir():
            shards = sorted(
                f for f in p.iterdir() if f.is_file() and f.suffix in {".yaml", ".yml"}
            )
            if not shards:
                return None
        else:
            shards = [p]
        return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in shards)
    except OSError:
        return None


class Ruleset:
    """``rules/`` 规则库装载结果：meta + taxonomy + rules + filemap/capabilities。"""

    def __init__(
        self, data: dict[str, Any], path: Path | None = None, *, tolerant: bool = False
    ) -> None:
        """校验 data → 切 meta/taxonomy/rules 三段 + phase 索引。

        ``tolerant=True``：rule 级问题（缺字段/非法 phase/未知 builtin 等）
        只弃肇事规则并记 ``skipped_rules``——yaml 与代码版本错位（server
        跑旧 .py 读新 rules/）时一条坏规则不再击穿整条修复臂；file 级
        问题（version/顶层结构/dup id）照旧 raise。严格模式（默认）行为
        不变，仍是写规则的验证面。
        """
        self.path = path
        self.skipped_rules: list[str] = []
        if tolerant:
            file_probs = self._file_problems(data)
            if file_probs:
                where = str(self.path) if self.path is not None else "rules/"
                raise RulesetError(
                    f"规则库 {where} 校验失败:\n" + "\n".join(file_probs)
                )
            keep: list[dict[str, Any]] = []
            cats = _producible_categories(data)
            rules = data.get("rules")
            for i, r in enumerate(rules if isinstance(rules, list) else []):
                tag = r.get("id", f"#{i}") if isinstance(r, dict) else f"#{i}"
                probs = self._rule_problems(r, tag, cats)
                if probs:
                    self.skipped_rules.extend(probs)
                else:
                    keep.append(r)
            data = {**data, "rules": keep}
        else:
            problems = self._validate(data)
            if problems:
                where = str(self.path) if self.path is not None else "rules/"
                raise RulesetError(f"规则库 {where} 校验失败:\n" + "\n".join(problems))
        self.raw = data
        self.meta: dict[str, Any] = data.get("meta") or {}
        self.loop_cfg: dict[str, Any] = self.meta.get("loop") or {}
        self.filemap_cfg: dict[str, Any] = data.get("filemap") or {}
        self.capabilities: dict[str, Any] = data.get("capabilities") or {}
        self.warn_patterns: list[dict[str, Any]] = data.get("warnings") or []
        tax_entries = data.get("taxonomy") or []
        if not self.loop_cfg.get("warn_driven_fixes", True):
            tax_entries = [e for e in tax_entries if e.get("scope") != "warnings"]
        self.taxonomy = Taxonomy(tax_entries)
        self.rules = [Rule(r) for r in data.get("rules") or []]
        self._by_phase: dict[str, list[Rule]] = {
            p: sorted((r for r in self.rules if r.phase == p), key=lambda r: r.order)
            for p in _PHASES
        }

    @staticmethod
    def _file_problems(data: dict[str, Any]) -> list[str]:  # noqa: C901, PLR0912  # 顶层段形逐段即分支
        """文件级校验项（version/顶层段形/meta.loop/段条目/dup id）——tolerant 也照常 raise。

        顶层段异形原逃逸为裸异常 (``rules: 5`` 崩 ``_dup_id_problems``
        自身、``meta: [1]`` 崩 ``__init__``、taxonomy/warnings 异形条目
        崩 ``Taxonomy.__init__``/逐次 ``re.search``)——段形先拦再进
        条目级校验，``data.get(...) or {}`` 的 falsy 容错口径保持
        (``None`` 视作缺席不拦)。
        """
        if not isinstance(data, dict):
            return ["顶层必须是 map"]
        probs: list[str] = []
        if data.get("version") != 1:
            probs.append(f"version 应为 1, 得 {data.get('version')!r}")
        for k in ("rules", "taxonomy", "warnings"):
            v = data.get(k)
            if v is not None and not isinstance(v, list):
                probs.append(f"{k} 必须是 list")
        for k in ("meta", "filemap", "capabilities"):
            v = data.get(k)
            if v is not None and not isinstance(v, dict):
                probs.append(f"{k} 必须是 map")
        meta = data.get("meta")
        loop = meta.get("loop") if isinstance(meta, dict) else None
        if loop is not None and not isinstance(loop, dict):
            probs.append("meta.loop 必须是 map")
        elif isinstance(loop, dict):
            # engine._FixRun 的 int()/float() 实读键——不可转即
            # 运行时 ValueError, 装载期拦。
            for k in (
                "max_rounds",
                "clean_err_max",
                "compile_passes",
                "stuck_sig_repeat",
            ):
                if k in loop:
                    try:
                        int(loop[k])
                    except (TypeError, ValueError):
                        probs.append(f"meta.loop.{k} 必须可转 int")
            if "timeout_sec" in loop:
                try:
                    float(loop["timeout_sec"])
                except (TypeError, ValueError):
                    probs.append("meta.loop.timeout_sec 必须可转 float")
        tax = data.get("taxonomy")
        if isinstance(tax, list):
            probs.extend(_taxonomy_problems(tax))
        warn = data.get("warnings")
        if isinstance(warn, list):
            probs.extend(_warnings_problems(warn))
        rules = data.get("rules")
        if isinstance(rules, list):
            probs.extend(_dup_id_problems(rules))
        return probs

    @staticmethod
    def _rule_problems(  # noqa: C901, PLR0912, PLR0915  # 校验项逐条即分支
        r: Any,  # noqa: ANN401  # yaml 值天然 Any
        tag: str,
        cats: frozenset[str] | None = None,
    ) -> list[str]:
        """单条规则的校验项——tolerant 模式下命中即整条弃用。

        spec 子语言 schema: ``when``/``condition``/``action``(含 params)/
        ``engines`` 各段的键白名单 + 值形 + 互需字段，全与
        actions/engine 叶实读面对齐 (详各 helper 注)。非 map 段先拦
        再按 ``{}`` 续扫——``.get``/``.items`` 旧崩面 (AttributeError/
        TypeError 穿透装载) 不再发生。
        """
        probs: list[str] = []
        if not isinstance(r, dict):
            return [f"rule {tag}: 必须是 map"]
        probs.extend(
            f"rule {tag}: 缺字段 {k}"
            for k in ("id", "phase", "when", "action")
            if k not in r
        )
        if "id" in r and not isinstance(r["id"], str):
            probs.append(f"rule {tag}: id 必须是 str")
        phase = r.get("phase")
        if not isinstance(phase, str) or phase not in _PHASES:
            probs.append(f"rule {tag}: phase 非法 {phase!r}")
        if "order" in r:
            try:
                float(r["order"])
            except (TypeError, ValueError):
                probs.append(f"rule {tag}: order 必须可转 float")
        probs.extend(_when_problems(r.get("when"), tag, cats))
        probs.extend(_cond_problems(r.get("condition"), tag))
        action = r.get("action")
        if action is not None and not isinstance(action, dict):
            probs.append(f"rule {tag}: action 必须是 map")
        action = action if isinstance(action, dict) else {}
        probs.extend(
            f"rule {tag}: action 未知键 {k!r}" for k in action if k not in _ACTION_KEYS
        )
        kind = action.get("kind")
        if not isinstance(kind, str) or kind not in _ACTION_KINDS:
            probs.append(f"rule {tag}: action.kind 非法 {kind!r}")
        fn = action.get("function")
        if kind == "builtin_transform" and (
            not isinstance(fn, str) or fn not in builtins.TRANSFORM_FNS
        ):
            probs.append(f"rule {tag}: 未知 builtin_transform {fn!r}")
        if fn is not None and kind != "builtin_transform":
            probs.append(f"rule {tag}: function 仅 builtin_transform 消费")
        params = action.get("params")
        if params is not None and not isinstance(params, dict):
            probs.append(f"rule {tag}: params 必须是 map")
            params = None
        probs.extend(
            _action_params_problems(
                kind, params if isinstance(params, dict) else {}, tag
            )
        )
        mechs = r.get("mechanisms")
        if mechs is not None and not (
            isinstance(mechs, list)
            and all(isinstance(m, str) and _MECH_ID_RX.match(m) for m in mechs)
        ):
            probs.append(f"rule {tag}: mechanisms 必须是 [BTW]\\d+ 形标签列表")
        engines = r.get("engines")
        if engines is not None and not isinstance(engines, dict):
            probs.append(f"rule {tag}: engines 必须是 map")
            engines = None
        for eng_name, spec in (engines if isinstance(engines, dict) else {}).items():
            if eng_name not in _ENGINE_NAMES:
                probs.append(f"rule {tag}: engines.{eng_name} 未知引擎")
            if not isinstance(spec, dict):
                probs.append(f"rule {tag}: engines.{eng_name} 必须是 map")
                continue
            probs.extend(
                f"rule {tag}: engines.{eng_name} 未知键 {k!r}"
                for k in spec
                if k not in _ENGINE_SPEC_KEYS
            )
            mode = spec.get("mode")
            if not isinstance(mode, str) or mode not in _MODES:
                probs.append(f"rule {tag}: engines.{eng_name}.mode 非法 {mode!r}")
            # degrade/fallback 值域白名单——typo 值静默失效属 fail-open
            # (``skpi`` 不脱 skip、``advisroy`` 不灭 advisory 记账)。
            for dk, vocab in (
                ("degrade", _DEGRADE_VALUES),
                ("fallback", _FALLBACK_VALUES),
            ):
                dv = spec.get(dk)
                if dv is not None and (not isinstance(dv, str) or dv not in vocab):
                    probs.append(f"rule {tag}: engines.{eng_name}.{dk} 非法 {dv!r}")
            if "degrade" in spec and mode != "degrade":
                probs.append(
                    f"rule {tag}: engines.{eng_name}.degrade 挂在 "
                    f"mode={mode!r} 下 (死键——仅 mode: degrade 消费)"
                )
        return probs

    @staticmethod
    def _validate(data: dict[str, Any]) -> list[str]:  # 校验项逐条即分支
        probs = Ruleset._file_problems(data)
        if not isinstance(data, dict):
            return probs
        cats = _producible_categories(data)
        rules = data.get("rules")
        for i, r in enumerate(rules if isinstance(rules, list) else []):
            tag = r.get("id", f"#{i}") if isinstance(r, dict) else f"#{i}"
            probs.extend(Ruleset._rule_problems(r, tag, cats))
        return probs

    @classmethod
    def load(cls, path: Path | None = None, *, tolerant: bool = False) -> Ruleset:
        """装载规则库 (默认本包附带 ``rules/`` 目录; 也接受单文件路径)。

        进程内按 ``(路径，分片指纹)`` 缓存展开后纯数据，命中 deepcopy 返回
        (见 ``_RULESET_CACHE`` 注 —— 调用方原地改写不外溢); 指纹漂移
        (分片增/删/改) 或不可 stat 时重走全量装载。
        ``tolerant=True`` 是运行时面 (fixloop/precheck 两臂): rule 级
        校验失败只弃该条记 ``skipped_rules``, 不击穿整条修复臂。
        """
        p = path or RULES_PATH
        fp = _ruleset_fingerprint(p)
        if fp is None:
            return cls(_expand_family_tokens(load_yaml(p)), path=p, tolerant=tolerant)
        key = str(p)
        hit = _RULESET_CACHE.get(key)
        if hit is None or hit[0] != fp:
            if len(_RULESET_CACHE) >= _RULESET_CACHE_MAX:
                _RULESET_CACHE.clear()
            hit = (fp, _expand_family_tokens(load_yaml(p)))
            _RULESET_CACHE[key] = hit
        return cls(copy.deepcopy(hit[1]), path=p, tolerant=tolerant)

    def phase(self, name: str) -> list[Rule]:
        """某 phase 的规则按 order 升序。"""
        return self._by_phase.get(name, [])

    def max_rounds(self) -> int:
        """``meta.loop.max_rounds`` (缺省 8)。"""
        return int(self.loop_cfg.get("max_rounds", 8))


def load_ruleset(path: Path | None = None, *, tolerant: bool = False) -> Ruleset:
    """``Ruleset.load`` 的函数式入口。"""
    return Ruleset.load(path, tolerant=tolerant)
