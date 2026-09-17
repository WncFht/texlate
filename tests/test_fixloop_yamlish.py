"""_yamlish 薄封装（PyYAML safe_load + 目录合并）+ 出厂 rules/ 装载校验。"""

from pathlib import Path

import pytest

from texlate.compile.fixloop._yamlish import YamlishError, load_yaml, loads

RULES_DIR = Path(__file__).resolve().parents[1] / "src/texlate/compile/fixloop/rules"


def _shipped_rule_count() -> int:
    """rules/ 各分片 rules: 段条目数合计——计数不硬编码，按分片装载现算。"""
    return sum(
        len(load_yaml(f).get("rules") or []) for f in sorted(RULES_DIR.glob("*.yaml"))
    )


def test_shipped_rules_dir_loads() -> None:
    data = load_yaml(RULES_DIR)
    assert data["version"] == 1
    assert data["meta"]["loop"]["max_rounds"] == 8  # noqa: PLR2004 - schema 断言值
    rules = data["rules"]
    # 合并完整性：装载条数 == 各分片 rules: 段条目合计；id 无重复
    assert len(rules) == _shipped_rule_count()
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids))
    assert ids[0] == "latex209_reject"
    assert "install_file" in ids


def test_load_yaml_dir_merges_lists_and_maps(tmp_path: Path) -> None:
    (tmp_path / "10-a.yaml").write_text("version: 1\nmeta: {a: 1}\nrules: [{id: x}]\n")
    (tmp_path / "20-b.yaml").write_text(
        "version: 1\nmeta: {b: 2}\nrules: [{id: y}, {id: z}]\n"
    )
    data = load_yaml(tmp_path)
    assert [r["id"] for r in data["rules"]] == ["x", "y", "z"]  # 文件名序拼接
    assert data["meta"] == {"a": 1, "b": 2}


def test_load_yaml_dir_scalar_conflict_rejected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("version: 1\n")
    (tmp_path / "b.yaml").write_text("version: 2\n")
    with pytest.raises(YamlishError, match="冲突"):
        load_yaml(tmp_path)


def test_load_yaml_empty_dir_rejected(tmp_path: Path) -> None:
    with pytest.raises(YamlishError, match=r"无 \*\.yaml"):
        load_yaml(tmp_path)


def test_loads_parses_standard_yaml() -> None:
    out = loads("a:\n  b: 1\n  c:\n    - x\n    - {k: v}\n")
    assert out == {"a": {"b": 1, "c": ["x", {"k": "v"}]}}


def test_loads_rejects_garbage() -> None:
    with pytest.raises(YamlishError, match="invalid yaml"):
        loads("a: [unclosed\n  b: }")


def test_load_yaml_missing_file(tmp_path: Path) -> None:
    with pytest.raises(YamlishError, match="no such file"):
        load_yaml(tmp_path / "gone.yaml")
