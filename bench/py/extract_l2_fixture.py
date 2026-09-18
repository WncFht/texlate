#!/usr/bin/env python3
r"""extract_l2_fixture — gitignored work 目录真 .log → tests/fixtures/logs/ 入库 fixture。

管线（spec: bench/results/scout-l2fixtures-2026-09-17/report.md §3）：

1. ``--strip-prefix PFX[=REPL]`` 字面替换脱敏（默认 REPL=``./``，把工作根前缀
   归一为工程相对形态；系统 texmf 绝对路径不动——``_SYS_TREE_RX`` 归因承重）。
2. 裁切：只删**无括弧行**（字体/宏转储大头）。保 line 0（engine 头）、``**`` 行、
   全部含 ``(``/``)`` 行（栈重放硬约束——``)`` 行决定 eof_file 归因）、错误锚
   行 ±8 ctx（``^!`` + ``file:line:`` 含 ``==>`` 复述行）、warning 形态行
   （by_class 计数保真）、裸 ``==>`` 行、tail 30。删段以
   ``[... elided N lines ...]`` 标记（无括弧、不命中任何错误/warning 形态）。
   ``--no-cut`` 原样件直写；``--first-error-only`` 只锚首错（大文件重裁用，
   n_errors 按裁后实算入 manifest）。
3. 写 ``--outdir/NAME.log``；产物含 ``/home/`` 或 ``/Users/`` 即 fail（硬门槛）。
4. 对裁后文本跑 ``parse_log_text`` + fixloop taxonomy 生成 manifest 行，
   ``--manifest`` upsert（断言值永远以裁后件为准，行号不漂移）。
5. ``--verify`` 对拍：逐错误重放文件栈 + last-pop 与 strip 后源件一致，
   且 L2 verdict 关键字段全等（first-error-only 模式豁免 n_errors/errors）。

跑法：``uv run python bench/py/extract_l2_fixture.py SRC --name NAME \
    [--strip-prefix PFX[=REPL]]... [--no-cut|--first-error-only] \
    [--verify] [--manifest PATH] [--notes TEXT] [--project-root-for-attribution DIR]``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.logparse import parse_text as fl_parse_text
from texlate.texlog import (
    CTX_LINES,
    ERR_BANG_RE,
    ERR_FILELINE_ROW_RE,
    TAIL_LINES,
    file_stack_at,
)
from texlate.validate import l2

_CTX = CTX_LINES  # 错误锚行两侧保留行数
_TAIL = TAIL_LINES  # 尾部保留行数

_FATAL_BARE_RX = re.compile(r"^\s*==>")


def _err_anchor(ln: str) -> bool:
    """错误锚行：``^!`` 或 ``file:line:`` 形态（含 ``==>``/Warning 非错行——
    裁切保真口径宽于计数口径，剔除证据行本身也必须留下）。"""
    return bool(ERR_BANG_RE.match(ln) or ERR_FILELINE_ROW_RE.match(ln))


def _keep_set(lines: list[str], *, first_error_only: bool) -> set[int]:
    n = len(lines)
    keep = {0}  # engine 头 / tectonic ** 首行
    err_idx = [i for i, ln in enumerate(lines) if _err_anchor(ln)]
    horizon: int | None = None
    if first_error_only:
        err_idx = err_idx[:1]
        if err_idx:
            # 首错 ctx 之后到 tail 之前整段可裁——首错栈重放只依赖其前的括弧行
            horizon = err_idx[0] + _CTX
    for i in err_idx:
        keep.update(range(max(0, i - _CTX), min(n, i + _CTX + 1)))
    for i, ln in enumerate(lines):
        if horizon is not None and i > horizon:
            break
        if (
            "(" in ln
            or ")" in ln
            or ln.startswith("**")
            or _FATAL_BARE_RX.match(ln)
            or l2._ANY_WARNING_RX.search(ln)
            or l2._MARKERLESS_WARN_RX.search(ln)
        ):
            keep.add(i)
    keep.update(range(max(0, n - _TAIL), n))
    return keep


def _elide(lines: list[str], keep: set[int]) -> tuple[list[str], list[int | None]]:
    """→ (裁后行, src_map)：src_map[j] = 裁后行 j 对应的源行号（marker 行 None）。"""
    out: list[str] = []
    src_map: list[int | None] = []
    i = 0
    while i < len(lines):
        if i in keep:
            out.append(lines[i])
            src_map.append(i)
            i += 1
            continue
        j = i
        while j < len(lines) and j not in keep:
            j += 1
        out.append(f"[... elided {j - i} lines ...]")
        src_map.append(None)
        i = j
    return out, src_map


def _last_named_pop(lines: list[str], stop: int) -> str | None:
    popped: list[str | None] = []
    file_stack_at(lines, stop, popped)
    return next((t for t in reversed(popped) if t is not None), None)


def _verify(
    src_lines: list[str],
    cut_lines: list[str],
    src_map: list[int | None],
    *,
    first_error_only: bool,
) -> list[str]:
    """裁切对拍：逐保留错误行重放 named-stack + last-pop 与源一致；
    L2 verdict 关键字段全等。返回失配清单（空=过）。"""
    fails: list[str] = []
    cut_pos = {si: j for j, si in enumerate(src_map) if si is not None}
    # 自保：被删行必无括弧（构造如此，防御回归；first-error-only 的
    # horizon 后整段裁切是声明行为，括弧行亦删——首错重放不受影响）
    if not first_error_only:
        fails.extend(
            f"paren line elided: src:{si + 1}"
            for si in range(len(src_lines))
            if si not in cut_pos and ("(" in src_lines[si] or ")" in src_lines[si])
        )
    for si, j in cut_pos.items():
        if l2._match_error_line(src_lines[si]) is None:
            continue
        s_stack = file_stack_at(src_lines, si)
        c_stack = file_stack_at(cut_lines, j)
        if s_stack != c_stack:
            fails.append(f"stack@src:{si + 1}: {s_stack} != {c_stack}")
        s_pop = _last_named_pop(src_lines, si)
        c_pop = _last_named_pop(cut_lines, j)
        if s_pop != c_pop:
            fails.append(f"last_pop@src:{si + 1}: {s_pop} != {c_pop}")

    vs = l2.parse_log_text("\n".join(src_lines) + "\n")
    vc = l2.parse_log_text("\n".join(cut_lines) + "\n")

    def _cmp(name: str, a: object, b: object) -> None:
        if a != b:
            fails.append(f"{name}: {a!r} != {b!r}")

    _cmp("engine", vs.engine, vc.engine)
    _cmp("log_missing", vs.log_missing, vc.log_missing)
    if not first_error_only:
        _cmp("n_errors", vs.n_errors, vc.n_errors)

        def _err_sig(e: l2.LogError) -> tuple[object, ...]:
            return (e.head, e.tex_file, e.tex_line, e.eof_file, e.file_stack)

        _cmp(
            "errors",
            [_err_sig(e) for e in vs.errors],
            [_err_sig(e) for e in vc.errors],
        )
    for attr in ("head", "tex_file", "tex_line", "eof_file", "file_stack"):
        _cmp(
            f"first_error.{attr}",
            getattr(vs.first_error, attr, None),
            getattr(vc.first_error, attr, None),
        )
    if not first_error_only:
        for attr in (
            "total",
            "by_class",
            "samples",
            "redlines",
            "sys_hits",
            "cjk_missing",
        ):
            _cmp(
                f"warnings.{attr}",
                getattr(vs.warnings, attr),
                getattr(vc.warnings, attr),
            )
    _cmp("tail", vs.tail, vc.tail)
    return fails


def _manifest_row(
    name: str,
    src: Path,
    text: str,
    *,
    project_root: Path | None,
    notes: str,
) -> dict:
    """对裁后文本实算 manifest 断言行（断言值以产物件为准）。"""
    v = l2.parse_log_text(text, project_root=project_root)
    fe = v.first_error
    rs = load_ruleset()
    rep = fl_parse_text(text, rs.warn_patterns)
    cat, pay = rs.taxonomy.classify(rep)
    return {
        "file": name,
        "source": str(src.relative_to(REPO)) if src.is_relative_to(REPO) else str(src),
        "engine": v.engine,
        "n_errors": v.n_errors,
        "ok": v.ok,
        "first_error": None
        if fe is None
        else {
            "head_contains": fe.head,
            "tex_file": fe.tex_file,
            "tex_line": fe.tex_line,
            "eof_file": fe.eof_file,
            "stack_suffix": fe.file_stack[-1] if fe.file_stack else None,
        },
        "warnings": {
            "by_class_min": dict(sorted(v.warnings.by_class.items())),
            "redline_contains": sorted(
                {r.split(":", 1)[0] for r in v.warnings.redlines}
            ),
            "sys_hits_contains": list(v.warnings.sys_hits),
            "cjk_missing_min": v.warnings.cjk_missing,
        },
        "tail_last": v.tail[-1] if v.tail else None,
        "fixloop": {"n_bang": rep.n_bang, "category": cat, "payload": pay},
        "project_root": str(project_root) if project_root else None,
        "notes": notes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument(
        "--strip-prefix",
        action="append",
        default=[],
        metavar="PFX[=REPL]",
        help="字面前缀替换（可重复）；REPL 缺省 ./",
    )
    ap.add_argument("--no-cut", action="store_true", help="原样入库（零裁切）")
    ap.add_argument(
        "--first-error-only",
        action="store_true",
        help="只锚首错 ±ctx（大文件重裁；n_errors 按裁后实算）",
    )
    ap.add_argument("--verify", action="store_true", help="裁后重放栈对拍源件")
    ap.add_argument(
        "--outdir",
        type=Path,
        default=REPO / "tests" / "fixtures" / "logs",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=REPO / "tests" / "fixtures" / "logs" / "manifest.json",
    )
    ap.add_argument("--no-manifest", action="store_true")
    ap.add_argument("--notes", default="")
    ap.add_argument("--project-root-for-attribution", type=Path, default=None)
    args = ap.parse_args()

    text = args.src.read_text(encoding="utf-8", errors="replace")
    for spec in args.strip_prefix:
        pfx, _, repl = spec.partition("=")
        text = text.replace(pfx, repl or "./")

    lines = text.splitlines()
    if args.no_cut:
        cut_lines, src_map = lines, list(range(len(lines)))
    else:
        cut_lines, src_map = _elide(
            lines, _keep_set(lines, first_error_only=args.first_error_only)
        )
    out_text = "\n".join(cut_lines) + "\n"

    if "/home/" in out_text or "/Users/" in out_text:
        sys.exit("FAIL: 产物仍含 /home/ 或 /Users/ 私路径——补 --strip-prefix")

    if args.verify:
        fails = _verify(
            lines, cut_lines, src_map, first_error_only=args.first_error_only
        )
        if fails:
            for f in fails:
                print(f"  verify: {f}", file=sys.stderr)
            sys.exit(f"FAIL: verify {len(fails)} 处失配")

    name = args.name if args.name.endswith(".log") else f"{args.name}.log"
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / name).write_text(out_text, encoding="utf-8")

    row = _manifest_row(
        name,
        args.src,
        out_text,
        project_root=args.project_root_for_attribution,
        notes=args.notes,
    )
    print(json.dumps(row, ensure_ascii=False))

    if not args.no_manifest:
        rows = []
        if args.manifest.exists():
            rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        rows = [r for r in rows if r["file"] != name]
        rows.append(row)
        rows.sort(key=lambda r: r["file"])
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    n_kept = sum(1 for s in src_map if s is not None)
    print(
        f"wrote {args.outdir / name}: {len(out_text)}B "
        f"({len(lines)}ln → {n_kept}ln kept, {len(lines) - n_kept} elided)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
