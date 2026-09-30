r"""Ruleset._validate 跨分片同 id 拦检 (A5) + ``_DEP_INPUT_RE`` 花括号形钉 (A3)。

rules/ 目录装载经 ``_yamlish._merge_into`` list 段 extend 不去重——分片间同
``id`` 规则曾静默拼双 (applied 键 ``{id}:{payload}`` 亦互相遮蔽);
``_validate`` 现以 seen_ids (id → 合并表首见序位) 拦检, 报错带双出处。
同 phase 同 order **不拦**：出厂 rules/ 多条 loop 规则同挂 ``order: 9``
(触发面互斥、稳定序按分片文件名序——权威清单见
test_fixloop_rules.test_phase_ordering 的 ``loop[:11]`` 钉),
撞位即合法并列, 不判冲突。

``_DEP_INPUT_RE``: ``\\input{x}`` 零空白花括号形 (LaTeX 主导) 曾因 ``\\s+``
强空白漏配。修复按 arxiv/locate.py:53-54 分形口径——花括号 ``\\s*`` /
裸名 ``\\s+``: ``\\inputfoo``/``\\inputlineno`` 不被 ``\\input`` 前缀误吃
(lineno.sty 真实存在, 误吃会真装)。
"""

import re
from pathlib import Path

import pytest
import regex

from texlate.compile.fixloop import Ruleset, RulesetError, load_ruleset
from texlate.compile.fixloop.engine import _dep_stems

_RULE_A = (
    "{id: a, phase: loop, order: 1, when: {always: true},"
    " action: {kind: run_tool, params: {argv: ['true']}}}"
)
_RULE_B = (
    "{id: b, phase: loop, order: 1, when: {always: true},"
    " action: {kind: run_tool, params: {argv: ['true']}}}"
)
_RULE_BAD_BUILTIN = (
    "{id: bad, phase: loop, order: 2, when: {always: true},"
    " action: {kind: builtin_transform, function: nope_missing}}"
)


def _shard(*rules: str) -> str:
    """单片 yaml 文本: version + taxonomy 单行 + rules 列表 (元素为 flow-map 行)。

    ``taxonomy`` 声明 ``missing_file``——``_producible_categories`` 值域
    校验要求 ``when.category`` 命中片内可产出类 (_GOOD/ok2 钉用),
    无 taxonomy 的合成片只剩内建类集会误弃合法规则。
    """
    body = "\n".join(f"  - {r}" for r in rules)
    return (
        "version: 1\n"
        "taxonomy:\n"
        "  - {id: missing_file, pattern: 'x'}\n"
        f"rules:\n{body}\n"
    )


def test_cross_shard_dup_id_rejected(tmp_path: Path) -> None:
    """两片同 id → RulesetError, 消息带合并表内双序位。"""
    (tmp_path / "10-a.yaml").write_text(_shard(_RULE_A), encoding="utf-8")
    (tmp_path / "20-b.yaml").write_text(_shard(_RULE_A), encoding="utf-8")
    with pytest.raises(RulesetError, match=r"rules\[0\].*rules\[1\]"):
        Ruleset.load(tmp_path)


def test_single_shard_dup_id_rejected(tmp_path: Path) -> None:
    """单片内同 id 同样拦——单文件装载路径也过 _validate。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_A), encoding="utf-8")
    with pytest.raises(RulesetError, match=r"rules\[0\].*rules\[1\]"):
        Ruleset.load(shard)


def test_dup_id_message_names_both_origins(tmp_path: Path) -> None:
    """重复出处钉: 三现报两次、各带首见序位 (排障能定位到合并表序位)。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_B, _RULE_A, _RULE_A), encoding="utf-8")
    with pytest.raises(RulesetError, match=r"rules\[0\].*rules\[2\]") as exc:
        Ruleset.load(shard)
    assert "rules[0] 与 rules[3]" in str(exc.value)


def test_same_phase_order_tie_allowed(tmp_path: Path) -> None:
    """同 phase 同 order 撞位合法 (出厂 loop order:9 族即此形)——两条都进表。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_B), encoding="utf-8")
    rs = Ruleset.load(shard)
    assert [r.id for r in rs.phase("loop")] == ["a", "b"]


def test_shipped_ruleset_no_dup_ids() -> None:
    """出厂 rules/ 现态 id 唯一——拦检上线后 load 依旧全绿。"""
    rs = Ruleset.load()
    ids = [r.id for r in rs.rules]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------ tolerant 装载
def test_tolerant_load_drops_unknown_builtin(tmp_path: Path) -> None:
    """``tolerant=True``：未知 builtin_transform 只弃该条记 ``skipped_rules``——
    yaml/代码版本错位（server 跑旧 .py 读新 rules/）时一条坏规则不再击穿
    整条修复臂（5+ 任务 RulesetError 全灭实证）。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_BAD_BUILTIN), encoding="utf-8")
    rs = Ruleset.load(shard, tolerant=True)
    assert [r.id for r in rs.rules] == ["a"]
    assert len(rs.skipped_rules) == 1
    assert "bad" in rs.skipped_rules[0]
    assert "nope_missing" in rs.skipped_rules[0]


def test_strict_load_still_rejects_unknown_builtin(tmp_path: Path) -> None:
    """严格默认面不变：同规则照旧 raise——写规则的验证面不收。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_BAD_BUILTIN), encoding="utf-8")
    with pytest.raises(RulesetError, match="未知 builtin_transform"):
        Ruleset.load(shard)


def test_tolerant_still_raises_file_level(tmp_path: Path) -> None:
    """file 级问题（dup id / version）tolerant 也照常 raise——只放 rule 级。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_A), encoding="utf-8")
    with pytest.raises(RulesetError, match="重复定义"):
        Ruleset.load(shard, tolerant=True)
    bad = tmp_path / "b.yaml"
    bad.write_text("version: 2\nrules: []\n", encoding="utf-8")
    with pytest.raises(RulesetError, match="version"):
        Ruleset.load(bad, tolerant=True)


def test_tolerant_drops_non_map_rule(tmp_path: Path) -> None:
    """非 map 规则项同弃——rule 级问题一律单条弃用不炸库。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(
        'version: 1\nrules:\n  - "x"\n  - ' + _RULE_A + "\n", encoding="utf-8"
    )
    rs = Ruleset.load(shard, tolerant=True)
    assert [r.id for r in rs.rules] == ["a"]
    assert rs.skipped_rules


def test_load_ruleset_tolerant_passthrough(tmp_path: Path) -> None:
    """``load_ruleset`` 函数入口透传 tolerant 开关。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_BAD_BUILTIN), encoding="utf-8")
    rs = load_ruleset(shard, tolerant=True)
    assert [r.id for r in rs.rules] == ["a"]
    assert rs.skipped_rules


def test_dep_input_braced_no_space_form(tmp_path: Path) -> None:
    r"""``\\input{x}`` 零空白花括号形收 stem (A3 漏配形态); ``\s*``/``\s+``
    分形下 ``\\inputfoo``/``\\inputlineno`` 前缀不误吃。"""
    f = tmp_path / "m.tex"
    f.write_text(
        "\\input{realdep}\n"
        "\\input{sub/fig.tex}\n"
        "\\input {spaced}\n"
        "\\input baredep\n"
        "\\inputfoo notdep\n"
        "\\inputlineno\n",
        encoding="utf-8",
    )
    assert _dep_stems(f) == ["realdep", "sub/fig.tex", "spaced", "baredep"]


def test_rules_yaml_load_hook_pattern_covers_shards() -> None:
    r"""A4 钉: pre-commit rules-yaml-load 的 ``files`` 正则须命中 rules/
    分片——曾锁 ``rules\.yaml$`` (分片落地后永不触发的 vacuous check)。"""
    repo = Path(__file__).resolve().parents[1]
    cfg = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    m = re.search(r"id:\s*rules-yaml-load\b.*?files:\s*'([^']+)'", cfg, re.DOTALL)
    assert m, "rules-yaml-load hook 缺 files 模式"
    rx = re.compile(m.group(1))
    shards = sorted((repo / "src/texlate/compile/fixloop/rules").glob("*.yaml"))
    assert shards, "rules/ 分片目录为空"
    for s in shards:
        rel = s.relative_to(repo).as_posix()
        assert rx.search(rel), f"hook files 模式不命中 {rel}"


# ------------------------------------------------------------ Ruleset.load 缓存
def test_load_cache_hit_returns_independent_object(tmp_path: Path) -> None:
    """同路径二次 load 命中缓存: 内容一致但深拷贝隔离——非同一对象。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A), encoding="utf-8")
    rs1 = Ruleset.load(shard)
    rs2 = Ruleset.load(shard)
    assert rs1 is not rs2
    assert rs1.rules[0].raw is not rs2.rules[0].raw
    assert [r.id for r in rs2.rules] == ["a"]


def test_load_cache_mutation_isolation(tmp_path: Path) -> None:
    """命中件原地改写 (ruleset_with_baseline 注 baseline_dir 形态) 不回流缓存。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A), encoding="utf-8")
    rs1 = Ruleset.load(shard)
    rs1.rules[0].raw["baseline_dir"] = "/x"
    rs2 = Ruleset.load(shard)
    assert "baseline_dir" not in rs2.rules[0].raw


def test_load_cache_shard_edit_invalidates(tmp_path: Path) -> None:
    """分片改动 (mtime/size 漂移) → 指纹失效重载: 改文本即见新内容。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A), encoding="utf-8")
    assert len(Ruleset.load(shard).rules) == 1
    shard.write_text(_shard(_RULE_A, _RULE_B), encoding="utf-8")
    assert [r.id for r in Ruleset.load(shard).rules] == ["a", "b"]


def test_load_cache_shard_add_invalidates(tmp_path: Path) -> None:
    """目录面新增分片同样漂移指纹——多片装载的缓存正确性。"""
    (tmp_path / "10-a.yaml").write_text(_shard(_RULE_A), encoding="utf-8")
    assert len(Ruleset.load(tmp_path).rules) == 1
    (tmp_path / "20-b.yaml").write_text(_shard(_RULE_B), encoding="utf-8")
    assert [r.id for r in Ruleset.load(tmp_path).rules] == ["a", "b"]


def test_shipped_rewrites_repl_escapes_valid() -> None:
    """出厂全部 ``regex_rewrite`` 的 ``repl`` 须过 ``re.sub`` 转义处理。

    钉 fontspec_double_merge 崩规类缺陷：yaml 双引号串 ``\\\\X`` 解码成
    ``\\X`` 直接喂 ``pat.sub``，``\\A`` 类非法转义在点火时炸
    ``bad escape``——规则静默失效（stub-fill2 实证：4 IMS cell
    already_def 清不掉）。全规则 repl 扫一遍编译+替换即可拦住。

    编译引擎镜像 actions._compile_rewrites 的 ``regex``（非 stdlib
    ``re``）——pdftex_prim_guard 平衡花括号臂用 ``(?&name)`` 递归子模式，
    stdlib ``re`` 无此语法会误报（primguard 实证）。
    """
    rs = Ruleset.load()
    checked = 0
    for rule in rs.rules:
        for rw in (rule.action.get("params") or {}).get("rewrites") or []:
            if "repl" in rw:
                regex.compile(rw["pattern"], regex.MULTILINE).sub(
                    rw["repl"], "SAMPLE\n"
                )
                checked += 1
    assert checked > 0


def test_fontspec_double_merge_repl_output() -> None:
    """fontspec_double_merge 注入对：literal ``\\AddToHook`` 双钩 + 原文回插。"""
    rs = Ruleset.load()
    rule = next(r for r in rs.rules if r.id == "fontspec_double_merge")
    rw = rule.action["params"]["rewrites"][0]
    out = regex.compile(rw["pattern"], regex.MULTILINE).sub(
        rw["repl"], "\\documentclass{arximspdf}\n"
    )
    assert "\\AddToHook{package/fontspec/before}" in out
    assert "\\AddToHook{package/fontspec/after}" in out
    assert out.rstrip().endswith("\\documentclass{arximspdf}")


# ------------------------------------------------------------ spec 子语言 schema
# 深度校验 (键白名单 + 值形 + 互需字段)——与 actions.py/engine.py 实读面对齐。
# 每行 = 一条 schema 违规规则 + 期望报错关键词; 严格面 raise, tolerant 面弃条。

_GOOD = (
    "{id: ok, phase: loop, order: 1, when: {category: missing_file},"
    " action: {kind: regex_rewrite,"
    " params: {rewrites: [{pattern: 'x', repl: 'y'}]}}}"
)

_SCHEMA_BAD_RULES = [
    # —— when 段值形 ——
    (
        (
            "{id: w1, phase: loop, when: {always: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "always",
    ),
    (
        (
            "{id: w2, phase: loop, when: {category: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "category",
    ),
    (
        (
            "{id: w3, phase: loop, when: {payload_required: 1},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "payload_required",
    ),
    (
        (
            "{id: w4, phase: loop, when: {main_head_contains: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "main_head_contains",
    ),
    (
        (
            "{id: w5, phase: loop, when: {any: {category: x}},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "when.any",
    ),
    (
        (
            "{id: w6, phase: loop, when: {any: [5]},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "必须是 map",
    ),
    (
        (
            "{id: w7, phase: loop, when: {any: [{category: 5}]},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "category",
    ),
    # —— condition 段值形/结构 ——
    (
        (
            "{id: c1, phase: loop, when: {always: true}, condition: {any: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "condition.any",
    ),
    (
        (
            "{id: c2, phase: loop, when: {always: true}, condition: {any: [5]},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "必须是 map",
    ),
    (
        (
            "{id: c3, phase: loop, when: {always: true},"
            " condition: {source_contains: '['},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "正则不可编译",
    ),
    (
        (
            "{id: c4, phase: loop, when: {always: true}, condition: {ctx_suggests: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "ctx_suggests",
    ),
    (
        (
            "{id: c5, phase: loop, when: {always: true},"
            " condition: {engine_in: xelatex},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "engine_in",
    ),
    (
        (
            "{id: c6, phase: loop, when: {always: true}, condition: {fileset: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "fileset",
    ),
    (
        (
            "{id: c7, phase: loop, when: {always: true},"
            " condition: {fileset: {has_ext: '.tex'}},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "has_ext",
    ),
    (
        (
            "{id: c8, phase: loop, when: {always: true},"
            " condition: {fileset: {bogus: []}},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "未知键 'bogus'",
    ),
    (
        (
            "{id: c9, phase: loop, when: {always: true},"
            " condition: {package_version_ge: {file: 5}},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "file 必须是 str",
    ),
    (
        (
            "{id: c10, phase: loop, when: {always: true},"
            " condition: {package_version_ge: {file: 'a.sty', version: 'x'}},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "可转 int",
    ),
    (
        (
            "{id: c11, phase: loop, when: {always: true},"
            " condition: {tool_available: 5},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "必须是 str",
    ),
    # —— action 段形状/键 ——
    ("{id: a1, phase: loop, when: {always: true}, action: 5}", "action 必须是 map"),
    (
        (
            "{id: a2, phase: loop, when: {always: true},"
            " action: {kind: run_tool, param: {}}}"
        ),
        "action 未知键 'param'",
    ),
    (
        (
            "{id: a3, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: 5}}"
        ),
        "params 必须是 map",
    ),
    (
        (
            "{id: a4, phase: loop, when: {always: true},"
            " action: {kind: run_tool, function: f, params: {argv: ['x']}}}"
        ),
        "仅 builtin_transform",
    ),
    (
        (
            "{id: a5, phase: loop, when: {always: true},"
            " action: {kind: builtin_transform, function: 5}}"
        ),
        "未知 builtin_transform",
    ),
    # —— params 按 kind 词表/必填/值形 ——
    (
        (
            "{id: p1, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {bogus: 1}}}"
        ),
        "params 未知键 'bogus'",
    ),
    (
        (
            "{id: p2, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {}}}"
        ),
        "argv 缺或非空",
    ),
    (
        (
            "{id: p3, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: 'x'}}}"
        ),
        "argv 缺或非空",
    ),
    (
        (
            "{id: p4, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x'], timeout: 'x'}}}"
        ),
        "timeout 必须可转 int",
    ),
    (
        (
            "{id: p5, phase: loop, when: {always: true},"
            " action: {kind: install_file, params: {}}}"
        ),
        "file 缺或非空",
    ),
    (
        (
            "{id: p6, phase: loop, when: {always: true},"
            " action: {kind: install_file,"
            " params: {file: '{payload}', try_exts: '.sty'}}}"
        ),
        "try_exts",
    ),
    (
        (
            "{id: p7, phase: loop, when: {always: true},"
            " action: {kind: install_file,"
            " params: {file: '{payload}', file_aliases: {a: 'b'}}}}"
        ),
        "file_aliases",
    ),
    (
        (
            "{id: p8, phase: loop, when: {always: true},"
            " action: {kind: install_file,"
            " params: {file: '{payload}', font_related: 1}}}"
        ),
        "font_related",
    ),
    (
        (
            "{id: p9, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite, params: {}}}"
        ),
        "rewrites 缺或非空",
    ),
    (
        (
            "{id: p10, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite, params: {rewrites: [5]}}}"
        ),
        "必须是 map",
    ),
    (
        (
            "{id: p11, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite, params: {rewrites: [{repl: 'x'}]}}}"
        ),
        "pattern 缺",
    ),
    (
        (
            "{id: p12, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite, params: {rewrites: [{pattern: '['}]}}}"
        ),
        "正则不可编译",
    ),
    (
        (
            "{id: p13, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite,"
            " params: {rewrites: [{pattern: 'x', flags: ['MULTILINEE']}]}}}"
        ),
        "未知旗",
    ),
    (
        (
            "{id: p14, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite,"
            " params: {rewrites: [{pattern: 'x', flags: 'M'}]}}}"
        ),
        "flags 必须是",
    ),
    (
        (
            "{id: p15, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite,"
            " params: {rewrites: [{pattern: 'x', function: px_to_bp, repl: 'y'}]}}}"
        ),
        "并存",
    ),
    (
        (
            "{id: p16, phase: loop, when: {always: true},"
            " action: {kind: regex_rewrite, params: {rewrites: [{pattern: 'x'}],"
            " exts: '.tex'}}}"
        ),
        "exts 必须是",
    ),
    (
        (
            "{id: p17, phase: loop, when: {always: true},"
            " action: {kind: reject_route, params: {}}}"
        ),
        "route 缺或非空",
    ),
    (
        (
            "{id: p18, phase: loop, when: {always: true},"
            " action: {kind: reject_route, params: {route: 'manual', reason: 5}}}"
        ),
        "reason 必须是 str",
    ),
    (
        (
            "{id: p19, phase: loop, when: {always: true},"
            " action: {kind: escalate_llm, params: {bogus: 1}}}"
        ),
        "params 未知键",
    ),
    (
        (
            "{id: p20, phase: loop, when: {always: true},"
            " action: {kind: scan_install, params: {}}}"
        ),
        "scan_patterns 缺或非空",
    ),
    (
        (
            "{id: p21, phase: loop, when: {always: true},"
            " action: {kind: scan_install,"
            " params: {scan_patterns: [{regex: '['}]}}}"
        ),
        "正则不可编译",
    ),
    (
        (
            "{id: p22, phase: loop, when: {always: true},"
            " action: {kind: scan_install,"
            " params: {scan_patterns: [{regex: 'x', bogus: 1}]}}}"
        ),
        "未知键 'bogus'",
    ),
    (
        (
            "{id: p23, phase: loop, when: {always: true},"
            " action: {kind: scan_install,"
            " params: {scan_patterns: [{regex: 'x'}], noise_filter: 5}}}"
        ),
        "noise_filter",
    ),
    (
        (
            "{id: p24, phase: loop, when: {always: true},"
            " action: {kind: scan_install,"
            " params: {scan_patterns: [{regex: 'x'}], vendored: 5}}}"
        ),
        "vendored",
    ),
    (
        (
            "{id: p25, phase: loop, when: {always: true},"
            " action: {kind: scan_install,"
            " params: {scan_patterns: [{regex: 'x'}], dir: 5}}}"
        ),
        "dir 必须是 str",
    ),
    # —— engines 段 ——
    (
        (
            "{id: e1, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}}, engines: 5}"
        ),
        "engines 必须是 map",
    ),
    (
        (
            "{id: e2, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}},"
            " engines: {xelate: {mode: native}}}"
        ),
        "未知引擎",
    ),
    (
        (
            "{id: e3, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}},"
            " engines: {xelatex: 5}}"
        ),
        "必须是 map",
    ),
    (
        (
            "{id: e4, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}},"
            " engines: {xelatex: {mode: native, bogus: 1}}}"
        ),
        "未知键 'bogus'",
    ),
    (
        (
            "{id: e5, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}},"
            " engines: {xelatex: {mode: bogus}}}"
        ),
        "mode 非法",
    ),
    # —— 顶层字段值形 ——
    (
        (
            "{id: 5, phase: loop, when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "id 必须是 str",
    ),
    (
        (
            "{id: t1, phase: loop, order: 'x', when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "order 必须可转 float",
    ),
    (
        (
            "{id: t2, phase: [loop], when: {always: true},"
            " action: {kind: run_tool, params: {argv: ['x']}}}"
        ),
        "phase 非法",
    ),
]


@pytest.mark.parametrize(("rule_yaml", "match"), _SCHEMA_BAD_RULES)
def test_schema_violation_rejected_strict(
    tmp_path: Path, rule_yaml: str, match: str
) -> None:
    """schema 违规在严格面 raise——消息带具体违规点 (逐键一处 probs.append)。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(rule_yaml), encoding="utf-8")
    with pytest.raises(RulesetError, match=match):
        Ruleset.load(shard)


@pytest.mark.parametrize(("rule_yaml", "match"), _SCHEMA_BAD_RULES)
def test_schema_violation_dropped_tolerant(
    tmp_path: Path, rule_yaml: str, match: str
) -> None:
    """同一批违规规则在 tolerant 面只弃肇事条——``skipped_rules`` 记违规点,
    合法规则照常进库 (rule 级问题不击穿整条修复臂)。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_GOOD, rule_yaml), encoding="utf-8")
    rs = Ruleset.load(shard, tolerant=True)
    assert [r.id for r in rs.rules] == ["ok"]
    assert rs.skipped_rules
    assert any(match in p for p in rs.skipped_rules)


def test_schema_valid_rule_passes_both_modes(tmp_path: Path) -> None:
    """良构规则 (含 condition/fileset/engines 各段) 双面都过——schema 不误伤。"""
    good = (
        "{id: ok2, phase: loop, order: 1.5,"
        " when: {any: [{category: missing_file, payload_required: true}]},"
        " condition: {engine_in: [xelatex], fileset: {has_ext: ['.tex']}},"
        " action: {kind: install_file, params: {file: '{payload}',"
        " try_exts: ['.sty'], font_related: false}},"
        " engines: {xelatex: {mode: native},"
        " tectonic: {mode: degrade, degrade: skip, fallback: advisory}}}"
    )
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_GOOD, good), encoding="utf-8")
    assert [r.id for r in Ruleset.load(shard).rules] == ["ok", "ok2"]
    rs = Ruleset.load(shard, tolerant=True)
    assert [r.id for r in rs.rules] == ["ok", "ok2"]
    assert not rs.skipped_rules


def test_shipped_ruleset_passes_schema() -> None:
    """出厂 rules/ 全量过新 schema——深度校验上线对现态零误伤 (acceptance a)。"""
    rs = Ruleset.load()
    assert rs.rules


def test_shipped_ruleset_scale_pin() -> None:
    """出厂 rules/ 规模唯一权威钉: ``len(rules) >= 209`` (当前真实条数)。

    各车道测试文件里发散的 ``len(rules) >= N`` 下界钉 (112/113/114/196/
    200/… 约 8 处) 以本钉为 canonical——车道落地只加新规则, 库规模
    只增不减; 后续扩容抬升本钉即可, 车道文件不再各自钉数。
    """
    assert len(load_ruleset().rules) >= 209  # noqa: PLR2004 - 库规模权威钉
