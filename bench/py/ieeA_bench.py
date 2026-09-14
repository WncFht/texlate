#!/usr/bin/env python3
r"""ieeA (zcyisiee/ieeA) parser benchmark — texlate PROTOCOL.

Measures:
 1. parse robustness over corpus/**/*.tex + fixtures (30s timeout)
 2. per-trap assertions on fixtures/tricky.tex, tricky-209.tex, tricky-multi/
 3. reconstruct fidelity (identity + fake-translation rebuild, placeholder residue)
 4. leak rate: chunks containing $ / \cite / \ref-family / \begin{

Writes bench/results/ieeA-parse.json
"""

import contextlib
import difflib
import io
import json
import re
import signal
import sys
import time
import warnings
from pathlib import Path

BENCH = Path("/Users/fanghaotian/src/texlate/bench")
CORPUS = BENCH / "corpus"
FIXTURES = BENCH / "fixtures"
RESULTS = BENCH / "results"

from ieeA.parser import LaTeXParser  # noqa: E402


class ParseTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise ParseTimeout()


def parse_one(path: Path, timeout_s: int = 30) -> dict:
    parser = LaTeXParser()
    out = io.StringIO()
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        with warnings.catch_warnings(record=True) as ws, contextlib.redirect_stdout(out):
            warnings.simplefilter("always")
            doc = parser.parse_file(str(path))
        ms = (time.perf_counter() - t0) * 1000
        return {
            "ok": True,
            "doc": doc,
            "ms": round(ms, 1),
            "warnings": sorted({str(w.message) for w in ws}),
            "prints": out.getvalue().strip().splitlines(),
        }
    except ParseTimeout:
        return {"ok": False, "error": "Timeout(>30s)", "ms": timeout_s * 1000}
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round(ms, 1)}
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


def scan_chunks(doc):
    """Return per-chunk leak info + aggregate counts."""
    per_chunk = []
    hits = {k: 0 for k in LEAK_PATTERNS}
    leaked = 0
    for c in doc.chunks:
        if c.context == "protected":
            continue
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            per_chunk.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    n = len([c for c in doc.chunks if c.context != "protected"])
    return {
        "n_translatable_chunks": n,
        "n_leaked": leaked,
        "hits": hits,
        "examples": per_chunk[:5],
    }


# ---------------------------------------------------------------- reconstruct
def orphan_chunk_ids(doc) -> int:
    """Chunks whose placeholder is unreachable (content silently dropped)."""
    ph_of = {c.id: f"{{{{CHUNK_{c.id}}}}}" for c in doc.chunks}
    haystacks = [doc.preamble, doc.body_template]
    haystacks += list(doc.global_placeholders.values())
    haystacks += [c.content for c in doc.chunks]
    blob = "\n".join(haystacks)
    orphans = 0
    for c in doc.chunks:
        if c.context == "protected":
            continue
        if ph_of[c.id] not in blob:
            orphans += 1
    return orphans


def classify_recon(orig: str, recon: str):
    if orig == recon:
        return "identical", 1.0, -1
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    # first diff position (cheap)
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


def fake_translation(chunk, idx):
    """Fake 'translation' that preserves placeholders (as a well-behaved MT would)."""
    keep = re.findall(r"\[\[[A-Z_]+_\d+\]\]|\{\{CHUNK_[a-f0-9-]+\}\}", chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def rebuild_metrics(doc):
    recon_identity = doc.reconstruct()
    translated = {
        c.id: fake_translation(c, i) for i, c in enumerate(doc.chunks)
    }
    recon_fake = doc.reconstruct(translated)
    residue_chunk = len(re.findall(r"\{\{CHUNK_", recon_fake))
    residue_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    return {
        "recon_identity": recon_identity,
        "recon_fake": recon_fake,
        "residue_chunk_ph": residue_chunk,
        "residue_protect_ph": residue_prot,
        "n_orphan_chunks": orphan_chunk_ids(doc),
    }


# ---------------------------------------------------------------- fixtures
def chunks_blob(doc):
    return "\n".join(c.content for c in doc.chunks if c.context != "protected")


def assert_tricky(doc, recon, recon_fake):
    """Return {Tnn: {status, detail}} for fixtures/tricky.tex."""
    chunks = chunks_blob(doc)
    ph_vals = "\n".join(doc.global_placeholders.values())
    res = {}

    def leak(rx, text=chunks):
        m = re.search(rx, text)
        return m.group(0) if m else None

    # T01 \be..\ee macro-expanded math env must be protected as a whole
    hit = leak(r"\\be\b|\\ee\b|\\wt\{A\}")
    res["T01"] = {
        "status": "fail" if hit else "pass",
        "detail": f"macro-env math leaked into translatable chunk: {hit!r}"
        if hit
        else "protected",
    }

    # T02 \dR custom math macro protected
    hit = leak(r"\\dR")
    res["T02"] = {
        "status": "fail" if hit else "pass",
        "detail": f"custom macro exposed raw in chunk: {hit!r}" if hit else "protected",
    }

    # T03 \def macro = definition, not translated
    hit = leak(r"\\def\\wt|\\def\\Tr")
    ok = "\\def\\wt{\\widetilde}" in recon
    res["T03"] = {
        "status": "pass" if (ok and not hit) else "fail",
        "detail": "stays in preamble"
        if ok and not hit
        else f"def lost or leaked: {hit!r} in_recon={ok}",
    }

    # T04 natbib family + ref family: keys must not appear in chunks
    fam = [
        "citep", "citet", "citealp", "citeauthor", "citeyear",
        "autoref", "cref", "pageref", "nameref",
    ]
    leaked_cmds = [c for c in fam if re.search(r"\\" + c + r"(?![a-zA-Z])", chunks)]
    leaked_keys = [
        k for k in ["vaswani2017", "kingma2015", "he2016", "devlin2019"] if k in chunks
    ]
    leaked_refs = [
        r for r in ["ref", "eqref", "label"] if re.search(r"\\" + r + r"\{", chunks)
    ]
    res["T04"] = {
        "status": "fail" if (leaked_cmds or leaked_keys or leaked_refs) else "pass",
        "detail": f"leaked cmds={leaked_cmds} keys={leaked_keys} core={leaked_refs}",
    }

    # T05 \section[opt]{long} -> long title translatable
    in_chunk = "A Very Long Section Title" in chunks
    in_recon = "A Very Long Section Title" in recon
    res["T05"] = {
        "status": "pass" if in_chunk else "fail",
        "detail": "long title chunked"
        if in_chunk
        else f"title NOT extracted (optional arg unsupported); survives literal in recon={in_recon} -> stays untranslated",
    }

    # T06 verbatim/lstlisting with % preserved
    verb_ok = "100% real data" in recon and "\\end{verbatim}" in recon
    lst_ok = "code%with%percent" in recon
    res["T06"] = {
        "status": "pass" if (verb_ok and lst_ok) else "fail",
        "detail": f"single-line verbatim intact={verb_ok}, lstlisting intact={lst_ok}",
    }

    # T07 \url{..%20..} / \verb|a%b| protected
    url_ok = "a%20b%20c.pdf" in recon
    verb_ok2 = "a%b" in recon
    res["T07"] = {
        "status": "pass" if (url_ok and verb_ok2) else "fail",
        "detail": f"url %20 intact={url_ok}, \\verb|a%b| intact={verb_ok2}",
    }

    # T08 comments: not translated, \% kept, no crash
    cmt_in_chunks = "a comment with" in chunks or "unbalanced brace" in chunks
    bs_pct_kept = "\\\\%" in recon or "\\%" in recon
    comment_text_leak = "followed by real comment" in chunks
    if cmt_in_chunks:
        st = "fail"
    elif comment_text_leak:
        st = "partial"
    else:
        st = "pass"
    res["T08"] = {
        "status": st,
        "detail": (
            f"comment-body-in-chunk={cmt_in_chunks}, \\\\%-trailing-comment "
            f"'followed by real comment' in chunk={comment_text_leak}, \\% preserved={bs_pct_kept}"
        ),
    }

    # T09 author block protected (or at least not translated)
    res["T09"] = {
        "status": "pass" if "Alice Smith" not in chunks else "fail",
        "detail": "author not in chunks (lives in preamble; note _protect_author_block"
        " regex \\\\author\\s*\\{ would miss the [1] optional arg if it were in body)",
    }

    # T10 subequations / align / flalign protected
    fl_leak = leak(r"x\s*&=\s*y") or leak(r"a\s*&=\s*b")
    envs_in_recon = "\\begin{subequations}" in recon and "\\begin{flalign}" in recon
    subeq_placeholder = any("subequations" in v or "flalign" in v for v in doc.global_placeholders.values())
    if fl_leak:
        st, d = "fail", f"math rows leaked into chunk: {fl_leak!r}"
    elif subeq_placeholder:
        st, d = "pass", "envs placeholder-protected"
    elif envs_in_recon:
        st, d = "partial", "subequations/flalign NOT in protected list; contents survive only as literal lines (would leak if >20 chars)"
    else:
        st, d = "fail", "env structure lost"
    res["T10"] = {"status": st, "detail": d}

    # T11 theorem env: body translatable, env preserved
    res["T11"] = {
        "status": "pass"
        if ("the statement holds" in chunks and "\\begin{theorem}" in recon)
        else "fail",
        "detail": "theorem body chunked, env literal in template",
    }

    # T12 footnote inside caption translatable
    res["T12"] = {
        "status": "pass" if "computed by hand" in chunks else "fail",
        "detail": "footnote text rides inside caption chunk -> translated"
        if "computed by hand" in chunks
        else "footnote text not extracted",
    }

    # T13 \ifdraft..\else..\fi no crash; conditional tokens in chunk = risk
    cond_leak = re.findall(r"\\ifdraft|\\else|\\fi|\\drafttrue", chunks)
    res["T13"] = {
        "status": "partial" if cond_leak else "pass",
        "detail": "parsed OK"
        + (
            f" but conditional tokens embedded in translatable chunk {sorted(set(cond_leak))} -> lost under translation"
            if cond_leak
            else ""
        ),
    }

    # T16 \NewDocumentCommand no crash/no leak
    res["T16"] = {
        "status": "pass"
        if ("\\NewDocumentCommand" in recon and "\\NewDocumentCommand" not in chunks)
        else "fail",
        "detail": "xparse def kept in preamble",
    }

    # T17 \text{} inside math stays protected
    res["T17"] = {
        "status": "pass" if "if and only if" not in chunks else "fail",
        "detail": "\\text{} rides inside [[MATH]] placeholder",
    }

    # T18 figure env + caption
    res["T18"] = {
        "status": "pass"
        if ("A figure with" in chunks and "\\begin{figure}" in recon)
        else "fail",
        "detail": "caption chunked, figure env preserved (figure is NOT in protected-env list but survives as literal lines)",
    }

    # T19 abstract
    res["T19"] = {
        "status": "pass" if any(c.context == "abstract" for c in doc.chunks) else "fail",
        "detail": "abstract env chunked",
    }

    # T20 list envs
    has_items = "First item" in chunks and "Numbered one" in chunks and "Its definition" in chunks
    res["T20"] = {"status": "pass" if has_items else "fail", "detail": "item texts chunked"}

    # T21 includegraphics protected
    gfx = "figs/plot.pdf" in ph_vals and "figs/plot.pdf" not in chunks
    res["T21"] = {"status": "pass" if gfx else "fail", "detail": "-> [[GRAPHICS_n]]"}

    # T22 \href: url protected, anchor translatable
    res["T22"] = {
        "status": "pass"
        if ("the documentation" in chunks and "https://example.com" in ph_vals)
        else "fail",
        "detail": "\\href{url} -> [[HREF_n]], {text} left for translation",
    }

    # T23 \emph \textbf \textit inner text translatable
    res["T23"] = {
        "status": "pass"
        if all(s in chunks for s in ["very important", "bold claim", "italic"])
        else "fail",
        "detail": "inline formatting text in chunks",
    }

    # T24 \bibliography no crash
    res["T24"] = {
        "status": "pass" if "\\bibliography{refs}" in recon else "fail",
        "detail": "kept literal (no .bbl/.bib in fixture dir)",
    }

    # T25 \makeatletter region no crash
    res["T25"] = {
        "status": "pass" if "\\makeatletter" in recon else "fail",
        "detail": "@-macros kept in preamble",
    }

    # T26 \[ \] and \( \) protected
    res["T26"] = {
        "status": "pass"
        if ("\\int_0^1" not in chunks and "e^{i\\pi}" not in chunks)
        else "fail",
        "detail": "display/inline delimiters -> [[MATH_n]]",
    }

    # T27 accents survive
    res["T27"] = {
        "status": "pass"
        if ("\\'e" in recon or "caf\\'e" in recon) and 'M\\"uller' in recon
        else "fail",
        "detail": "accent commands preserved as text",
    }

    # T29 standalone footnote translatable
    res["T29"] = {
        "status": "pass" if "This footnote text should be translated" in chunks else "fail",
        "detail": "footnote chunk extracted",
    }

    # extra: fake-translation residue on the fixture itself
    res_chunk = len(re.findall(r"\{\{CHUNK_", recon_fake))
    res_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    res["_meta"] = {
        "status": "info",
        "detail": (
            f"chunks={len(doc.chunks)} ph={len(doc.global_placeholders)} "
            f"residue_chunk={res_chunk} residue_prot={res_prot}"
        ),
    }
    return res


def assert_209(res_parse, recon):
    chunks = chunks_blob(res_parse["doc"]) if res_parse["ok"] else ""
    beq_leak = re.search(r"\\beq\b|\\eeq\b", chunks)
    return {
        "parse_ok": res_parse["ok"],
        "beq_eeq_trap": {
            "status": "fail" if beq_leak else "pass",
            "detail": f"\\beq..\\eeq leaked: {beq_leak.group(0) if beq_leak else None}",
        },
        "documentstyle": {
            "status": "pass" if res_parse["ok"] and "\\documentstyle" in recon else "fail",
            "detail": "2.09 preamble survives",
        },
        "def_macros": {
            "status": "pass" if res_parse["ok"] and "\\def\\Im" in recon else "fail",
            "detail": "\\def kept in preamble",
        },
    }


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {
        "lib": "ieeA",
        "lib_path": "/Users/fanghaotian/src/ieeA",
        "parser": "ieeA.parser.latex_parser.LaTeXParser.parse_file",
        "date": "2026-09-14",
        "parse": [],
        "leak_summary": {},
        "reconstruct": [],
        "fixtures": {},
    }

    corpus_files = sorted(CORPUS.rglob("*.tex"))
    fixture_files = [FIXTURES / "tricky.tex", FIXTURES / "tricky-209.tex",
                     FIXTURES / "tricky-multi" / "main.tex"]

    parsed = {}  # path -> result dict (with doc)
    all_files = [(p, "corpus") for p in corpus_files] + [
        (p, "fixture") for p in fixture_files
    ]

    total_chunks = 0
    total_leaked = 0
    hits_total = {k: 0 for k in LEAK_PATTERNS}
    t_all = time.perf_counter()

    for path, group in all_files:
        rel = str(path.relative_to(BENCH))
        r = parse_one(path)
        entry = {
            "file": rel,
            "group": group,
            "ok": r["ok"],
            "ms": r["ms"],
        }
        if not r["ok"]:
            entry["error"] = r["error"]
            report["parse"].append(entry)
            continue

        doc = r["doc"]
        entry["n_chunks"] = len(doc.chunks)
        entry["n_placeholders"] = len(doc.global_placeholders)
        if r["warnings"]:
            entry["warnings"] = r["warnings"]
        if r["prints"]:
            entry["prints"] = r["prints"][:5]

        lk = scan_chunks(doc)
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

        rb = rebuild_metrics(doc)
        orig = path.read_text(encoding="utf-8", errors="replace")
        status, ratio, first_diff = classify_recon(orig, rb["recon_identity"])
        entry["recon"] = {
            "status": status,
            "quick_ratio": ratio,
            "first_diff_at": first_diff,
            "len_orig": len(orig),
            "len_recon": len(rb["recon_identity"]),
            "residue_chunk_ph": rb["residue_chunk_ph"],
            "residue_protect_ph": rb["residue_protect_ph"],
            "n_orphan_chunks": rb["n_orphan_chunks"],
            "has_begin_document": "\\begin{document}" in orig,
        }
        report["parse"].append(entry)
        parsed[rel] = {**r, "recon_identity": rb["recon_identity"], "recon_fake": rb["recon_fake"]}

    report["leak_summary"] = {
        "total_translatable_chunks": total_chunks,
        "total_leaked_chunks": total_leaked,
        "leak_rate": round(total_leaked / total_chunks, 4) if total_chunks else None,
        "hits": hits_total,
        "wall_s": round(time.perf_counter() - t_all, 1),
    }

    # ---------------- fixture assertions
    tricky_rel = "fixtures/tricky.tex"
    r = parsed[tricky_rel]
    report["fixtures"]["tricky.tex"] = assert_tricky(
        r["doc"], r["recon_identity"], r["recon_fake"]
    )

    t209_rel = "fixtures/tricky-209.tex"
    r209 = parsed[t209_rel]
    report["fixtures"]["tricky-209.tex"] = assert_209(r209, r209["recon_identity"])

    multi_rel = "fixtures/tricky-multi/main.tex"
    rm = parsed[multi_rel]
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
            "detail": "nested \\input resolved relative to including file's dir (sub/sub/nested) -> "
            + ("found" if "Nested paragraph content" in recon_multi else "NOT found; literal \\input left in chunk"),
        },
        "T14_commented_input": {
            "status": "pass" if "THIS FILE MUST NOT APPEAR" not in recon_multi else "fail",
            "detail": "commented \\input expanded? "
            + ("yes -> FAIL" if "THIS FILE MUST NOT APPEAR" in recon_multi else "content removed by comment stripping (single-line file => survives by accident)"),
        },
        "commented_input_leak_into_chunk": {
            "status": "info",
            "detail": f"\\input{{sub/nested}} literal inside chunk: {bool(re.search(r'\\\\input', chunks_blob(rm['doc'])))}",
        },
    }

    out_path = RESULTS / "ieeA-parse.json"
    # strip doc objects before dumping
    clean = json.loads(json.dumps(report, default=str, ensure_ascii=False))
    out_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")
    n_ok = sum(1 for e in report["parse"] if e["ok"])
    print(f"parse ok {n_ok}/{len(report['parse'])}")
    print(f"leak rate {report['leak_summary']['leak_rate']} "
          f"({total_leaked}/{total_chunks})")
    for tid, v in report["fixtures"]["tricky.tex"].items():
        print(f"  {tid}: {v['status']}  {v['detail'][:100]}")
    print("  --209--")
    for tid, v in report["fixtures"]["tricky-209.tex"].items():
        if isinstance(v, dict):
            print(f"  {tid}: {v['status']}  {str(v['detail'])[:100]}")
        else:
            print(f"  {tid}: {v}")
    print("  --multi--")
    for tid, v in report["fixtures"]["tricky-multi"].items():
        print(f"  {tid}: {v['status']}  {v['detail'][:110]}")


if __name__ == "__main__":
    main()
