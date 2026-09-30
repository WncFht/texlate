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

import regex

from texlate.compile._yamlish import load_yaml
from texlate.compile.engine._route import PSTRICKS_SIG_ALTS
from texlate.compile.fixloop import builtins
from texlate.compile.logparse import Taxonomy

#: 规则库根: 2026-09-17 起为 ``rules/`` 目录（_yamlish.load_yaml 目录感知
#: 合并多分片; 序敏感段 taxonomy/warnings 各自单文件承载）。``Ruleset.load``
#: 传显式单文件路径仍兼容（部分规则集亦可单独校验装载）。
RULES_PATH = Path(__file__).with_name("rules")

#: yaml 模式串占位符 → 原语/签名族 (扩表免手同步: 1e0e5c8 手工
#: 13→75 交替即此债)。``@pdftex_prims``/``@pstricks`` 在任何字符串值里
#: 出现即展开成 ``(?:…)`` 非捕获交替——按长度降序排, 防短名前缀截长名。
#: ``@pstricks`` 单源在 compile/engine/_route.py ``PSTRICKS_SIG_ALTS``
#: (route 静态签名与规则条件同口径; 行锚 ``^[ \t]*`` 留在 yaml 侧外置,
#: token 不含锚, 嵌进遮盖视图/raw 源两用)。
_FAMILY_TOKENS: dict[str, frozenset[str] | tuple[str, ...]] = {
    "@pdftex_prims": builtins.PDFTEX_PRIMS,
    "@pstricks": PSTRICKS_SIG_ALTS,
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


def _str_list(v: Any) -> bool:  # noqa: ANN401  # yaml 值天然 Any
    """值形判据: ``list[str]`` (exts/engine_in/fileset 各键共用)。"""
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _rx_problems(pat: Any, label: str) -> list[str]:  # noqa: ANN401  # 同上
    """正则值校验: str 且 ``regex`` 可编译。

    ``_cond_ok``/``_compile_rewrites``/``_scan_names`` 的 compile/search
    都在 try 外——病 pattern 装载期拦, 不再穿透点火面炸整格。
    """
    if not isinstance(pat, str):
        return [f"{label} 必须是 str"]
    try:
        regex.compile(pat)
    except regex.error as e:
        return [f"{label} 正则不可编译: {e}"]
    return []


def _when_item_problems(
    item: dict[str, Any],
    label: str,
    tag: str,
    cats: frozenset[str] | None = None,
) -> list[str]:
    """单个 when 候选 (顶层 map 或 ``any[]`` 子项) 的值形校验。

    与 ``_when_ok`` 逐键消费形对齐: ``category`` 仅 str——评估侧
    ``c["category"] != cat`` 是标量比对, list 形永不等即静默
    fail-dead, OR 语义走 ``when.any`` 子项; ``payload_required``
    真值 (bool), ``main_head_contains`` ``in`` 子串 (str——非 str
    触发 TypeError, _when_ok 在 try 外, 装载期拦)。``cats`` 非空时
    校验 ``category`` 值域 (可产出类集合, ``_producible_categories``)
    ——域外值永不命中即死规则。
    """
    probs: list[str] = []
    if "category" in item:
        if not isinstance(item["category"], str):
            probs.append(f"rule {tag}: {label}.category 必须是 str")
        elif cats is not None and item["category"] not in cats:
            probs.append(
                f"rule {tag}: {label}.category 未知类别 {item['category']!r} "
                "(taxonomy id/subclassify.into/引擎内建类之外, 永不命中)"
            )
    if "payload_required" in item and not isinstance(item["payload_required"], bool):
        probs.append(f"rule {tag}: {label}.payload_required 必须是 bool")
    if "main_head_contains" in item and not isinstance(item["main_head_contains"], str):
        probs.append(f"rule {tag}: {label}.main_head_contains 必须是 str")
    return probs


def _when_problems(
    when: Any,  # noqa: ANN401  # yaml 值天然 Any
    tag: str,
    cats: frozenset[str] | None = None,
) -> list[str]:
    """``when`` 段校验: 键白名单 + 值形 (typo 键在旧 _when_ok 下是 fail-open 面)。

    ``cats`` = ``_producible_categories`` 结果; ``None`` 时跳过
    ``category`` 值域检查 (兼容不带 taxonomy 语境的直接调用)。
    """
    if when is None:
        return []
    if not isinstance(when, dict):
        return [f"rule {tag}: when 必须是 map"]
    probs = [f"rule {tag}: when 未知键 {k!r}" for k in when if k not in _WHEN_KEYS]
    if "always" in when and not isinstance(when["always"], bool):
        probs.append(f"rule {tag}: when.always 必须是 bool")
    # 顶层 map 自身即隐式候选 (``when.get("any") or [when]``)——同过值形。
    probs.extend(_when_item_problems(when, "when", tag, cats))
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
                    probs.extend(_when_item_problems(c, f"when.any[{j}]", tag, cats))
    return probs


def _cond_value_problems(key: str, val: Any, tag: str) -> list[str]:  # noqa: ANN401, C901, PLR0911, PLR0912  # yaml 值天然 Any; 与 _cond_ok 分派同形, 每键一处
    """``condition`` 单键值形校验——与 ``_cond_ok`` 分派表的消费形逐键对齐。

    旗标键 (vendored_shadow/err_outside_fileset/shim_known) 的值不被
    消费 (键在即启), 不检; ``any``/``fileset``/``package_version_ge``
    是结构性子形; ``engine_in`` 限 ``list[str]``——str 在 ``not in``
    下退成子串匹配 (footgun, ``xelatex in "xelatextex"`` 式误中)。
    """
    if key == "any":
        if not isinstance(val, list):
            return [f"rule {tag}: condition.any 必须是 list"]
        return []
    if key in _COND_REGEX_KEYS:
        return _rx_problems(val, f"rule {tag}: condition.{key}")
    if key in _COND_STR_KEYS:
        if not isinstance(val, str):
            return [f"rule {tag}: condition.{key} 必须是 str"]
        return []
    if key == "engine_in":
        if not _str_list(val):
            return [f"rule {tag}: condition.engine_in 必须是 list[str]"]
        # 值域白名单——``ctx.engine_name not in v`` 下未知名是恒假死条件
        # (与 engines.<name> 未知名同型死 spec)。
        return [
            f"rule {tag}: condition.engine_in 未知引擎 {e!r}"
            for e in val
            if e not in _ENGINE_NAMES
        ]
    if key == "fileset":
        if not isinstance(val, dict):
            return [f"rule {tag}: condition.fileset 必须是 map"]
        probs = [
            f"rule {tag}: condition.fileset 未知键 {k!r}"
            for k in val
            if k not in _FILESET_KEYS
        ]
        probs.extend(
            f"rule {tag}: condition.fileset.{k} 必须是 list[str]"
            for k, v in val.items()
            if k in _FILESET_KEYS and not _str_list(v)
        )
        # 三键消费侧全与 ``Path.suffix`` 比对 (``e in {p.suffix}``/
        # ``p.suffix.lower() in pool``)——suffix 恒带 ``.`` 前缀, 缺
        # 点的值是永不命中的死配置 (``has_ext: [ins]`` 型 typo)。
        probs.extend(
            f"rule {tag}: condition.fileset.{k} 扩展名须带 '.' 前缀: {e!r}"
            for k, v in val.items()
            if k in _FILESET_KEYS and isinstance(v, list)
            for e in v
            if isinstance(e, str) and not e.startswith(".")
        )
        return probs
    if key == "package_version_ge":
        if not isinstance(val, dict):
            return [f"rule {tag}: condition.package_version_ge 必须是 map"]
        probs = []
        if not isinstance(val.get("file"), str):
            probs.append(f"rule {tag}: condition.package_version_ge.file 必须是 str")
        try:
            int(val.get("version", 0))
        except (TypeError, ValueError):
            probs.append(
                f"rule {tag}: condition.package_version_ge.version 必须可转 int"
            )
        return probs
    return []


def _cond_problems(cond: Any, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``condition`` 段校验: 键白名单 + 逐键值形 (``any`` 子表递归); 与 _cond_ok 分派同源。"""
    if cond is None:
        return []
    if not isinstance(cond, dict):
        return [f"rule {tag}: condition 必须是 map"]
    probs = [f"rule {tag}: condition 未知键 {k!r}" for k in cond if k not in _COND_KEYS]
    for key, val in cond.items():
        probs.extend(_cond_value_problems(key, val, tag))
    anys = cond.get("any")
    if isinstance(anys, list):  # 非 list 已在上方略行拦; enumerate(5) 旧崩面
        for j, sub in enumerate(anys):
            probs.extend(_cond_problems(sub, f"{tag}.any[{j}]"))
    return probs


def _scan_pattern_problems(sp: Any, label: str, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``scan_patterns[]`` 单条校验——``_scan_names`` 实读 ``regex``(必)/split/suffix。"""
    if not isinstance(sp, dict):
        return [f"rule {tag}: {label} 必须是 map"]
    probs = [
        f"rule {tag}: {label} 未知键 {k!r}" for k in sp if k not in _SCAN_PATTERN_KEYS
    ]
    if "regex" not in sp:
        probs.append(f"rule {tag}: {label} 缺 regex")
    else:
        pat = sp["regex"]
        if not isinstance(pat, str):
            probs.append(f"rule {tag}: {label}.regex 必须是 str")
        else:
            try:
                rx = regex.compile(pat)
            except regex.error as e:
                probs.append(f"rule {tag}: {label}.regex 正则不可编译: {e}")
            else:
                # ``_scan_names`` 无条件 ``m.group(1)``——无捕获组的 pattern
                # 首命中即 IndexError (per-rule 兜底记 'rule crashed')。
                # 注: 可选组不参与时 ``m.group(1)=None`` → ``nm.strip()``
                # AttributeError 属同族崩面, 但非静态可查。
                if rx.groups < 1:
                    probs.append(
                        f"rule {tag}: {label}.regex 需含捕获组 "
                        "(_scan_names 无条件取 m.group(1))"
                    )
    probs.extend(
        f"rule {tag}: {label}.{k} 必须是 str"
        for k in ("split", "suffix")
        if k in sp and not isinstance(sp[k], str)
    )
    return probs


def _rewrite_flag_bit(fl: str) -> int | None:
    """Flag 名 → ``regex``/``re`` 属性位; 解析不出 = None。

    与 ``_compile_rewrites`` 同序 fallback——该处在找不到时静默按 0
    处理 (``MULTILINEE`` 类 typo 悄悄丢旗), 装载期拦成显式错误。
    """
    bit = getattr(regex, fl, getattr(re, fl, None))
    return bit if isinstance(bit, int) else None


def _rewrite_item_problems(rw: Any, j: int, tag: str) -> list[str]:  # noqa: ANN401, C901, PLR0912  # yaml 值天然 Any; 校验项逐条即分支
    """``rewrites[]`` 单条校验——``_compile_rewrites`` 实读面。

    ``pattern`` 无条件下标取 (rw["pattern"]) → 必填 str 且按解析后
    flags 可编译; ``function`` 在 REWRITE_FNS 注册 (与 ``repl`` 互斥,
    并存时 function 胜出、repl 是死配置); ``repl`` 喂 ``m.expand``
    须 str; ``flags`` 逐名可解析。
    """
    label = f"params.rewrites[{j}]"
    if not isinstance(rw, dict):
        return [f"rule {tag}: {label} 必须是 map"]
    probs = [f"rule {tag}: {label} 未知键 {k!r}" for k in rw if k not in _REWRITE_KEYS]
    flags = 0
    flv = rw.get("flags")
    if flv is not None:
        if not _str_list(flv):
            probs.append(f"rule {tag}: {label}.flags 必须是 list[str]")
        else:
            for fl in flv:
                bit = _rewrite_flag_bit(fl)
                if bit is None:
                    probs.append(f"rule {tag}: {label}.flags 未知旗 {fl!r}")
                else:
                    flags |= bit
    pat = rw.get("pattern")
    if not isinstance(pat, str):
        probs.append(f"rule {tag}: {label}.pattern 缺或必须是 str")
    else:
        try:
            regex.compile(pat, flags)
        except regex.error as e:
            probs.append(f"rule {tag}: {label}.pattern 正则不可编译: {e}")
    fn = rw.get("function")
    if fn is not None:
        if not isinstance(fn, str):
            probs.append(f"rule {tag}: {label}.function 必须是 str")
        elif fn not in builtins.REWRITE_FNS:
            probs.append(f"rule {tag}: 未知 rewrite function {fn!r}")
        if "repl" in rw:
            probs.append(f"rule {tag}: {label} function/repl 并存 (repl 死配置)")
    if "repl" in rw and not isinstance(rw["repl"], str):
        probs.append(f"rule {tag}: {label}.repl 必须是 str")
    ms = rw.get("match_surface")
    if ms is not None and (not isinstance(ms, str) or ms not in _MATCH_SURFACES):
        probs.append(f"rule {tag}: match_surface 非法 {ms!r}")
    return probs


def _action_params_problems(kind: Any, params: dict[str, Any], tag: str) -> list[str]:  # noqa: ANN401, C901, PLR0912, PLR0915  # yaml 值天然 Any; 校验项逐条即分支
    """``action.params`` 按 kind 校验——键词表 + 必填项 + 值形。

    词表 = ``actions.py`` 实读名 ∪ 出厂注解键 (``verify``/``batch``/
    ``once_per_payload``/``hint``/``context`` 是不消费的文档性键,
    仍收录)。``builtin_transform`` 的 params 词表随 TRANSFORM_FNS
    逐函数定义 (各 ``builtins/`` 叶自查), 此处不限键名不检值。
    """
    probs: list[str] = []
    # kind 非 str (如 list) 不可哈希——``.get`` 直接 TypeError; 该形已由
    # rule 级 ``action.kind 非法`` 条目记名, 此处按未知 kind 放行跳过。
    vocab = _ACTION_PARAM_KEYS.get(kind) if isinstance(kind, str) else None
    if vocab is not None:
        probs.extend(
            f"rule {tag}: params 未知键 {k!r} (kind={kind})"
            for k in params
            if k not in vocab
        )
    if kind == "scan_install":
        sps = params.get("scan_patterns")
        if not isinstance(sps, list) or not sps:
            probs.append(
                f"rule {tag}: params.scan_patterns 缺或非空 list (scan_install 必填)"
            )
        else:
            for j, sp in enumerate(sps):
                probs.extend(
                    _scan_pattern_problems(sp, f"params.scan_patterns[{j}]", tag)
                )
        if "noise_filter" in params:
            probs.extend(
                _rx_problems(params["noise_filter"], f"rule {tag}: params.noise_filter")
            )
        if "vendored" in params and not isinstance(params["vendored"], bool):
            probs.append(f"rule {tag}: params.vendored 必须是 bool")
        if "dir" in params and not isinstance(params["dir"], str):
            probs.append(f"rule {tag}: params.dir 必须是 str")
    elif kind == "install_file":
        file_v = params.get("file")
        if not isinstance(file_v, str) or not file_v:
            probs.append(
                f"rule {tag}: params.file 缺或非空 str (install_file 必填, "
                "params['file'] 直取下标)"
            )
        probs.extend(
            f"rule {tag}: params.{k} 必须是 list[str]"
            for k in ("try_exts", "font_related_exts")
            if k in params and not _str_list(params[k])
        )
        # try_exts 逐元素直拼 ``params["file"]`` 成候选名 (actions.py
        # ``file + e``)——无 ``.`` 的值拼出无扩展名文件, 属 ``[ldf]`` 型
        # typo 死配置; ``b.ldf`` 复合后缀 ({lang}b.ldf) 是出厂合法形,
        # 故只查含点不查前缀。font_related_exts 消费面是 ``str.endswith``
        # 且出厂值全为裸名 ([tfm, pfb, vf, fd, map, enc])——点前缀检查
        # 会拦死出厂规则集, 刻意不查。
        probs.extend(
            f"rule {tag}: params.try_exts 扩展名须含 '.': {e!r}"
            for e in params.get("try_exts") or []
            if isinstance(e, str) and "." not in e
        )
        fa = params.get("file_aliases")
        if fa is not None:
            if not isinstance(fa, dict):
                probs.append(f"rule {tag}: params.file_aliases 必须是 map")
            else:
                probs.extend(
                    f"rule {tag}: params.file_aliases[{k!r}] 必须是 list[str]"
                    for k, v in fa.items()
                    if not _str_list(v)
                )
        probs.extend(
            f"rule {tag}: params.{k} 必须是 bool"
            for k in ("font_related", "already_present_ok")
            if k in params and not isinstance(params[k], bool)
        )
    elif kind == "run_tool":
        argv = params.get("argv")
        if not _str_list(argv) or not argv:
            probs.append(
                f"rule {tag}: params.argv 缺或非空 list[str] (run_tool 必填, "
                "空 argv 崩 subprocess)"
            )
        if "timeout" in params:
            try:
                int(params["timeout"])
            except (TypeError, ValueError):
                probs.append(f"rule {tag}: params.timeout 必须可转 int")
    elif kind == "regex_rewrite":
        rws = params.get("rewrites")
        if not isinstance(rws, list) or not rws:
            probs.append(
                f"rule {tag}: params.rewrites 缺或非空 list (regex_rewrite 必填)"
            )
        else:
            for j, rw in enumerate(rws):
                probs.extend(_rewrite_item_problems(rw, j, tag))
        probs.extend(
            f"rule {tag}: params.{k} 必须是 list[str]"
            for k in ("exts", "engine_flags")
            if k in params and not _str_list(params[k])
        )
    elif kind == "reject_route":
        route_v = params.get("route")
        if not isinstance(route_v, str) or not route_v:
            probs.append(
                f"rule {tag}: params.route 缺或非空 str (reject_route 必填, "
                "空 route 产无令牌 REJECT note)"
            )
        if "reason" in params and not isinstance(params["reason"], str):
            probs.append(f"rule {tag}: params.reason 必须是 str")
    return probs


def _dup_id_problems(rules: list[Any]) -> list[str]:  # yaml 值天然 Any
    """``rules:`` 段 id 唯一性校验 (合并表序位双出处)。

    rules/ 目录装载经 ``_yamlish._merge_into`` list 段 extend 不去重——两片
    同 ``id`` 曾静默拼成双规则 (``applied`` 键 ``{id}:{payload}`` 亦互相
    遮蔽)。``(phase, order)`` 撞位不拦: 同序位合法——出厂 order:9 族七条
    loop 规则同挂 (fileset_relocate/rungen_stub/nonctan_input_stub/
    docstrip_generate/tikz_library_install/pgf_library_install/svg_prepare,
    触发面互斥、稳定序按分片文件名序)。
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


def _re_compilable(pat: Any, label: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """Stdlib ``re`` 可编译校验 (``Taxonomy``/warnings 消费面引擎)。

    ``logparse.py`` 用 stdlib ``re``, 与 ``_rx_problems`` 的 ``regex``
    引擎不同源——同一 pattern 两引擎下可编译性可能分歧。
    """
    if not isinstance(pat, str):
        return [f"{label} 必须是 str"]
    try:
        re.compile(pat)
    except re.error as e:
        return [f"{label} 正则不可编译: {e}"]
    return []


def _taxonomy_problems(tax: Any) -> list[str]:  # noqa: ANN401, C901, PLR0912  # yaml 值天然 Any; 校验项逐条即分支
    """``taxonomy:`` 段条目校验——``Taxonomy.__init__``/``classify*`` 实读面。

    ``scope`` 缺席默认 ``head``; head/tail 条目装载期即
    ``re.compile(e["pattern"])`` (stdlib re + IGNORECASE), warnings
    条目只消费 ``id``/``warn_id`` (``pattern`` 在其上是死键);
    ``guard``/``payload_group``/``subclassify``/``preempts`` 为可选
    消费键。异形条目原逃逸为 __init__/逐条分类的裸异常。
    """
    probs: list[str] = []
    for i, e in enumerate(tax):
        tag = f"taxonomy[{i}]"
        if not isinstance(e, dict):
            probs.append(f"{tag} 必须是 map")
            continue
        if not isinstance(e.get("id"), str):
            probs.append(f"{tag}: id 缺或必须是 str")
        scope = e.get("scope", "head")
        if not isinstance(scope, str) or scope not in _TAXONOMY_SCOPES:
            probs.append(f"{tag}: scope 非法 {scope!r} (缺席默认 head)")
            continue
        if scope == "warnings":
            if not isinstance(e.get("warn_id"), str):
                probs.append(f"{tag}: warnings scope 需 str warn_id")
            if "pattern" in e:
                probs.append(f"{tag}: warnings scope 不消费 pattern (死键)")
        else:
            probs.extend(_re_compilable(e.get("pattern"), f"{tag}: pattern"))
        if "guard" in e:
            probs.extend(_re_compilable(e["guard"], f"{tag}: guard"))
        pg = e.get("payload_group")
        if pg is not None and not isinstance(pg, int):
            probs.append(f"{tag}: payload_group 必须是 int (显式 null = 无 payload)")
        sub = e.get("subclassify")
        if sub is not None:
            if not isinstance(sub, dict):
                probs.append(f"{tag}: subclassify 必须是 map")
            else:
                probs.extend(
                    _re_compilable(sub.get("pattern"), f"{tag}: subclassify.pattern")
                )
                if not isinstance(sub.get("into"), str):
                    probs.append(f"{tag}: subclassify.into 必须是 str")
                spg = sub.get("payload_group")
                if spg is not None and not isinstance(spg, int):
                    probs.append(f"{tag}: subclassify.payload_group 必须是 int")
        pre = e.get("preempts")
        if pre is not None and not _str_list(pre):
            probs.append(f"{tag}: preempts 必须是 list[str]")
    return probs


def _warnings_problems(warn: Any) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``warnings:`` 段条目校验——``logparse`` 无条件 ``w["id"]``/``w["pattern"]``。"""
    probs: list[str] = []
    for i, w in enumerate(warn):
        tag = f"warnings[{i}]"
        if not isinstance(w, dict):
            probs.append(f"{tag} 必须是 map")
            continue
        if not isinstance(w.get("id"), str):
            probs.append(f"{tag}: id 缺或必须是 str")
        probs.extend(_re_compilable(w.get("pattern"), f"{tag}: pattern"))
    return probs


def _producible_categories(data: dict[str, Any]) -> frozenset[str]:
    """``when.category`` 可命中域 = taxonomy ``id`` ∪ ``subclassify.into`` ∪ 引擎内建类。"""
    cats = set(_BUILTIN_CATS)
    tax = data.get("taxonomy")
    if isinstance(tax, list):
        for e in tax:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("id"), str):
                cats.add(e["id"])
            sub = e.get("subclassify")
            if isinstance(sub, dict) and isinstance(sub.get("into"), str):
                cats.add(sub["into"])
    return frozenset(cats)


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
#: 可选声明字段 ``mechanisms:`` 的 mech_id 形 (corpus 注册表值域
#: B/T/W 族; 注册表成员核验在 bench/py/report/mech_ids.py --validate)。
_MECH_ID_RX = re.compile(r"^[BTW]\d+$")
#: ``action`` 段合法键——``_apply`` 只读 kind/function/params, 其他键
#: 是死配置 (``param:`` 类 typo 与 ``categry:`` 同型 fail-open 面)。
_ACTION_KEYS = frozenset({"kind", "function", "params"})
#: 各 action.kind 的 ``params`` 合法键——``actions.py`` 实读名 ∪ 出厂
#: 注解键 (verify/batch/once_per_payload/hint/context 不消费但收)。
#: ``builtin_transform`` 缺席有意: 词表随 TRANSFORM_FNS 逐函数定义,
#: 各 ``builtins/`` 叶自持, 此处不做总表白名单 (造约束)。
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
#: ``_match_apply``/``_gate_eval``/``_precheck_phase`` 实读, via/note
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
        条目级校验, ``data.get(...) or {}`` 的 falsy 容错口径保持
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
            # engine.py:1749-1757 的 int()/float() 实读键——不可转即
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
        ``engines`` 各段的键白名单 + 值形 + 互需字段, 全与
        actions.py/engine.py 实读面对齐 (详各 helper 注)。非 map 段先拦
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

        进程内按 ``(路径, 分片指纹)`` 缓存展开后纯数据, 命中 deepcopy 返回
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
