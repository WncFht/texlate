"""ruleset —— rules/ 规则库的校验装载 + phase 查询 (C2 自 engine.py 拆出).

``Rule``/``Ruleset``/``load_ruleset``/``RULES_PATH``/``RulesetError`` +
装载期校验助手 (``_when_problems``/``_cond_problems``/``_dup_id_problems``)
+ when/condition/action 词表常量簇 + ``_FAMILY_TOKENS`` 展开 +
``_RULESET_CACHE`` 分片指纹缓存。不依赖 engine——动作解释器在
``actions.py``, 主循环在 ``engine.py`` (两侧均门面回引本叶公共名)。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop._yamlish import load_yaml
from texlate.compile.fixloop.logparse import Taxonomy

#: 规则库根: 2026-09-17 起为 ``rules/`` 目录（_yamlish.load_yaml 目录感知
#: 合并多分片; 序敏感段 taxonomy/warnings 各自单文件承载）。``Ruleset.load``
#: 传显式单文件路径仍兼容（部分规则集亦可单独校验装载）。
RULES_PATH = Path(__file__).with_name("rules")

#: yaml 模式串占位符 → builtins 原语族 (扩表免手同步: 1e0e5c8 手工
#: 13→75 交替即此债)。``@pdftex_prims`` 在任何字符串值里出现即展开成
#: ``(?:…)`` 非捕获交替——按长度降序排, 防短名前缀截长名。
_FAMILY_TOKENS: dict[str, frozenset[str]] = {
    "@pdftex_prims": builtins.PDFTEX_PRIMS,
}


def _expand_family_tokens(node: Any) -> Any:  # noqa: ANN401  # yaml 树天然 Any
    """递归展开 ``_FAMILY_TOKENS`` 占位符 → 正则交替片段 (yaml 全树)。"""
    if isinstance(node, str):
        for tok, fam in _FAMILY_TOKENS.items():
            if tok in node:
                alts = "|".join(sorted(fam, key=lambda s: (-len(s), s)))
                node = node.replace(tok, f"(?:{alts})")
        return node
    if isinstance(node, list):
        return [_expand_family_tokens(x) for x in node]
    if isinstance(node, dict):
        return {k: _expand_family_tokens(v) for k, v in node.items()}
    return node


class RulesetError(ValueError):
    """``rules/`` 规则库结构校验失败。"""


def _when_problems(when: Any, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``when`` 段键名白名单校验 (typo 键在旧 _when_ok 下是 fail-open 面)。"""
    if when is None:
        return []
    if not isinstance(when, dict):
        return [f"rule {tag}: when 必须是 map"]
    probs = [f"rule {tag}: when 未知键 {k!r}" for k in when if k not in _WHEN_KEYS]
    anys = when.get("any")
    if anys is not None:
        if not isinstance(anys, list):
            probs.append(f"rule {tag}: when.any 必须是 list")
        else:
            for j, c in enumerate(anys):
                if not isinstance(c, dict):
                    probs.append(f"rule {tag}: when.any[{j}] 必须是 map")
                else:
                    probs.extend(
                        f"rule {tag}: when.any[{j}] 未知键 {k!r}"
                        for k in c
                        if k not in _WHEN_ITEM_KEYS
                    )
    return probs


def _cond_problems(cond: Any, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``condition`` 段键名白名单 (``any`` 子表递归); 与 _cond_ok 分派同源。"""
    if cond is None:
        return []
    if not isinstance(cond, dict):
        return [f"rule {tag}: condition 必须是 map"]
    probs = [f"rule {tag}: condition 未知键 {k!r}" for k in cond if k not in _COND_KEYS]
    for j, sub in enumerate(cond.get("any") or []):
        probs.extend(_cond_problems(sub, f"{tag}.any[{j}]"))
    return probs


def _dup_id_problems(rules: list[Any]) -> list[str]:  # yaml 值天然 Any
    """``rules:`` 段 id 唯一性校验 (合并表序位双出处)。

    rules/ 目录装载经 ``_yamlish._merge_into`` list 段 extend 不去重——两片
    同 ``id`` 曾静默拼成双规则 (``applied`` 键 ``{id}:{payload}`` 亦互相
    遮蔽)。``(phase, order)`` 撞位不拦: 同序位合法——出厂四条 loop 规则
    同挂 ``order: 9`` (rungen_stub/nonctan_input_stub/docstrip_generate/
    svg_prepare, 触发面互斥、稳定序按分片文件名序)。
    """
    probs: list[str] = []
    seen: dict[str, int] = {}  # id → 合并表首见序位
    for i, r in enumerate(rules):
        rid = r.get("id") if isinstance(r, dict) else None
        if not isinstance(rid, str):
            continue
        if rid in seen:
            probs.append(
                f"rule {rid}: id {rid!r} 重复定义 (rules[{seen[rid]}] 与 rules[{i}])"
            )
        else:
            seen[rid] = i
    return probs


# ════════════════════════════════════════════════════════════════
# Ruleset —— rules/ 规则库的校验装载 + phase 查询
# ════════════════════════════════════════════════════════════════

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
#: 可选声明字段 ``mechanisms:`` 的 mech_id 形 (corpus_v3 注册表值域
#: B/T/W 族; 注册表成员核验在 bench/py/mech_ids.py --validate)。
_MECH_ID_RX = re.compile(r"^[BTW]\d+$")
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
        "main_head_contains",
        "source_contains",
        "ctx_suggests",
        "fileset",
        "cache_dir_glob",
        "vendored_shadow",
        "package_version_ge",
        "prim_read_form",
        "shim_known",
    }
)


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
        """Gate | precheck | loop。"""
        return self.raw["phase"]

    @property
    def order(self) -> float:
        """同 phase 内升序键 (缺省 0; 允许 11.5 类插位小数)。"""
        return float(self.raw.get("order", 0))

    @property
    def mechanisms(self) -> list[str]:
        """声明式机制标签 (corpus_v3 mech_id 表; 缺省 [])。"""
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


#: ``Ruleset.load`` 进程内缓存 —— ``{str(path): (分片指纹, 展开后纯数据)}``。
#: 指纹 = load_yaml 选片口径下每件分片的 ``(name, mtime_ns, size)`` 元组,
#: 任一分片增删改即漂移重载 (B14 fix#8: 每格 ~300ms yaml 装载 → ~3ms
#: deepcopy)。缓存的是展开后 *数据* 而非 Ruleset, 返回一律 deepcopy:
#: ``repair.ruleset_with_baseline`` 会原地改写 ``rule.raw`` 注 baseline_dir,
#: 共享对象会把 per-task 态漏回缓存。
_RULESET_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], dict[str, Any]]] = {}
_RULESET_CACHE_MAX = 16


def _ruleset_fingerprint(p: Path) -> tuple[tuple[str, int, int], ...] | None:
    """``load_yaml`` 实际会读到的分片集快照; ``None`` = 不确定, 别缓存。

    选片口径与 ``load_yaml`` 严格对齐 (目录: 排序 *.yaml/*.yml 普通文件;
    否则自身单文件)。stat/iterdir OSError、目录无分片 (load_yaml 会抛错)
    都返回 ``None`` —— 错误态走原路径照常抛, 不进缓存。
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
    """``rules/`` 规则库装载结果: meta + taxonomy + rules + filemap/capabilities。"""

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        """校验 data → 切 meta/taxonomy/rules 三段 + phase 索引。"""
        self.path = path
        self.raw = data
        problems = self._validate(data)
        if problems:
            where = str(self.path) if self.path is not None else "rules/"
            raise RulesetError(f"规则库 {where} 校验失败:\n" + "\n".join(problems))
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
    def _validate(data: dict[str, Any]) -> list[str]:  # 校验项逐条即分支
        probs: list[str] = []
        if not isinstance(data, dict):
            return ["顶层必须是 map"]
        if data.get("version") != 1:
            probs.append(f"version 应为 1, 得 {data.get('version')!r}")
        probs.extend(_dup_id_problems(data.get("rules") or []))
        for i, r in enumerate(data.get("rules") or []):
            tag = r.get("id", f"#{i}")
            probs.extend(
                f"rule {tag}: 缺字段 {k}"
                for k in ("id", "phase", "when", "action")
                if k not in r
            )
            if r.get("phase") not in _PHASES:
                probs.append(f"rule {tag}: phase 非法 {r.get('phase')!r}")
            probs.extend(_when_problems(r.get("when"), tag))
            probs.extend(_cond_problems(r.get("condition"), tag))
            kind = (r.get("action") or {}).get("kind")
            if kind not in _ACTION_KINDS:
                probs.append(f"rule {tag}: action.kind 非法 {kind!r}")
            fn = (r.get("action") or {}).get("function")
            if kind == "builtin_transform" and fn not in builtins.TRANSFORM_FNS:
                probs.append(f"rule {tag}: 未知 builtin_transform {fn!r}")
            rewrites = ((r.get("action") or {}).get("params") or {}).get(
                "rewrites"
            ) or []
            probs.extend(
                f"rule {tag}: 未知 rewrite function {rw['function']!r}"
                for rw in rewrites
                if "function" in rw and rw["function"] not in builtins.REWRITE_FNS
            )
            probs.extend(
                f"rule {tag}: match_surface 非法 {rw['match_surface']!r}"
                for rw in rewrites
                if "match_surface" in rw and rw["match_surface"] not in _MATCH_SURFACES
            )
            mechs = r.get("mechanisms")
            if mechs is not None and not (
                isinstance(mechs, list)
                and all(isinstance(m, str) and _MECH_ID_RX.match(m) for m in mechs)
            ):
                probs.append(f"rule {tag}: mechanisms 必须是 [BTW]\\d+ 形标签列表")
            for eng_name, spec in (r.get("engines") or {}).items():
                mode = (spec or {}).get("mode")
                if mode not in _MODES:
                    probs.append(f"rule {tag}: engines.{eng_name}.mode 非法 {mode!r}")
        return probs

    @classmethod
    def load(cls, path: Path | None = None) -> Ruleset:
        """装载规则库 (默认本包附带 ``rules/`` 目录; 也接受单文件路径)。

        进程内按 ``(路径, 分片指纹)`` 缓存展开后纯数据, 命中 deepcopy 返回
        (见 ``_RULESET_CACHE`` 注 —— 调用方原地改写不外溢); 指纹漂移
        (分片增/删/改) 或不可 stat 时重走全量装载。
        """
        p = path or RULES_PATH
        fp = _ruleset_fingerprint(p)
        if fp is None:
            return cls(_expand_family_tokens(load_yaml(p)), path=p)
        key = str(p)
        hit = _RULESET_CACHE.get(key)
        if hit is None or hit[0] != fp:
            if len(_RULESET_CACHE) >= _RULESET_CACHE_MAX:
                _RULESET_CACHE.clear()
            hit = (fp, _expand_family_tokens(load_yaml(p)))
            _RULESET_CACHE[key] = hit
        return cls(copy.deepcopy(hit[1]), path=p)

    def phase(self, name: str) -> list[Rule]:
        """某 phase 的规则按 order 升序。"""
        return self._by_phase.get(name, [])

    def max_rounds(self) -> int:
        """``meta.loop.max_rounds`` (缺省 8)。"""
        return int(self.loop_cfg.get("max_rounds", 8))


def load_ruleset(path: Path | None = None) -> Ruleset:
    """``Ruleset.load`` 的函数式入口。"""
    return Ruleset.load(path)
