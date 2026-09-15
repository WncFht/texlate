"""rules.yaml 装载薄封装：PyYAML safe_load + 文件路径上下文错误。

历史注记：早期为保持 venv 零依赖内置过 YAML 子集解析器；PyYAML 成为正式
依赖后退役，本模块只剩统一错误类型与入口。
"""

from pathlib import Path
from typing import Any

import yaml


class YamlishError(ValueError):
    """yaml 装载/解析失败的统一错误类型（带文件路径上下文）。"""


def loads(text: str, *, name: str = "<string>") -> Any:  # noqa: ANN401  # yaml 装载天然 Any 返回
    """解析 yaml 文本，语法错误转 YamlishError 并带出来源名。"""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        msg = f"{name}: invalid yaml: {e}"
        raise YamlishError(msg) from e


def load_yaml(path: Path) -> Any:  # noqa: ANN401  # yaml 装载天然 Any 返回
    """加载 yaml 文件为纯数据。"""
    if not path.exists():
        msg = f"{path}: no such file"
        raise YamlishError(msg)
    return loads(path.read_text(encoding="utf-8"), name=str(path))
