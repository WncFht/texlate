"""ruleset._ruleset_validate — rules/ 装载期校验助手簇 (C5 拆叶)。

``_when_problems``/``_cond_problems``/``_action_params_problems``/
``_dup_id_problems``/``_taxonomy_problems``/``_warnings_problems`` +
值形原语 (``_str_list``/``_rx_problems``/``_re_compilable``/
``_rewrite_flag_bit``) + ``_producible_categories``——与
``_actions_*`` 叶/engine 实读面逐键对齐, 未知键 fail-closed、词表
白名单拦 typo fail-open 面。
"""

from __future__ import annotations

import re
from typing import Any

import regex

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop._ruleset_vocab import (
    _ACTION_PARAM_KEYS,
    _BUILTIN_CATS,
    _COND_KEYS,
    _COND_REGEX_KEYS,
    _COND_STR_KEYS,
    _ENGINE_NAMES,
    _FILESET_KEYS,
    _MATCH_SURFACES,
    _REWRITE_KEYS,
    _SCAN_PATTERN_KEYS,
    _TAXONOMY_SCOPES,
    _WHEN_ITEM_KEYS,
    _WHEN_KEYS,
)


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

    词表 = ``actions`` 叶实读名 ∪ 出厂注解键 (``verify``/``batch``/
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
        # try_exts 逐元素直拼 ``params["file"]`` 成候选名 (actions 叶
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
