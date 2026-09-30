r"""``\pacs`` polyfill —— ``\AtBeginDocument`` 参数内 ``#`` 单写约定钉。

实证 (pacsdiag 车道, 2026-09-18): ``\AtBeginDocument{\def\pacs##1{...}}`` 在
现代内核 (toks 存储链) 逐字留下 ``##`` —— hook 执行时 ``\def\pacs##`` 炸
"Parameters must be numbered consecutively" ×2, 残留 ``\pacs`` 成 ``#1``-
定界宏, 调用点扫参越过花括号撞 \par → "Paragraph ended before \pacs was
complete" (loop2/rt1/guardsmoke 7 格三连签实证, 错误行=调用后首个空行)。

当前钉面 (routeclean 2026-09-20 后, shim_map 的 revtex.cls 槽已删):
vendored ``vendor/shims/revtex.cls`` stub 覆盖 ``\pacs`` 且全件 ``##``-free;
全部 shim_map body 的 ``\AtBeginDocument`` 参数顶层扫 ``##`` (嵌套 def
体内的 ``##`` 合法, 不计); 内建 emit ``_builtins_shim._REVTEX209_POLYFILL``
单 ``#`` 形与 vendored 替身钉语义平 (两链机制已异构: def-in-hook vs
外 def+内 let)。
"""

from pathlib import Path

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop._builtins_shim import _REVTEX209_POLYFILL
from texlate.latex.chars import match_brace


def _shim_map() -> dict[str, dict[str, str]]:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules["legacy_pkg_shim"].action["params"]["shim_map"]


def _at_begin_doc_args(body: str) -> list[str]:
    r"""抽出每个 ``\AtBeginDocument{...}`` 的参数文本 (``match_brace`` 配平)。"""
    args = []
    idx = 0
    tag = "\\AtBeginDocument{"
    while True:
        i = body.find(tag, idx)
        if i < 0:
            return args
        e = match_brace(body, i + len(tag) - 1)
        if e is None:  # 括号未闭合 → 无顶层可言, 停扫
            return args
        args.append(body[i + len(tag) : e - 1])
        idx = e


def _top_level_double_hash(arg: str) -> str | None:
    r"""``\AtBeginDocument`` 参数顶层 (未入任何 ``{}``) 的 ``##`` —— 必炸。

    ``\X`` 转义跳两字符、``%`` 注释跳至行尾——与 ``match_brace`` 同口径。
    """
    depth = 0
    i = 0
    while i < len(arg):
        c = arg[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            j = arg.find("\n", i)
            i = len(arg) if j < 0 else j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "#" and arg[i : i + 2] == "##" and depth == 0:
            return arg[max(0, i - 30) : i + 30]
        i += 1
    return None


_REVTEX_STUB = (
    Path(__file__).resolve().parents[2]
    / "src/texlate/compile/fixloop/vendor/shims/revtex.cls"
)


def test_revtex_cls_pacs_single_hash() -> None:
    r"""``revtex.cls`` stub: ``\pacs`` 覆盖在场且全件无 ``##`` 定界宏陷阱。
    routeclean 2026-09-20: shim_map 槽删 → vendored shims 实件钉。"""
    body = _REVTEX_STUB.read_text(encoding="utf-8")
    assert "\\pacs" in body
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
    r"""两条 emit 链同义钉: 内建 ``_REVTEX209_POLYFILL`` 单 ``#`` 形钉住,
    vendored revtex.cls 替身 (routeclean 后服务物) ``\pacs`` 覆盖且无
    ``##`` ——两链机制已异构 (def-in-hook vs 外 def+内 let), 钉语义面。"""
    builtin_line = next(ln for ln in _REVTEX209_POLYFILL.splitlines() if "\\pacs" in ln)
    assert "##" not in builtin_line
    body = _REVTEX_STUB.read_text(encoding="utf-8")
    assert "\\pacs" in body
    assert "##" not in body
