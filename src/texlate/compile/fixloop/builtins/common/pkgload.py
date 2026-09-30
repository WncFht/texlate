r"""builtins.common.pkgload — ``\usepackage``/``\RequirePackage`` 装载命令骨架 (common 拆分)。

命名组单源 (自 builtins.pkgload 归位 —— 旧拼在同骨架上组位逐处漂移,
names 位 g5/g3/g2 不等; 命名组替数字位收口) + 装载点剥除
``_drop_pkg_loads``/名单元素面 ``_load_elems``。
"""

from __future__ import annotations

import re

__all__ = [
    "_LOAD_SITE_RE",
    "_PKG_LOAD_HEAD_SRC",
    "_PKG_LOAD_RE",
    "_PKG_LOAD_SRC",
    "_USE_RE",
    "_drop_pkg_loads",
    "_load_elems",
    "_pkg_list_re",
    "re",
]

#: 装载命令规范骨架 (命名组): ``head``=名单外全部前缀，``cmd``=命令名，
#: ``opts``=整 ``[..]`` 段 (含括号), ``opts_inner``=选项本体，
#: ``names``=花括号名单。opts 字符集 ``[^\]]`` 允跨行 —— TeX 选项表
#: 换行合法 (旧 ``[^\]\n]`` 各拼形的严格超集)。
_PKG_LOAD_HEAD_SRC = (
    r"(?P<head>\\(?P<cmd>usepackage|RequirePackage)\s*"
    r"(?P<opts>\[(?P<opts_inner>[^\]]*)\])?\s*)"
)
_PKG_LOAD_SRC = _PKG_LOAD_HEAD_SRC + r"\{(?P<names>[^}]*)\}"
_PKG_LOAD_RE = re.compile(_PKG_LOAD_SRC)


def _pkg_list_re(pkg: str) -> re.Pattern[str]:
    r"""名单内含 ``pkg`` 的装载点变体 —— ``names`` 拆 ``before``/``after`` 双组。

    ``\b<pkg>\b`` 界只挡字母续名 (``{physics-tools}`` 这类连字符兄弟名
    的误中由调用方元素级判定滤掉)。``builtins.pkgload._PHYS_LOAD_RE``
    等同形名单变体的单源。
    """
    return re.compile(
        _PKG_LOAD_HEAD_SRC
        + rf"\{{(?P<before>[^}}]*)\b{re.escape(pkg)}\b(?P<after>[^}}]*)\}}"
    )


#: ``_PKG_LOAD_SRC`` + ``^(\s*)`` 行首锚变体 —— 锚必须留：
#: option_clash_merge 靠它防行内装载点误并 (``\if..\RequirePackage``
#: 同行形态不收)。组面 = 命名组 (head/cmd/opts/opts_inner/names) +
#: 组 1 行首空白。
_USE_RE = re.compile(rf"^(\s*){_PKG_LOAD_SRC}", re.MULTILINE)


def _drop_pkg_loads(t: str, pkg: str) -> tuple[str, int]:
    r"""剥 ``\usepackage``/``\RequirePackage`` 对 pkg 的装载 → (新文本, 摘除数)。

    独载: 行首锚 (前缀全空白) → 整行注释; 行内嵌入 → 置空
    (注释替换会误吃同行尾 token)。名单成员按逗号列**元素**判
    (``_load_elems``) —— 旧的 ``\b<pkg>\b`` 子串形把 ``{physics-tools}``
    的连字符兄弟名撕残 (``-tools`` 残留); 保留站点沿用原前缀文本
    (不再顺手归并 cmd↔opts↔``{`` 间空白)。
    """
    want = pkg.lower()
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        if want not in _load_elems(m):
            return m.group(0)
        n += 1
        keep = [
            p.strip()
            for p in m.group(1).split(",")
            if p.strip() and p.strip().lower() != want
        ]
        if keep:
            return f"{m.group(0)[: m.start(1) - m.start(0)]}{','.join(keep)}}}"
        ls = m.string.rfind("\n", 0, m.start()) + 1
        if m.string[ls : m.start()].strip():
            return ""
        return "% fixloop: stripped " + m.group(0).strip()

    return _LOAD_SITE_RE.sub(_sub, t), n


#: ``\usepackage``/``\RequirePackage`` 装载点 —— group(1)=花括内逗号列
#: 元素串 (``[opts]`` 跳过)。无行首锚：``\if..\RequirePackage..\fi``
#: 单行条件形也收，前置在 token 前序位恒正确。
_LOAD_SITE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}"
)


def _load_elems(m: re.Match[str]) -> set[str]:
    r"""``_LOAD_SITE_RE`` 命中的花括逗号列 → 小写去空白包名集。"""
    return {e.strip().lower() for e in m.group(1).split(",") if e.strip()}
