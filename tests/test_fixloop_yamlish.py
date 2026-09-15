"""_yamlish 子集解析器单测 + 出厂 rules.yaml 装载校验。

子集边界见 _yamlish.py docstring: 块级 map/seq + 单行 flow + 引号标量;
多文档/anchor/tag/块标量/flow 跨行/tab 缩进一律 YamlishError。
"""

from pathlib import Path

import pytest

from texlate.compile.fixloop._yamlish import YamlishError, load_yaml, loads

RULES_YAML = (
    Path(__file__).resolve().parents[1] / "src/texlate/compile/fixloop/rules.yaml"
)


# ---------------------------------------------------------------- 出厂文件
def test_shipped_rules_yaml_loads() -> None:
    data = load_yaml(RULES_YAML)
    assert data["version"] == 1
    assert data["meta"]["loop"]["max_rounds"] == 8  # noqa: PLR2004 - schema 断言值
    assert len(data["rules"]) == 24  # noqa: PLR2004 - 25 条对账 = 24 rules + version_guard 策略
    ids = [r["id"] for r in data["rules"]]
    assert ids[0] == "latex209_reject"
    assert "install_file" in ids


def test_shipped_rules_yaml_pyyaml_parity() -> None:
    yaml = pytest.importorskip("yaml")  # venv 无 PyYAML → skip; 有则深度对拍
    assert load_yaml(RULES_YAML) == yaml.safe_load(RULES_YAML.read_text())


# ---------------------------------------------------------------- 正常子集
def test_nested_map_and_seq() -> None:
    out = loads("a:\n  b: 1\n  c:\n    - x\n    - {k: v}\n")
    assert out == {"a": {"b": 1, "c": ["x", {"k": "v"}]}}


def test_same_indent_seq_under_key() -> None:
    # rules.yaml 实际用法: key 下的 `- ` 与 key 同缩进
    out = loads("rules:\n- {id: a}\n- id: b\n  v: 2\n")
    assert out == {"rules": [{"id": "a"}, {"id": "b", "v": 2}]}


def test_flow_collections_single_line() -> None:
    out = loads("x: {a: 1, b: [p, q]}\ny: [1, 2.5, true, null]\nz: {}\n")
    assert out == {
        "x": {"a": 1, "b": ["p", "q"]},
        "y": [1, 2.5, True, None],
        "z": {},
    }


def test_quoted_scalars() -> None:
    out = loads("a: \"x: y # z\"\nb: 'it''s'\nc: \"e\\n\\\\d\"\n")
    assert out == {"a": "x: y # z", "b": "it's", "c": "e\n\\d"}


def test_comment_stripping() -> None:
    out = loads("a: 1 # trailing\n# full line\nb: 'x # y'\n")
    assert out == {"a": 1, "b": "x # y"}


def test_scalar_coercion() -> None:
    out = loads("n: -3\nf: 0.5\nz: ~\ns: hello world\nt: True\n")
    assert out == {"n": -3, "f": 0.5, "z": None, "s": "hello world", "t": True}


def test_null_payload_group_preserved() -> None:
    # taxonomy 用 `payload_group: null` 显式声明"无 payload"——必须保持 None
    out = loads("- {id: m, payload_group: null}\n- {id: n}\n")
    assert out[0]["payload_group"] is None
    assert "payload_group" not in out[1]


def test_regex_string_roundtrip() -> None:
    # rules.yaml 的 regex 大量用双引号 \\\\ 写法 —— 解析后应是单个反斜杠对
    out = loads("p: \"File `([^']+\\\\.sty)' not found\"\n")
    assert out["p"] == "File `([^']+\\.sty)' not found"


def test_multiline_flow_map() -> None:
    # prettier 会把超长 flow 折成多行 —— 续行 (缩进深于父) 吸进同一集合
    out = loads('a: {x: 1,\n  y: "two"}\nb: [\n  1,\n  2,\n]\n')
    assert out == {"a": {"x": 1, "y": "two"}, "b": [1, 2]}
    # seq item 形态 (rules.yaml warnings/rules 的 prettier 折行)
    out = loads("rules:\n  - {\n      id: r1,\n      tags: [a, b],\n    }\n")
    assert out == {"rules": [{"id": "r1", "tags": ["a", "b"]}]}


# ---------------------------------------------------------------- 拒绝面
@pytest.mark.parametrize(
    ("bad", "frag"),
    [
        ("a:\n\tb: 1\n", "tab"),
        ("a: {x: 1,\n", "未闭合"),  # EOF 仍未闭合
        ("a: {x: 1,\nb: 2}\n", "未闭合"),  # 续行缩进不深于父 → 拒
        ("---\na: 1\n", "多文档"),
        ("a: &x 1\n", "anchor"),
        ("a: |\n  txt\n", "块标量"),
        ('a: "unterminated\n', "引号"),
        ("a: 1\na: 2\n", "重复键"),
    ],
)
def test_rejected_constructs(bad: str, frag: str) -> None:
    with pytest.raises(YamlishError, match=frag):
        loads(bad)


def test_top_level_scalar() -> None:
    assert loads("just a string\n") == "just a string"


def test_empty_doc() -> None:
    assert loads("\n# only comments\n") is None
