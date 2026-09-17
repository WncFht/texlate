"""rules.yaml 装载薄封装：PyYAML safe_load + 文件路径上下文错误。

历史注记：早期为保持 venv 零依赖内置过 YAML 子集解析器；PyYAML 成为正式
依赖后退役，本模块只剩统一错误类型与入口。

2026-09-17 起规则库物理拆为 ``rules/`` 目录多文件（单文件 4800+ 行不可
持续）：``load_yaml`` 对目录按文件名序逐件装载后做顶层段合并——list 段
(rules/taxonomy/warnings) 依文件序拼接、map 段 (meta/filemap/...) 递归
合并、标量同值幂等/异值即冲突报错。序敏感段 (taxonomy 首命中、warnings
镜像序) 各自单文件承载，文件内序即语义。
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


def _merge_into(dst: dict[str, Any], src: Any, *, name: str) -> None:  # noqa: ANN401
    """把单件 yaml 顶层 map 并入 dst：list 拼接、map 递归、标量冲突报错。"""
    if src is None:
        return
    if not isinstance(src, dict):
        msg = f"{name}: 顶层必须是 map"
        raise YamlishError(msg)
    for key, val in src.items():
        old = dst.get(key)
        if old is None:
            dst[key] = val
        elif isinstance(old, list) and isinstance(val, list):
            old.extend(val)
        elif isinstance(old, dict) and isinstance(val, dict):
            _merge_maps(old, val, name=name, trail=key)
        elif old != val:
            msg = f"{name}: 顶层键 {key!r} 与已有分片冲突 ({old!r} vs {val!r})"
            raise YamlishError(msg)


def _merge_maps(
    dst: dict[str, Any], src: dict[str, Any], *, name: str, trail: str
) -> None:
    """Map 段递归合并（filemap.overrides 等嵌套层）；叶子冲突报错。"""
    for key, val in src.items():
        old = dst.get(key)
        if old is None:
            dst[key] = val
        elif isinstance(old, dict) and isinstance(val, dict):
            _merge_maps(old, val, name=name, trail=f"{trail}.{key}")
        elif isinstance(old, list) and isinstance(val, list):
            old.extend(val)
        elif old != val:
            msg = f"{name}: 键 {trail}.{key} 与已有分片冲突 ({old!r} vs {val!r})"
            raise YamlishError(msg)


def load_yaml(path: Path) -> Any:  # noqa: ANN401  # yaml 装载天然 Any 返回
    """加载 yaml 为纯数据；``path`` 是目录时合并其下全部 ``*.yaml``。

    目录分支按文件名排序逐件装载（``00-base.yaml`` 这类数字前缀即声明
    序），顶层段按上段所述规则合并；文件分支行为不变——现存单文件调用
    方零感知。
    """
    if not path.exists():
        msg = f"{path}: no such file"
        raise YamlishError(msg)
    if path.is_dir():
        parts = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix in {".yaml", ".yml"}
        )
        if not parts:
            msg = f"{path}: 目录内无 *.yaml"
            raise YamlishError(msg)
        merged: dict[str, Any] = {}
        for p in parts:
            _merge_into(
                merged, loads(p.read_text(encoding="utf-8"), name=str(p)), name=str(p)
            )
        return merged
    return loads(path.read_text(encoding="utf-8"), name=str(path))
