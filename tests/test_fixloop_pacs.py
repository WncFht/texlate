r"""``\pacs`` polyfill —— ``\AtBeginDocument`` 参数内 ``#`` 单写约定钉。

实证 (lane-pacsdiag, 2026-09-18): ``\AtBeginDocument{\def\pacs##1{...}}`` 在
现代内核 (toks 存储链) 逐字留下 ``##`` —— hook 执行时 ``\def\pacs##`` 炸
"Parameters must be numbered consecutively" ×2, 残留 ``\pacs`` 成 ``#1``-
定界宏, 调用点扫参越过花括号撞 \par → "Paragraph ended before \pacs was
complete" (loop2/rt1/guardsmoke 7 格三连签实证, 错误行=调用后首个空行)。
内建 emit ``_builtins_shim._REVTEX209_POLYFILL`` 已修单 ``#`` 并注释声明与
``shim_map.revtex.cls`` 同义——本测试钉住 yaml 侧同步形态, 并对全部
shim_map body 扫 ``\AtBeginDocument`` 顶层 ``##`` (嵌套 def 体内的 ``##``
合法, 不计)。
"""

import re

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop._builtins_shim import _REVTEX209_POLYFILL

_PACS_LINE = "\\AtBeginDocument{\\def\\pacs#1{\\par\\noindent\\textbf{PACS:} #1\\par}}"


def _shim_map() -> dict[str, dict[str, str]]:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules["legacy_pkg_shim"].action["params"]["shim_map"]


def _at_begin_doc_args(body: str) -> list[str]:
    r"""抽出每个 ``\AtBeginDocument{...}`` 的参数文本 (花括号配平)。"""
    args = []
    idx = 0
    tag = "\\AtBeginDocument{"
    while True:
        i = body.find(tag, idx)
        if i < 0:
            return args
        j = i + len(tag)
        depth = 1
        while j < len(body) and depth:
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
            j += 1
        args.append(body[i + len(tag) : j - 1])
        idx = j


def _top_level_double_hash(arg: str) -> str | None:
    r"""``\AtBeginDocument`` 参数顶层 (未入任何 ``{}``) 的 ``##`` —— 必炸。"""
    depth = 0
    i = 0
    while i < len(arg):
        c = arg[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "#" and arg[i : i + 2] == "##" and depth == 0:
            return arg[max(0, i - 30) : i + 30]
        i += 1
    return None


def test_revtex_cls_pacs_single_hash() -> None:
    r"""``revtex.cls`` stub body: ``\pacs`` polyfill 单 ``#`` 形, 无 ``##``。"""
    body = _shim_map()["revtex.cls"]["body"]
    assert _PACS_LINE in body
    assert "##" not in body


def test_shim_map_no_top_level_double_hash_in_hooks() -> None:
    r"""全 shim_map body: ``\AtBeginDocument`` 参数顶层禁 ``##`` (定界宏陷阱)。"""
    offenders = []
    for fname, spec in _shim_map().items():
        body = spec.get("body") or ""
        for arg in _at_begin_doc_args(body):
            hit = _top_level_double_hash(arg)
            if hit is not None:
                offenders.append(f"{fname}: ...{hit}...")
    assert not offenders, "\n".join(offenders)


def test_polyfill_emits_agree_on_pacs() -> None:
    r"""两条 emit 链同义钉: 内建 ``_REVTEX209_POLYFILL`` 与 yaml stub body
    的 ``\pacs`` 行逐字一致 (注释声明同义, 漂移即本测试拦)。"""
    builtin_line = next(ln for ln in _REVTEX209_POLYFILL.splitlines() if "\\pacs" in ln)
    yaml_line = next(
        ln.strip()
        for ln in _shim_map()["revtex.cls"]["body"].splitlines()
        if re.search(r"\\AtBeginDocument.*\\pacs", ln)
    )
    assert builtin_line.strip() == yaml_line
