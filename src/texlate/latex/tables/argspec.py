r"""``latex.tables.argspec`` — ``data/argspec.json`` 装载与查表（``tables`` god-file 机械拆分叶）。

``argspec_tables`` 懒加载 + 进程级缓存 → ``(macros, envs)`` 两张
``name → ArgspecEntry`` 表；``argspec_lookup``/``argspec_lookup_env``
宏/env 两路查表——均不按包门控（``pkgs`` 只收本文件包名，工程按
``\\input`` 拆开后包门必假阴，门控已退役）。
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from texlate.latex.model import ArgspecEntry

# ---------------------------------------------------------------- argspec.json


@cache
def argspec_tables() -> tuple[dict[str, ArgspecEntry], dict[str, ArgspecEntry]]:
    r"""``data/argspec.json`` → ``(macros, envs)`` 两张 ``name → ArgspecEntry`` 表。

    懒加载 + 进程级缓存（~500KB JSON 只在首个未知 cs 命中时读一次）。
    条目照抄 JSON 字段；``guessed`` = source 含 ``guessed-signature``
    （族规则推断签名，审计可回滚）；``also_in`` 收跨包重名登记。

    包门史话（两 ``argspec_lookup*`` 共用前提）：查表曾按
    ``ScanState.pkgs`` 门控，但 ``pkgs`` 只收**本文件**
    ``\\usepackage``/``\\documentclass``——工程按 ``\\input`` 拆开后
    体文件查不到导言区包名，包门必假阴 → 门控已退役，两侧查表
    均不按包过滤（``pkgs`` 收集端已拆，``ScanState.pkgs`` 只剩
    ClassVar 空集保读口形态——外部测试钉死）。
    """
    raw = resources.files("texlate.latex").joinpath("data/argspec.json")
    data = json.loads(raw.read_text(encoding="utf-8"))
    macros: dict[str, ArgspecEntry] = {}
    envs: dict[str, ArgspecEntry] = {}
    for key, dst in (("macros", macros), ("environments", envs)):
        for name, e in data.get(key, {}).items():
            dst[name] = ArgspecEntry(
                name=name,
                package=e.get("package", ""),
                signature=e.get("signature", ""),
                arg_roles=tuple(e.get("arg_roles", ())),
                policy=e.get("policy", "protect"),
                body_role=e.get("body_role", ""),
                guessed="guessed-signature" in e.get("source", ()),
                also_in=frozenset(e.get("also_in", "").split()),
            )
    return macros, envs


def argspec_lookup(name: str, _pkgs: set[str]) -> ArgspecEntry | None:
    r"""未知控制序列查表——不按包门控（``argspec_lookup_env`` 同规）。

    门控退役史话见 ``argspec_tables``。用户 ``\\newcommand``/``\\def``
    撞名由调用方先短路：主流 ``_handle_unknown_cs`` 仅 ``m is None``
    才查表（``_resolve_macro``
    命中 gullet 宏表即跳过；可展开用户宏 gullet 先行吃掉到不了分段
    器），cite/ref 词族按名先行、签名只决定保护参目。不吃签名会把
    key 参漏成散文送译——``\\crefrange{a}{b}`` 第二参、``\\joref``
    尾四组实证泄漏 → cleveref ``\\cref@resetstack`` 递归炸栈
    （2105.00111）。``text``/``opt-text`` 角色参回吐主流不受影响；
    最坏形态 = 未加载包同名 cs 按签名多吞若干组（有界少译，无腐蚀
    面）。``_pkgs`` 死参——旧门控签名留位（调用面仍传
    ``state.pkgs``），不读。
    """
    return argspec_tables()[0].get(name)


def argspec_lookup_env(name: str, _pkgs: set[str]) -> ArgspecEntry | None:
    r"""``argspec_lookup`` 的环境侧同名物（``\\begin{X}`` 的 X）——不按包门控。

    ``\\begin{X}`` 出现本身即工程已供 X 的证据（X 无内核/恒激活族
    提供方；用户 ``\\newenvironment`` 撞名由调用方 ``_argspec_env``
    的 ``reg`` 先短路，到不了此层）。不吃签名会把 env-name/key 参
    漏成散文送译——thmtools ``restatable`` 实证：
    ``\\begin{restatable}{theorem}{main}`` 的两参进 chunk 被译成
    ``{这是译文}{这是译文}`` → cleveref ``\\cref@resetstack`` 递归炸栈
    （2105.00111）。``text``/``opt-text`` 角色参回吐主流不受影响；
    最坏形态 = 未定义/撞名 env 按签名多吞若干组（有界少译，无腐蚀
    面）。``_pkgs`` 死参——旧门控签名留位（调用面仍传
    ``state.pkgs``），不读。
    """
    return argspec_tables()[1].get(name)
