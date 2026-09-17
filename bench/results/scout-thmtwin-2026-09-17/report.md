# scout-thmtwin: `\@begintheorem` runaway attribution (1306.0281)

## Verdict

**THEOREM_ANCHOR_SHIM innocent; splice reconstruction innocent.** The killer is
the fixloop `acm_proc_article-sp.cls` stub
(`src/texlate/compile/fixloop/rules.yaml:1783`) bridging to **acmart**:
acmart→`\RequirePackage{amsthm}` flips `\@begintheorem` to signature `#1#2[#3]`,
while the document's **ntheorem**
(`\usepackage[amsmath,thmmarks,hyperref]{ntheorem}` — *without* the `amsthm`
option) calls it with the kernel 2-arg convention. Minimal repro `a_noshim.tex`
(no shim at all) fails identically to `b_shim.tex` (with shim) — 9 bangs each,
same 2× Paragraph-ended + missing-\item cascade.

## Mechanism (verified at primitive level, `tmp/thmtwin/t1.tex`)

In `\def\@begintheorem#1#2[#3]`, `[` is **#2's trailing delimiter** — TeX scans
#2 = "everything up to the first depth-0 `[`". ntheorem's `\@xthm`
(ntheorem.sty:893-897) expands to `\@begintheorem{Definition}{\csname
thetheorem\endcsname}\ifx\thm@starredenv\@undefined\thm@thmcaption{...}\fi
\ignorespaces` — so #2's `[`-hunt swallows `{\csname thetheorem\endcsname}\ifx
\thm@starredenv\@undefined\thm@thmcaption ...` — **exactly the runaway arg in
the real log** — then keeps eating the env body until `\par` (the blank-line
error sites) or a stray `[`. All 6 errors are no-note (`\@xthm`-arm) envs; the
6 `missing \item` are the cascade when `\end{env}` hits a trivlist that never
got `\item`.

Who holds the signature: probe `c_probe.tex` shows `\@begintheorem` = amsthm
`#1#2[#3]` after class, and at `\begin{document}` it's nameref-wrapped
(`\NR@gettitle{#3}\NRorg@begintheorem{#1}{#2}[{#3}]` — hyperref via acmart) —
same `[`-delimited signature, same death. ntheorem only redefines
`\@begintheorem` inside its `[amsthm]` option block (ntheorem.sty:668-684); this
doc doesn't use it, so it expects kernel `#1#2`. The real 2009 acm class doesn't
load amsthm — only the acmart bridge introduces the clash.

**Bonus silent corruption in the same family:** noted envs go `\@ythm` →
`\@opargbegintheorem{N}{C}{note}`, which is `\relax` in this stack →
`{Lemma}{2.1}{note}` typesets as literal junk with no error. The fix below
repairs this too.

## Fix (verified)

Add to the stub body in `rules.yaml:1783` — restore ntheorem's own
`amsthm`-option **item-only** defs (ntheorem's `\@thm` already opens `\trivlist`;
a `\trivlist`-carrying restore reintroduces missing-\item):

```tex
\AtBeginDocument{\@ifpackageloaded{ntheorem}{%
  \def\@begintheorem#1#2{\item[\hskip\labelsep \theorem@headerfont #1\ #2.]}%
  \def\@opargbegintheorem#1#2#3{\item[\hskip\labelsep \theorem@headerfont #1\ #2\ (#3).]}%
}{}}
```

Results: `f_fix4.tex` 9 bangs → 1 (only preexisting `Theorem style plain
already defined` noise, present in both baselines); `g_shimfix.tex` (shim + fix)
clean, PDF out. Rejected alternative: `\PassOptionsToPackage{amsthm}{ntheorem}`
introduces new breakage (style/proof/openbox already-defined + `\NAT@@citetp`).

Tradeoff: the restore kills nameref's theorem-title wrap and the thmtwin hook
for ntheorem envs — symmetric in both arms, `\refstepcounter`+hyperref anchors
(`theorem.N`) still produced, so anchor parity is unaffected.

**Suggested owner file:** `src/texlate/compile/fixloop/rules.yaml` (the stub is
already a per-paper bespoke kit; inject.py untouched). Generic variant if
wanted: a fixloop rule keyed on "ntheorem loaded + `\@begintheorem` meaning
starts `macro:#1#2[#3]`" — amsart2000 bridge has the same exposure.

## Artifacts

- Repros/probe/fix variants:
  `bench/results/scout-thmtwin-2026-09-17/{a_noshim,b_shim,c_probe,f_fix4,g_shimfix}.tex`
- Field evidence:
  `bench/results/fixer-legacy-acm-2026-09-17/work/1306.0281/splice/main.log`
  L2584–3015

(Report text as delivered by scout-thmtwin; written to file by leader per
subagent report protocol.)
