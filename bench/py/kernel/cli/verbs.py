"""kernel.cli.verbs — 分析动词注册/分派叶 (kernel.cli 拆分叶).

§5.2 分析动词自注册机制：``verbs.REGISTRY`` 是纯数据表 (verb 名 →
(叶名，help)), parser 与 ``_DISPATCH`` 读同一表——新动词文件落地即
上线，cli 本体零改。``_lazy_verb`` 惰性 ``importlib.import_module(
"verbs.<leaf>")`` (连字符动词共享模块叶); 未安装动词统一
``_cmd_verb`` 报 "verb not installed" (exit 2)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import importlib

from kernel.cli.common import EXIT_REFUSED, _err

_NOT_IMPLEMENTED = "not yet implemented — index-reading analysis verb lands with the §5.2 rewrite queue"


def _lazy_verb(name: str):
    """Import the module REGISTRY maps ``name`` to; (module, None) or
    (None, err). Hyphenated verb names share a module leaf."""
    leaf = _verb_registry().get(name, (name,))[0]
    try:
        return importlib.import_module(f"verbs.{leaf}"), None
    except Exception as exc:
        return None, exc


def _verb_registry() -> dict:
    """verbs.REGISTRY — pure-data import, safe at parser-build time."""
    try:
        return dict(importlib.import_module("verbs").REGISTRY)
    except Exception:
        return {}


def _cmd_verb(args) -> int:
    """Generic verb dispatch: lazy-load verbs.<cmd> and call main(args)."""
    mod, err = _lazy_verb(args.cmd)
    if mod is None or not hasattr(mod, "main"):
        _err(f"{args.cmd}: verb not installed ({err or 'no main'})")
        return EXIT_REFUSED
    return int(mod.main(args) or 0)


def _cmd_not_implemented(args) -> int:
    _err(f"{args.cmd}: {_NOT_IMPLEMENTED}")
    return EXIT_REFUSED
