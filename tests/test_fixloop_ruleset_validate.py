r"""Ruleset._validate 跨分片同 id 拦检 (A5) + ``_DEP_INPUT_RE`` 花括号形钉 (A3)。

rules/ 目录装载经 ``_yamlish._merge_into`` list 段 extend 不去重——分片间同
``id`` 规则曾静默拼双 (applied 键 ``{id}:{payload}`` 亦互相遮蔽);
``_validate`` 现以 seen_ids (id → 合并表首见序位) 拦检, 报错带双出处。
同 phase 同 order **不拦**：出厂 rules/ 四条 loop 规则同挂 ``order: 9``
(rungen_stub/nonctan_input_stub/docstrip_generate/svg_prepare, 触发面互斥、
稳定序按分片文件名序——见 test_fixloop_rules.test_phase_ordering 注释),
撞位即合法并列, 不判冲突。

``_DEP_INPUT_RE``: ``\\input{x}`` 零空白花括号形 (LaTeX 主导) 曾因 ``\\s+``
强空白漏配。修复按 arxiv/locate.py:53-54 分形口径——花括号 ``\\s*`` /
裸名 ``\\s+``: ``\\inputfoo``/``\\inputlineno`` 不被 ``\\input`` 前缀误吃
(lineno.sty 真实存在, 误吃会真装)。
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, RulesetError
from texlate.compile.fixloop.engine import _dep_stems

_RULE_A = (
    "{id: a, phase: loop, order: 1, when: {always: true}, action: {kind: run_tool}}"
)
_RULE_B = (
    "{id: b, phase: loop, order: 1, when: {always: true}, action: {kind: run_tool}}"
)


def _shard(*rules: str) -> str:
    """单片 yaml 文本: version + rules 列表 (元素为 flow-map 行)。"""
    body = "\n".join(f"  - {r}" for r in rules)
    return f"version: 1\nrules:\n{body}\n"


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
    """同 phase 同 order 撞位合法 (出厂 loop order:9 四件即此形)——两条都进表。"""
    shard = tmp_path / "a.yaml"
    shard.write_text(_shard(_RULE_A, _RULE_B), encoding="utf-8")
    rs = Ruleset.load(shard)
    assert [r.id for r in rs.phase("loop")] == ["a", "b"]


def test_shipped_ruleset_no_dup_ids() -> None:
    """出厂 rules/ 现态 id 唯一——拦检上线后 load 依旧全绿。"""
    rs = Ruleset.load()
    ids = [r.id for r in rs.rules]
    assert len(ids) == len(set(ids))


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
