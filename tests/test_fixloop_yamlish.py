"""_yamlish 薄封装（PyYAML safe_load）+ 出厂 rules.yaml 装载校验。"""

from pathlib import Path

import pytest

from texlate.compile.fixloop._yamlish import YamlishError, load_yaml, loads

RULES_YAML = (
    Path(__file__).resolve().parents[1] / "src/texlate/compile/fixloop/rules.yaml"
)


def test_shipped_rules_yaml_loads() -> None:
    data = load_yaml(RULES_YAML)
    assert data["version"] == 1
    assert data["meta"]["loop"]["max_rounds"] == 8  # noqa: PLR2004 - schema 断言值
    assert len(data["rules"]) == 36  # noqa: PLR2004 - 33 + case_link/graphic_repair/invalid_char_recode
    ids = [r["id"] for r in data["rules"]]
    assert ids[0] == "latex209_reject"
    assert "install_file" in ids


def test_loads_parses_standard_yaml() -> None:
    out = loads("a:\n  b: 1\n  c:\n    - x\n    - {k: v}\n")
    assert out == {"a": {"b": 1, "c": ["x", {"k": "v"}]}}


def test_loads_rejects_garbage() -> None:
    with pytest.raises(YamlishError, match="invalid yaml"):
        loads("a: [unclosed\n  b: }")


def test_load_yaml_missing_file(tmp_path: Path) -> None:
    with pytest.raises(YamlishError, match="no such file"):
        load_yaml(tmp_path / "gone.yaml")
