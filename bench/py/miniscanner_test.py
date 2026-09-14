#!/usr/bin/env python3
r"""miniscanner benchmark — texlate PROTOCOL, 与 ieeA_bench.py 同一断言口径.

 1. corpus/**/*.tex + fixtures 解析鲁棒性 (30s timeout)
 2. fixtures/tricky.tex, tricky-209.tex, tricky-multi/ 逐条陷阱断言
 3. reconstruct 保真: identity / fake-translation 占位符残留 / 孤儿 chunk
 4. 泄漏率: 可译 chunk 内含 $ \cite \ref \begin{ 条件命令的比例

写出 bench/results/miniscanner-parse.json, 终端打矩阵.
"""

import difflib
import json
import re
import signal
import sys
import time
from pathlib import Path

BENCH = Path("/Users/fanghaotian/src/texlate/bench")
CORPUS = BENCH / "corpus"
FIXTURES = BENCH / "fixtures"
RESULTS = BENCH / "results"

sys.path.insert(0, str(Path(__file__).parent))
import miniscanner as ms


class ParseTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise ParseTimeout


def parse_one(path: Path, timeout_s: int = 30, flatten: bool = True) -> dict:
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        res = ms.parse_file(str(path), flatten=flatten)
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": True, "res": res, "ms": round(ms_, 1)}
    except ParseTimeout:
        return {"ok": False, "error": "Timeout(>30s)", "ms": timeout_s * 1000}
    except Exception as e:
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round(ms_, 1)}
    finally:
        signal.alarm(0)


# ---------------------------------------------------------------- leak scan
LEAK_PATTERNS = {
    "dollar": re.compile(r"\$"),
    "cite_family": re.compile(r"\\cite[a-zA-Z]*"),
    "ref_family": re.compile(r"\\(?:eq|auto|c|page|name|sub)?ref(?![a-zA-Z])"),
    "begin_env": re.compile(r"\\begin\{"),
    "conditional": re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])"),
    "input_include": re.compile(r"\\(?:input|include)\{"),
}


def scan_chunks(res: ms.ScanResult):
    per_chunk = []
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    for c in res.chunks:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            per_chunk.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    return {
        "n_translatable_chunks": len(res.chunks),
        "n_leaked": leaked,
        "hits": hits,
        "examples": per_chunk[:5],
    }


# ---------------------------------------------------------------- reconstruct
def orphan_chunk_ids(res: ms.ScanResult) -> int:
    """chunk 的占位符在任何可及位置都见不到 → 内容被静默丢弃."""
    blob = (
        res.protected_tex
        + "\n"
        + "\n".join(res.ph_map.values())
        + "\n"
        + "\n".join(c.content for c in res.chunks)
    )
    orphans = 0
    for c in res.chunks:
        if f"[[CHUNK_{c.id}]]" not in blob:
            orphans += 1
    return orphans


def classify_recon(orig: str, recon: str):
    if orig == recon:
        return "identical", 1.0, -1

    def norm(s):
        return re.sub(r"\s+", " ", s).strip()

    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


def fake_translation(chunk: ms.Chunk, idx: int) -> str:
    keep = re.findall(r"\[\[[A-Z_]+_\d+\]\]", chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def rebuild_metrics(res: ms.ScanResult):
    recon_identity = ms.reconstruct(res)
    translated = {c.id: fake_translation(c, i) for i, c in enumerate(res.chunks)}
    recon_fake = ms.reconstruct(res, translated)
    residue_chunk = len(re.findall(r"\[\[CHUNK_\d+\]\]", recon_fake))
    residue_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    return {
        "recon_identity": recon_identity,
        "recon_fake": recon_fake,
        "residue_chunk_ph": residue_chunk,
        "residue_protect_ph": residue_prot,
        "n_orphan_chunks": orphan_chunk_ids(res),
    }


# ---------------------------------------------------------------- fixtures
def chunks_blob(res: ms.ScanResult) -> str:
    return "\n".join(c.content for c in res.chunks)


def assert_tricky(res: ms.ScanResult, recon: str, recon_fake: str):
    chunks = chunks_blob(res)
    ph_vals = "\n".join(res.ph_map.values())
    out = {}

    def leak(rx):
        m = re.search(rx, chunks)
        return m.group(0) if m else None

    # T01 \be..\ee 宏展开数学环境整体保护
    hit = leak(r"\\be\b|\\ee\b|\\wt\{A\}")
    out["T01"] = {
        "status": "fail" if hit else "pass",
        "detail": f"macro-env math leaked: {hit!r}"
        if hit
        else "\\be..\\ee -> [[MATH_n]]",
    }

    # T02 \dR 自定义数学宏
    hit = leak(r"\\dR")
    out["T02"] = {
        "status": "fail" if hit else "pass",
        "detail": f"custom macro raw in chunk: {hit!r}"
        if hit
        else "\\dR -> [[MACRO_n]]",
    }

    # T03 \def 宏定义不译
    hit = leak(r"\\def\\wt|\\def\\Tr")
    ok = "\\def\\wt{\\widetilde}" in recon
    out["T03"] = {
        "status": "pass" if (ok and not hit) else "fail",
        "detail": "def in preamble, verbatim"
        if ok and not hit
        else f"def lost/leaked: {hit!r} in_recon={ok}",
    }

    # T04 natbib 全族 + ref 族
    fam = [
        "citep",
        "citet",
        "citealp",
        "citeauthor",
        "citeyear",
        "autoref",
        "cref",
        "pageref",
        "nameref",
    ]
    leaked_cmds = [c for c in fam if re.search(r"\\" + c + r"(?![a-zA-Z])", chunks)]
    leaked_keys = [
        k for k in ["vaswani2017", "kingma2015", "he2016", "devlin2019"] if k in chunks
    ]
    leaked_refs = [
        r for r in ["ref", "eqref", "label"] if re.search(r"\\" + r + r"\{", chunks)
    ]
    out["T04"] = {
        "status": "fail" if (leaked_cmds or leaked_keys or leaked_refs) else "pass",
        "detail": f"cmds={leaked_cmds} keys={leaked_keys} core={leaked_refs}",
    }

    # T05 \section[opt]{long}
    out["T05"] = {
        "status": "pass" if "A Very Long Section Title" in chunks else "fail",
        "detail": "long title chunked"
        if "A Very Long Section Title" in chunks
        else "optional arg unsupported -> title lost",
    }

    # T06 verbatim/lstlisting 内 % 原样
    verb_ok = "100% real data" in recon and "\\end{verbatim}" in recon
    lst_ok = "code%with%percent" in recon
    out["T06"] = {
        "status": "pass" if (verb_ok and lst_ok) else "fail",
        "detail": f"verbatim intact={verb_ok} lstlisting={lst_ok}",
    }

    # T07 \url{..%20..} \verb|a%b|
    url_ok = "a%20b%20c.pdf" in recon
    verb_ok2 = "a%b" in recon
    out["T07"] = {
        "status": "pass" if (url_ok and verb_ok2) else "fail",
        "detail": f"url %20={url_ok} verb={verb_ok2}",
    }

    # T08 注释边界
    cmt_in_chunks = "a comment with" in chunks or "unbalanced brace" in chunks
    comment_text_leak = "followed by real comment" in chunks
    pct_kept = "\\%" in recon
    if cmt_in_chunks:
        st = "fail"
    elif comment_text_leak or not pct_kept:
        st = "partial"
    else:
        st = "pass"
    out["T08"] = {
        "status": st,
        "detail": f"comment-in-chunk={cmt_in_chunks} "
        f"\\\\%-trail={comment_text_leak} "
        f"\\% kept={pct_kept}",
    }

    # T09 author 保护
    out["T09"] = {
        "status": "pass" if "Alice Smith" not in chunks else "fail",
        "detail": "author -> [[AUTHOR_n]]",
    }

    # T10 subequations/align/flalign
    fl_leak = leak(r"x\s*&=\s*y") or leak(r"a\s*&=\s*b")
    subeq_ph = any("subequations" in v or "flalign" in v for v in res.ph_map.values())
    out["T10"] = {
        "status": "pass"
        if (not fl_leak and subeq_ph)
        else ("partial" if not fl_leak else "fail"),
        "detail": "all -> [[MATH_n]]"
        if subeq_ph and not fl_leak
        else f"leak={fl_leak!r}",
    }

    # T11 theorem 可选名 + 正文可译
    out["T11"] = {
        "status": "pass"
        if ("the statement holds" in chunks and "\\begin{theorem}" in recon)
        else "fail",
        "detail": "theorem body chunked, env literal",
    }

    # T12 caption 内 footnote
    out["T12"] = {
        "status": "pass" if "computed by hand" in chunks else "fail",
        "detail": "footnote text rides in caption chunk",
    }

    # T13 \ifdraft..\else..\fi
    cond_leak = re.findall(r"\\ifdraft|\\else|\\fi|\\drafttrue", chunks)
    out["T13"] = {
        "status": "partial" if cond_leak else "pass",
        "detail": "conditional tokens as boundary literals"
        + (f" LEAKED {sorted(set(cond_leak))}" if cond_leak else ""),
    }

    # T16 \NewDocumentCommand
    out["T16"] = {
        "status": "pass"
        if ("\\NewDocumentCommand" in recon and "\\NewDocumentCommand" not in chunks)
        else "fail",
        "detail": "xparse def kept verbatim",
    }

    # T17 数学内 \text{}
    out["T17"] = {
        "status": "pass" if "if and only if" not in chunks else "fail",
        "detail": "\\text{} inside [[MATH]]",
    }

    # T18 figure 内 caption
    out["T18"] = {
        "status": "pass"
        if ("A figure with" in chunks and "\\begin{figure}" in recon)
        else "fail",
        "detail": "caption mined from [[ENV]] body",
    }

    # T19 abstract
    out["T19"] = {
        "status": "pass" if "We study tricky" in chunks else "fail",
        "detail": "abstract text chunked",
    }

    # T20 列表
    has_items = (
        "First item" in chunks
        and "Numbered one" in chunks
        and "Its definition" in chunks
    )
    out["T20"] = {
        "status": "pass" if has_items else "fail",
        "detail": "item texts chunked",
    }

    # T21 includegraphics
    gfx = "figs/plot.pdf" in ph_vals and "figs/plot.pdf" not in chunks
    out["T21"] = {"status": "pass" if gfx else "fail", "detail": "-> [[GRAPHICS_n]]"}

    # T22 \href
    out["T22"] = {
        "status": "pass"
        if ("the documentation" in chunks and "https://example.com" in ph_vals)
        else "fail",
        "detail": "url->[[HREF_n]], text translatable",
    }

    # T23 \emph\textbf\textit
    out["T23"] = {
        "status": "pass"
        if all(s in chunks for s in ["very important", "bold claim", "italic"])
        else "fail",
        "detail": "inline formatting text merged into chunk",
    }

    # T24 \bibliography
    out["T24"] = {
        "status": "pass" if "\\bibliography{refs}" in recon else "fail",
        "detail": "-> [[BIB_n]], survives",
    }

    # T25 \makeatletter
    out["T25"] = {
        "status": "pass" if "\\makeatletter" in recon else "fail",
        "detail": "kept literal",
    }

    # T26 \[ \] \( \)
    out["T26"] = {
        "status": "pass"
        if ("\\int_0^1" not in chunks and "e^{i\\pi}" not in chunks)
        else "fail",
        "detail": "display/inline delims -> [[MATH_n]]",
    }

    # T27 重音
    out["T27"] = {
        "status": "pass"
        if ("\\'e" in recon or "caf\\'e" in recon) and 'M\\"uller' in recon
        else "fail",
        "detail": "accent commands preserved",
    }

    # T29 独立 footnote
    out["T29"] = {
        "status": "pass"
        if "This footnote text should be translated" in chunks
        else "fail",
        "detail": "footnote arg -> own chunk",
    }

    res_chunk = len(re.findall(r"\[\[CHUNK_\d+\]\]", recon_fake))
    res_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    out["_meta"] = {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={res_chunk} residue_prot={res_prot}",
    }
    return out


def assert_209(res_parse, recon):
    res = res_parse["res"] if res_parse["ok"] else None
    chunks = chunks_blob(res) if res else ""
    beq_leak = re.search(r"\\beq\b|\\eeq\b", chunks)
    return {
        "parse_ok": res_parse["ok"],
        "beq_eeq_trap": {
            "status": "fail" if beq_leak else "pass",
            "detail": f"\\beq..\\eeq leaked: {beq_leak.group(0) if beq_leak else None}",
        },
        "documentstyle": {
            "status": "pass"
            if res_parse["ok"] and "\\documentstyle" in recon
            else "fail",
            "detail": "2.09 preamble survives",
        },
        "def_macros": {
            "status": "pass" if res_parse["ok"] and "\\def\\Im" in recon else "fail",
            "detail": "\\def kept verbatim",
        },
    }


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {
        "lib": "miniscanner",
        "date": "2026-09-14",
        "parse": [],
        "leak_summary": {},
        "fixtures": {},
    }

    corpus_files = sorted(CORPUS.rglob("*.tex"))
    fixture_files = [
        FIXTURES / "tricky.tex",
        FIXTURES / "tricky-209.tex",
        FIXTURES / "tricky-multi" / "main.tex",
    ]
    all_files = [(p, "corpus") for p in corpus_files] + [
        (p, "fixture") for p in fixture_files
    ]

    parsed = {}
    total_chunks = total_leaked = 0
    hits_total = dict.fromkeys(LEAK_PATTERNS, 0)
    recon_stats = {"identical": 0, "normalized": 0, "diverged": 0}
    t_all = time.perf_counter()

    for path, group in all_files:
        rel = str(path.relative_to(BENCH))
        r = parse_one(path)
        entry = {"file": rel, "group": group, "ok": r["ok"], "ms": r["ms"]}
        if not r["ok"]:
            entry["error"] = r["error"]
            report["parse"].append(entry)
            continue

        res = r["res"]
        entry["n_chunks"] = len(res.chunks)
        entry["n_placeholders"] = len(res.ph_map)

        lk = scan_chunks(res)
        entry["leak"] = {
            "n_translatable": lk["n_translatable_chunks"],
            "n_leaked": lk["n_leaked"],
            "hits": {k: v for k, v in lk["hits"].items() if v},
        }
        if lk["examples"]:
            entry["leak"]["examples"] = lk["examples"][:2]
        total_chunks += lk["n_translatable_chunks"]
        total_leaked += lk["n_leaked"]
        for k, v in lk["hits"].items():
            hits_total[k] += v

        rb = rebuild_metrics(res)
        orig = path.read_text(encoding="utf-8", errors="replace")
        # flatten 在 parse 前已展开 \input → recon 的对比基准是展平文本
        orig_flat = ms.flatten_inputs(orig, str(path.parent), str(path.parent))
        status, ratio, first_diff = classify_recon(orig_flat, rb["recon_identity"])
        recon_stats[status] += 1
        entry["recon"] = {
            "status": status,
            "quick_ratio": ratio,
            "first_diff_at": first_diff,
            "residue_chunk_ph": rb["residue_chunk_ph"],
            "residue_protect_ph": rb["residue_protect_ph"],
            "n_orphan_chunks": rb["n_orphan_chunks"],
        }
        report["parse"].append(entry)
        parsed[rel] = {
            "res": res,
            "recon_identity": rb["recon_identity"],
            "recon_fake": rb["recon_fake"],
            "ok": True,
            "ms": r["ms"],
        }

    report["leak_summary"] = {
        "total_translatable_chunks": total_chunks,
        "total_leaked_chunks": total_leaked,
        "leak_rate": round(total_leaked / total_chunks, 4) if total_chunks else None,
        "hits": hits_total,
        "recon_stats": recon_stats,
        "wall_s": round(time.perf_counter() - t_all, 1),
    }

    # ---------------- fixture 断言
    rt = parsed["fixtures/tricky.tex"]
    report["fixtures"]["tricky.tex"] = assert_tricky(
        rt["res"], rt["recon_identity"], rt["recon_fake"]
    )

    r209 = parsed["fixtures/tricky-209.tex"]
    report["fixtures"]["tricky-209.tex"] = assert_209(r209, r209["recon_identity"])

    rm = parsed["fixtures/tricky-multi/main.tex"]
    recon_multi = rm["recon_identity"]
    report["fixtures"]["tricky-multi"] = {
        "T14_input_expanded": {
            "status": "pass" if "Intro paragraph" in recon_multi else "fail",
            "detail": "sub/intro.tex inlined",
        },
        "T14_include_expanded": {
            "status": "pass" if "Methods paragraph" in recon_multi else "fail",
            "detail": "sub/methods.tex inlined",
        },
        "T14_nested_input": {
            "status": "pass" if "Nested paragraph content" in recon_multi else "fail",
            "detail": "nested \\input resolved vs main dir",
        },
        "T14_commented_input": {
            "status": "pass"
            if "THIS FILE MUST NOT APPEAR" not in recon_multi
            else "fail",
            "detail": "commented \\input not expanded",
        },
    }

    out_path = RESULTS / "miniscanner-parse.json"
    report["parse"] = json.loads(
        json.dumps(report["parse"], default=str, ensure_ascii=False)
    )
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    n_ok = sum(1 for e in report["parse"] if e["ok"])
    print(f"parse ok {n_ok}/{len(report['parse'])}")
    print(
        f"leak rate {report['leak_summary']['leak_rate']} "
        f"({total_leaked}/{total_chunks}) hits={hits_total}"
    )
    print(f"recon {recon_stats}")
    for tid, v in report["fixtures"]["tricky.tex"].items():
        print(f"  {tid}: {v['status']}  {v['detail'][:110]}")
    print("  --209--")
    for tid, v in report["fixtures"]["tricky-209.tex"].items():
        if isinstance(v, dict):
            print(f"  {tid}: {v['status']}  {str(v['detail'])[:110]}")
        else:
            print(f"  {tid}: {v}")
    print("  --multi--")
    for tid, v in report["fixtures"]["tricky-multi"].items():
        print(f"  {tid}: {v['status']}  {v['detail'][:110]}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
