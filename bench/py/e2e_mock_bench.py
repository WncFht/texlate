#!/usr/bin/env python3
r"""e2e mock bench — corpus39 全量 mock 翻译 → ctex 注入 → 双引擎编译基线（M0 出口判据）。

每工程条件（attribution 设计来自 tmp/exp/e2e/pipeline.py）:
  base-xel : 原样复制 → xelatex（zh 失败时区分"原文就挂"vs"管线引入"）
  pipe-xel : normalize_project → mock-A 翻译 → prepare_chinese(ctex) → xelatex → judge
  pipe-tec : 同上 → tectonic
  base-tec : 原样复制 → tectonic（**仅当 pipe-tec 非 clean 时补跑**，归因用）

路由先行：`route_project`（\documentstyle → reject；仍跑 base-xel 实证拒绝正确性）。
mock-A 忠实译：散文段 → 固定中文串，[[X_n]] 占位符/控制字 token 原位保留；
校验器 per-chunk 占位符多重集 + 花括号配平（应零 fault——fault 即管线 bug 信号）。

miniscanner 补丁（BUG1–5）移植自 tmp/exp/e2e/pipeline.py，注释保留原 BUG 编号。

用法:
  python3 bench/py/e2e_mock_bench.py [--only SUBSTR] [--conditions base-xel,...]
      [--limit N] [--timeout SEC] [--tag NAME]
产出: bench/results/e2emock-<tag>-<date>/{results.json,matrix.md,summary.md}
工作区: bench/work_e2emock/<cond>/<safe_id>/（gitignored 重产物）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/Users/fanghaotian/src/texlate")
BENCH_PY = ROOT / "bench/py"
sys.path.insert(0, str(BENCH_PY))
sys.path.insert(0, str(ROOT / "src"))
import miniscanner

from texlate.compile.engine import (
    TectonicEngine,
    XelatexEngine,
    route_project,
)
from texlate.compile.inject import (
    InjectRejectError,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project

CORPUS = ROOT / "bench/corpus"
WORK = ROOT / "bench/work_e2emock"
RESULTS_DIR_DEFAULT = "e2emock-corpus39"

ZH = "这是一个用于验证编译的测试段落。"
PH_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")
CJK_RX = re.compile(r"(\\[a-zA-Z@]+\*?)([㐀-䶿一-鿿豈-﫿])")


# ------------------------------------------------------------ miniscanner 补丁
# 以下整体移植自 tmp/exp/e2e/pipeline.py（BUG1–5 注释为原编号）:


# BUG(miniscanner._args): 未知命令按 6 参贪婪读, 跨空白把后续 token 当单字符参数
# 吃掉 —— \subjclass{..}\n\n\begin{abstract} → CMD 吞 \begi, 尾 n{abstract} 落进
# chunk 被译走, 命令名被劈. identity 检查对此不可见 (两侧各自 verbatim).
# 补丁: 单 token 参数仅当 (a) 非 '\', (b) 与上一参数紧邻无空白. 复制方法体+2 处条件.
def _args_patched(self, tex, i, nargs, has_opt=False):
    pos = self._ws(tex, i)
    out: list[tuple[int, int, int, int]] = []
    if has_opt and pos < len(tex) and tex[pos] == "[":
        e = self._match_bracket(tex, pos)
        if e:
            out.append((pos + 1, e - 1, pos, e))
            pos = self._ws(tex, e)
    adjacent = True
    for _ in range(nargs):
        if pos < len(tex) and tex[pos] == "[":
            e = self._match_bracket(tex, pos)
            if e is None:
                break
            out.append((pos + 1, e - 1, pos, e))
            np_ = self._ws(tex, e)
            adjacent = np_ == e
            pos = np_
        elif pos < len(tex) and tex[pos] == "{":
            e = self._match_brace(tex, pos)
            if e is None:
                break
            out.append((pos + 1, e - 1, pos, e))
            np_ = self._ws(tex, e)
            adjacent = np_ == e
            pos = np_
        elif pos < len(tex) and tex[pos] not in " \t\n\\" and adjacent:
            out.append((pos, pos + 1, pos, pos + 1))
            pos += 1
        else:
            break
    return out, pos


miniscanner.Scanner._args = _args_patched


# BUG2(miniscanner.BOUNDARY): \vspace{2mm}/\item[label] 等边界命令只 emit 命令名,
# 强制 {arg}/[opt] 留在 run → 落进 chunk 被译走 → \vspace 读 CJK 当 dimen → 报错;
# \item 标签丢失 + \item这是 粘连. 补丁: 拦截 dispatch, 参数随边界命令一起进字面 piece.
# corpus39 冒烟新增 (BUG2b): preamble-only 文件无 preamble_end → \usepackage
# 在 body 区被扫到, [opt]{pkg} 落 chunk → 包名被译成中文. 文件参数族补齐.
ARG_BOUNDARY = {
    "vspace",
    "hspace",
    "cline",
    "cmidrule",
    "setcounter",
    "addtocounter",
    "setlength",
    "addtolength",
    "setstretch",
    "newcounter",
    "pagestyle",
    "thispagestyle",
    "pagenumbering",
    "newtheorem",
    "linebreak",
    "pagebreak",
    "nopagebreak",
}

# BUG2b (corpus39 冒烟实测): preamble-only 文件无 preamble_end → \usepackage
# 在 body 区被扫到, [opt]{pkg} 落 chunk → 包名被译成中文 (0906.4725 实测
# "File `这是….sty' not found"). 文件参数族同机制保护; nargs=1:
# 只读 [opt]+{file} 各一, 防 nargs=3 紧邻单 token 吞掉后续正文字符.
FILE_ARG_BOUNDARY = {
    "usepackage",
    "RequirePackage",
    "RequirePackageWithOptions",
    "documentclass",
    "documentstyle",
    "LoadClass",
    "LoadClassWithOptions",
    "bibliographystyle",
    "bibliography",
}

# BUG4: \vglue -10mm/\kern5pt 裸 dimen 原语 — 参数无括号, 数字落进 chunk 被译走.
DIM_BOUNDARY = {
    "vglue",
    "hglue",
    "vskip",
    "hskip",
    "kern",
    "raise",
    "lower",
    "moveleft",
    "moveright",
    "parindent",
    "parskip",
    "hsize",
    "vsize",
    "baselineskip",
    "lineskip",
    "topskip",
    "hangindent",
    "leftskip",
    "rightskip",
    "tabskip",
    "spaceskip",
    "xspaceskip",
}

# BUG5: \left( \right) \big[ 分隔符参数是单 token —— 未知命令路径只认 {/[,
# 分隔符裸落 chunk. 消费其后一个分隔符 token.
DELIM_BOUNDARY = {
    "left",
    "right",
    "middle",
    "big",
    "Big",
    "bigg",
    "Bigg",
    "bigl",
    "bigr",
    "Bigl",
    "Bigr",
    "biggl",
    "biggr",
    "Biggl",
    "Biggr",
    "bigm",
    "Bigm",
    "biggm",
    "Biggm",
}

_orig_dispatch = miniscanner.Scanner._dispatch_cmd


def _ws1(tex: str, i: int) -> int:
    """空白跳过但不跨段落: ' \t' + 至多一个 \n."""
    n = len(tex)
    while i < n and tex[i] in " \t":
        i += 1
    if i < n and tex[i] == "\n":
        i += 1
        while i < n and tex[i] in " \t":
            i += 1
    return i


def _dispatch_patched(self, tex, i, name, j, run, flush_run):
    n = len(tex)
    if name in ("input", "include"):
        # BUG3: \input file 裸文件名(无{}) — 原版只认 {..}, 裸形落进 run→chunk
        # → 文件名被翻译 → "I can't find file '这是…'". 补: 消费裸文件名 token.
        pos = self._ws(tex, j)
        if pos < n and tex[pos] == "{":
            return _orig_dispatch(self, tex, i, name, j, run, flush_run)
        m = re.match(r"[^\s{}%\\]+", tex[pos:])
        if m:
            fname = m.group(0)
            self.inputs.append((i, fname))
            flush_run()
            self._emit(tex[i : pos + m.end()])
            return pos + m.end()
        return _orig_dispatch(self, tex, i, name, j, run, flush_run)
    if name == "item":
        # 边界: 消费 *?[opt], 本体进字面 piece, 下一 run 强制成 chunk
        flush_run()
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        _a, end = self._args(tex, pos, 0, True)
        self._emit(tex[i:end])
        self._force_chunk = True
        return end
    if name in DIM_BOUNDARY:
        # [to|spread]?[=]?({dim}|bare-dim) → [[CMD]] 进 run (chunk 内亦免疫)
        m = re.match(r"\s*(?:to|spread)?\s*=?", tex[j:])
        pos = j + m.end()
        if pos < n and tex[pos] == "{":
            e = self._match_brace(tex, pos)
            if e:
                pos = e
        else:
            m2 = re.match(r"[-+0-9.]+[^\s{}%\\]*", tex[pos:])
            if m2:
                pos += m2.end()
        run.append(self._ph("CMD", tex[i:pos]))
        return pos
    if name in ARG_BOUNDARY or name in FILE_ARG_BOUNDARY:
        # 带参边界命令: 参数随本体 → [[CMD]] 进 run
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        nargs = 1 if name in FILE_ARG_BOUNDARY else 3
        _a, end = self._args(tex, pos, nargs, True)
        run.append(self._ph("CMD", tex[i:end]))
        return end
    if name == "\\":
        # 换行 \\[2mm]: 可选 dim 仅当内容像 dimen 才消费 (防吞 [see x] 文本)
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        pos = _ws1(tex, pos)
        if pos < n and tex[pos] == "[":
            e = self._match_bracket(tex, pos)
            if e and re.match(r"\s*[-+0-9.]", tex[pos + 1 : e - 1]):
                pos = e
        run.append(self._ph("CMD", tex[i:pos]))
        return pos
    if name in DELIM_BOUNDARY:
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        pos = _ws1(tex, pos)
        if pos < n and tex[pos] == "\\":
            _nm, pos = self._read_cmd_name(tex, pos)
        elif pos < n and tex[pos] not in " \t\n":
            pos += 1
        run.append(self._ph("CMD", tex[i:pos]))
        return pos
    return _orig_dispatch(self, tex, i, name, j, run, flush_run)


miniscanner.Scanner._dispatch_cmd = _dispatch_patched


def cjk_glue_fix(tex: str) -> str:
    r"""xeCJK 下 CJK catcode=11 → \item这是 粘连成未定义 cs. \cmd+CJK 间插空格恒安全."""
    return CJK_RX.sub(r"\1 \2", tex)


# ---------------------------------------------------------------- mock 翻译
# 占位符/控制字 token 原位保留, 散文段换成固定中文 —— 位置敏感的构造不能动:
#   \bibitem{key} 必须在其条目前面; \href 必须贴着 {url}; verbatim 参数里 % 是活的;
#   \left( \right) 分隔符是裸文本 —— 括号/竖线一律保留.
TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]|\\[a-zA-Z@]+\*?|\\.|[][(){}|]")


def mock_a(content: str) -> str:
    """忠实译: 每个非空散文段 → 固定中文串; [[X_n]] 与 \\cmd 原位不动."""
    out = []
    pos = 0
    for m in TOKEN_RX.finditer(content):
        seg = content[pos : m.start()]
        out.append(ZH if seg.strip() else seg)
        out.append(m.group(0))
        pos = m.end()
    tail = content[pos:]
    out.append(ZH if tail.strip() else tail)
    return "".join(out)


def validate_chunk(content: str, zh: str) -> list[str]:
    """v0 校验器雏形: 占位符多重集一致 + 非转义花括号配平."""
    faults = []
    if sorted(PH_RX.findall(content)) != sorted(PH_RX.findall(zh)):
        faults.append("ph_mismatch")
    body = PH_RX.sub("", zh)
    depth, i = 0, 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                faults.append("brace_unbalanced")
                break
        i += 1
    if depth != 0 and "brace_unbalanced" not in faults:
        faults.append("brace_unbalanced")
    return faults


def process_tex(txt: str) -> tuple[str, dict]:
    """扫一个文件 → (zh_text, stats). mock-A 忠实译 + 校验器."""
    res = miniscanner.parse_tex(txt)
    ident = miniscanner.reconstruct(res, None) == txt
    trans: dict[int, str] = {}
    n_ph_src = n_ph_zh = 0
    faults = []
    for c in res.chunks:
        zh = mock_a(c.content)
        trans[c.id] = zh
        n_ph_src += len(PH_RX.findall(c.content))
        n_ph_zh += len(PH_RX.findall(zh))
        f = validate_chunk(c.content, zh)
        if f:
            faults.append({"chunk": c.id, "faults": f})
    zh_tex = miniscanner.reconstruct(res, trans)
    zh_tex = cjk_glue_fix(zh_tex)
    leftover = len(PH_RX.findall(zh_tex))
    stats = {
        "chunks": len(res.chunks),
        "ph_src": n_ph_src,
        "ph_zh": n_ph_zh,
        "identity": ident,
        "leftover_ph": leftover,
        "faults": faults,
    }
    return zh_tex, stats


def mock_translate_tree(dst: Path) -> dict:
    """全部 .tex mock 翻译写回；返回 per-file stats + 汇总。"""
    fstats = {}
    for f in sorted(dst.rglob("*.tex")):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            fstats[str(f.relative_to(dst))] = {"read_error": str(e)}
            continue
        zh, st = process_tex(txt)
        st["non_utf8"] = "" in txt
        f.write_text(zh, encoding="utf-8")
        fstats[str(f.relative_to(dst))] = st
    return {
        "files": fstats,
        "n_files": len(fstats),
        "n_identity_fail": sum(
            1 for s in fstats.values() if s.get("identity") is False
        ),
        "n_fault_chunks": sum(len(s.get("faults", [])) for s in fstats.values()),
        "n_leftover_ph": sum(s.get("leftover_ph", 0) for s in fstats.values()),
    }


# ---------------------------------------------------------------- 条件执行
def _engine(name: str):
    # halt_on_error=False：best-effort 基线（对齐 compile_bench 方法论，
    # engine 默认 True 是 fixloop 首错语义——bench 要拿全量错误计数）
    if name == "xelatex":
        return XelatexEngine(halt_on_error=False)
    return TectonicEngine()


def _verdict_dict(v) -> dict:
    return {
        "status": v.status,
        "reasons": v.reasons,
        "notes": v.notes,
        "n_errors": v.n_errors,
        "category": v.category,
        "payload": v.payload,
        "cjk_chars": v.cjk_chars,
        "missing_chars": v.missing_chars,
        "warnings_hit": v.warnings_hit,
    }


def run_condition(
    cond: str, src: Path, sid: str, main_rel: str, timeout: float
) -> dict:
    """单条件：复制 → (pipe: normalize→mock→inject) → compile → judge。"""
    engine_name = "xelatex" if cond.endswith("xel") else "tectonic"
    dst = WORK / cond / sid
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    rec: dict = {"engine": engine_name}
    if cond.startswith("pipe"):
        rec["normalize"] = normalize_project(dst, engine_name, main_rel)
        rec["mock"] = mock_translate_tree(dst)
        try:
            rec["inject"] = prepare_chinese(dst, main_rel)
        except InjectRejectError as e:
            rec["verdict"] = {"status": "reject", "reasons": [e.reason]}
            return rec
    engine = _engine(engine_name)
    res = engine.compile(dst, main_rel, timeout=timeout, sandbox=True)
    v = judge(res, expect_cjk=cond.startswith("pipe"))
    rec["compile"] = {
        "ok": res.ok,
        "timed_out": res.timed_out,
        "seconds": round(res.seconds, 2),
        "passes": res.passes,
        "rc": res.rc,
        "pdf_bytes": res.pdf_bytes,
        "n_deps": len(res.deps) if res.deps else 0,
        "first_error": res.log.first_error,
    }
    rec["verdict"] = _verdict_dict(v)
    return rec


def list_projects() -> list[str]:
    """corpus39 叶目录：直接含 .tex 的顶层目，或 hep-th/math 下的二级目。"""
    out = []
    for p in sorted(CORPUS.iterdir()):
        if not p.is_dir():
            continue
        if any(p.glob("*.tex")):
            out.append(p.name)
        else:
            out.extend(
                f"{p.name}/{d.name}"
                for d in sorted(p.iterdir())
                if d.is_dir() and any(d.glob("*.tex"))
            )
    return out


def safe_id(rel: str) -> str:
    return rel.replace("/", "--")


def run_project(rel: str, conditions: list[str], timeout: float) -> dict:
    src = CORPUS / rel
    sid = safe_id(rel)
    rec: dict = {"id": rel}
    main_path = find_main_tex(src)
    if main_path is None:
        rec["error"] = "no main tex"
        return rec
    main_rel = main_path.relative_to(src).as_posix()
    rec["main"] = main_rel
    route = route_project(src)
    rec["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
    }
    for cond in conditions:
        if cond == "base-tec":
            continue  # 条件性补跑——pipe-tec 非 clean 时再跑
        rec[cond] = run_condition(cond, src, sid, main_rel, timeout)
    if "base-tec" in conditions:
        pt = rec.get("pipe-tec", {}).get("verdict", {}).get("status")
        if pt is not None and pt != "clean":
            rec["base-tec"] = run_condition("base-tec", src, sid, main_rel, timeout)
    return rec


# ---------------------------------------------------------------- 报告
def _status(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def write_reports(results: dict, out_dir: Path) -> None:
    conds = ["base-xel", "pipe-xel", "pipe-tec", "base-tec"]
    rows = []
    for rel, rec in sorted(results.items()):
        cells = [_status(rec, c) for c in conds]
        route = rec.get("route", {})
        flag = "reject" if route.get("reject") else ""
        rows.append((rel, rec.get("main", "?"), flag, *cells))
    matrix = [
        "| 工程 | main | 路由 | base-xel | pipe-xel | pipe-tec | base-tec |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    matrix.extend("| " + " | ".join(str(x) for x in r) + " |" for r in rows)
    (out_dir / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")

    lines = ["# e2e mock bench — corpus39", ""]
    for cond in conds:
        ran = [r[cond] for r in results.values() if r.get(cond)]
        clean = sum(1 for r in ran if r["verdict"]["status"] == "clean")
        lines.append(f"- **{cond}**: clean {clean}/{len(ran)}")
    lines.append("")
    # 归因：pipe 失败 ∧ base clean = 管线引入
    for eng in ("xel", "tec"):
        introduced = []
        for rel, rec in sorted(results.items()):
            p = rec.get(f"pipe-{eng}", {}).get("verdict", {}).get("status")
            b = rec.get(f"base-{eng}", {}).get("verdict", {}).get("status")
            if p not in (None, "clean") and b == "clean":
                introduced.append(rel)
        lines.append(f"- pipe-{eng} 失败且 base-{eng} clean（管线引入）: {introduced}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="substring filter on project id")
    ap.add_argument("--conditions", default="base-xel,pipe-xel,pipe-tec,base-tec")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    args = ap.parse_args()

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    projects = list_projects()
    for idx, rel in enumerate(projects):
        if args.only and args.only not in rel:
            continue
        if args.limit is not None and idx >= args.limit:
            break
        print(f"===== [{idx}/{len(projects)}] {rel} conds={conditions}", flush=True)
        rec = run_project(rel, conditions, args.timeout)
        if rel in results:
            results[rel].update(rec)
        else:
            results[rel] = rec
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        write_reports(results, out_dir)
        stat = {c: _status(rec, c) for c in conditions}
        print(f"  -> {stat}", flush=True)
    print(f"done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
