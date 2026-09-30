#!/usr/bin/env python3
r"""iclr/sections.py — arXiv 源码 → 章节级词数/字符数统计（ICLR 章节长度研究）.

语料目录形态与 corpus 一致: ``{corpus}/{id}/extracted/`` (+ ``meta.json``)。
对每篇: find_main_tex 定位主档 → ``\input``/``\include`` 流内展开 →
剥注释 → 裁 ``\begin{document}`` 正文 → 按 ``\section`` 边界切分 →
detex 计词数（数学/浮动体/引用剥离，caption 单列）→ 章节名归一 bucket。

输出 sections.jsonl（每篇一行，sections 明细内嵌）+ 末尾打印覆盖对账。
纯离线：只吃盘上语料，不发网络请求。uv run python bench/py/iclr/sections.py

用法:
  uv run python bench/py/iclr/sections.py --corpus bench/corpus \
      --out bench/work_iclr/sections_corpusv3.jsonl [--ids file] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import suppress
from pathlib import Path

# 包内脚本直跑时 bench/py 不在 sys.path——先立起再引 specs/kernel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib

from texlate.compile.inject import find_main_tex

REPO = Path(__file__).resolve().parents[3]

log = benchlib.log

# ---------------- 文本处理 ----------------

INPUT_RX = re.compile(
    r"\\(?:input|include|InputIfFileExists|subfile|import|subimport)\b"
    r"\s*(?:\[[^\]]*\])?\s*\{?\\?\s*([^{}\s]+)\}?"
)
BEGIN_DOC = re.compile(r"\\begin\s*\{document\}")
END_DOC = re.compile(r"\\end\s*\{document\}")
SEC_RX = re.compile(
    r"\\(section|subsection|subsubsection)\s*(\*)?\s*(?:\[([^\]]*)\])?\s*\{"
)
APPENDIX_CMD_RX = re.compile(r"\\appendix\b|\\begin\s*\{(?:appendices|appendix)\}")
REFS_RX = re.compile(
    r"\\bibliography\s*\{|\\printbibliography|\\begin\s*\{thebibliography\}"
)
ABSTRACT_RX = re.compile(r"\\begin\s*\{abstract\}(.*?)\\end\s*\{abstract\}", re.DOTALL)

MATH_ENVS = (
    "equation|equation*|eqnarray|eqnarray*|align|align*|alignat|alignat*|"
    "gather|gather*|multline|multline*|flalign|flalign*|displaymath|math|"
    "dmath|dmath*|subequations|split|aligned|gathered"
)
KILL_ENVS = (
    "figure|figure*|table|table*|algorithm|algorithm*|algorithmic|algorithm2e|"
    "algpseudocode|tikzpicture|pgfpicture|pspicture|picture|verbatim|verbatim*|"
    "lstlisting|minted|listing|sidewaysfigure|sidewaystable|wrapfigure|"
    "wraptable|SCfigure|framed|mdframed|tcolorbox|bclogo|asy|tabular|tabular*|"
    "tabularx|tabulary|longtable|supertabular|xtab|threeparttable|array|"
    "minipage|parbox|subfigure|subtable|floatrow|ffigbox|talltblr|tblr"
)
KILL_ENV_RX = re.compile(
    r"\\begin\s*\{(" + KILL_ENVS + r")\}(.*?)\\end\s*\{\1\}", re.DOTALL
)
MATH_ENV_RX = re.compile(
    r"\\begin\s*\{(" + MATH_ENVS + r")\}.*?\\end\s*\{\1\}", re.DOTALL
)
CAPTION_RX = re.compile(r"\\(?:caption|subcaption)\s*(?:\[[^\]]*\])?\s*{")

DROP_ARG_CMDS = (
    "cite|citet|citep|citealp|citealt|citeauthor|citeyear|citeyearpar|"
    "citeonline|citereset|footcite|parencite|textcite|autocite|supercite|"
    "ref|eqref|autoref|cref|Cref|vref|Vref|pageref|nameref|secref|figref|"
    "tabref|appref|label|url|doi|email|includegraphics|bibliography|"
    "bibliographystyle|addbibresource|vspace|vspace*|hspace|hspace*|"
    "vskip|hskip|vfill|hfill|newpage|clearpage|pagebreak|nopagebreak|"
    "linebreak|nolinebreak|footnote[*]?mark|footnotemark|thanks|index|"
    "gls|Gls|glspl|acrshort|acrlong|acrfull|hypertarget|phantom|smash|"
    "ensuremath|mycite"
)
DROP_ARG_RX = re.compile(
    r"\\(?:" + DROP_ARG_CMDS + r")\s*(?:\[[^\]]*\])?\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
)
HREF_RX = re.compile(r"\\href\s*\{[^{}]*\}\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
TEXTCMD_RX = re.compile(
    r"\\(?:emph|textbf|textit|textsc|textsl|textsf|textrm|text|mathrm|mathbf|"
    r"mathit|mathcal|mathsf|mathtt|underline|uppercase|lowercase|noindent|"
    r"paragraph|subparagraph|title|author|footnote|footnotetext|mbox|hbox|"
    r"captionof|chapter|part|section|subsection|subsubsection)\s*(\*)?"
    r"\s*(?:\[[^\]]*\])?\s*"
)
MATH_RXES = [
    re.compile(r"\$\$.*?\$\$", re.DOTALL),
    re.compile(r"\\\[.*?\\\]", re.DOTALL),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
    re.compile(r"\$(?:[^$\\]|\\.)*\$"),
]
BRACE_CMD_RX = re.compile(r"\\[a-zA-Z]+\s*(\*)?\s*")
LONE_CMD_RX = re.compile(r"\\[a-zA-Z@]+\b|\\[^a-zA-Z]")
WORD_RX = re.compile(r"[A-Za-z][A-Za-z0-9_'&.-]*")
NUM_RX = re.compile(r"^\d[\d.,/%-]*$")


strip_comments = benchlib.strip_comments


def read_tex(p: Path) -> str:
    b = p.read_bytes()
    for enc in ("utf-8", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def norm_input_target(raw: str) -> str:
    t = raw.strip().strip("{}").strip('"').strip("'")
    t = t.replace("\\", "/")
    while t.startswith("./"):  # 只剥 "./" 前缀——保留 ".." 让 base/root  join 出真父级
        t = t[2:]
    if t.endswith(".tex.tex"):
        t = t[:-4]
    return t


def expand_inputs(root: Path, main: Path, cap: int = 4 << 20) -> tuple[str, int]:
    """主档文本流内展开 \\input/\\include（按文件目录解析，.tex 补后缀）。

    返回 (展开后全文，未解析目标数)。深度上界 8，总量 cap 防爆。
    """
    unresolved = 0

    bib_rx = re.compile(r"\\bibliography\s*\{([^{}]+)\}")

    def _expand(p: Path, depth: int, seen: frozenset) -> str:
        nonlocal unresolved
        try:
            text = read_tex(p)
        except OSError:
            return ""
        base = p.parent
        out, last = [], 0
        for m in INPUT_RX.finditer(text):
            out.append(text[last : m.start()])
            last = m.end()
            if depth >= 8:
                continue
            raw = m.group(1) or ""
            if m.group(0).startswith(("\\import", "\\subimport")):
                continue  # import 系换目录语义，先不展开（少见）
            tgt = norm_input_target(raw)
            cands = [
                base / tgt,
                base / (tgt + ".tex"),
                root / tgt,
                root / (tgt + ".tex"),
                base / Path(tgt).name,
                base / (Path(tgt).name + ".tex"),
            ]
            hit = next((c for c in cands if c.exists() and c.is_file()), None)
            if hit is None or hit in seen:
                if hit is None and tgt and not tgt.startswith("%"):
                    unresolved += 1
                continue
            out.append("\n" + _expand(hit, depth + 1, seen | {hit}) + "\n")
        out.append(text[last:])
        expanded = "".join(out)
        if depth == 0:
            # \bibliography{x} → 内联 x.bbl（thebibliography env 在其内）
            def _bib_sub(m: re.Match) -> str:
                nonlocal unresolved
                names = [n.strip() for n in m.group(1).split(",")]
                parts = [m.group(0)]
                for nm in names:
                    hit = next(
                        (
                            c
                            for c in (
                                base / (nm + ".bbl"),
                                root / (nm + ".bbl"),
                                base / nm,
                                root / nm,
                            )
                            if c.exists() and c.is_file()
                        ),
                        None,
                    )
                    if hit is not None:
                        try:
                            parts.append("\n" + read_tex(hit) + "\n")
                        except OSError:
                            unresolved += 1
                return "\n".join(parts)

            expanded = bib_rx.sub(_bib_sub, expanded)
        return expanded

    full = _expand(main.resolve(), 0, frozenset({main.resolve()}))
    return full[:cap], unresolved


def _grab_brace(text: str, start: int) -> tuple[str, int]:
    """text[start]=='{' → (平衡括号内内容，结束后位置)。"""
    depth, i = 0, start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        elif c == "\\":
            i += 1  # 跳过转义符后一字符
        i += 1
    return text[start + 1 :], n


def _extract_captions(text: str) -> tuple[str, int]:
    """抽 \\caption{...} 内文（返回拼接文本，词数在上游计）。"""
    caps = []
    for m in CAPTION_RX.finditer(text):
        inner, _ = _grab_brace(text, m.end() - 1)
        caps.append(inner)
    return " ".join(caps)


def detex(text: str) -> tuple[str, str]:
    """LaTeX → 纯文本。返回 (正文文本，浮动体 caption 文本)。

    顺序：抽 caption → 杀浮动体 env → 杀数学 env/$$..$$/$..$ →
    href 留锚文 → drop-arg 命令整删 → 其余命令丢名留参 → 残余 \\cmd 抹除。
    """
    caps = _extract_captions(text)
    prev = None
    while prev != text:  # env 嵌套：迭代到不动点
        prev = text
        text = KILL_ENV_RX.sub(" ", text)
        text = MATH_ENV_RX.sub(" ", text)
    for rx in MATH_RXES:
        text = rx.sub(" ", text)
    text = HREF_RX.sub(lambda m: " " + m.group(1) + " ", text)
    prev = None
    while prev != text:
        prev = text
        text = DROP_ARG_RX.sub(" ", text)
    text = re.sub(r"\\item\b", "\n", text)
    text = TEXTCMD_RX.sub(" ", text)
    text = LONE_CMD_RX.sub(" ", text)
    text = re.sub(r"[{}]", " ", text)
    return text, caps


def count_words(text: str) -> int:
    return sum(1 for m in WORD_RX.finditer(text) if not NUM_RX.match(m.group(0)))


def detex_count(text: str) -> tuple[int, int, int]:
    body, caps = detex(text)
    return count_words(body), len(body), count_words(caps)


# ---------------- section 名归一 ----------------

BUCKET_RULES: list[tuple[str, re.Pattern]] = [
    ("abstract", re.compile(r"abstract|summary$", re.IGNORECASE)),
    (
        "introduction",
        re.compile(
            r"^introduction|^intro\b|contribution|overview$|"
            r"^paper organization|^outline",
            re.IGNORECASE,
        ),
    ),
    (
        "related_work",
        re.compile(
            r"related work|prior work|previous work|related literature|"
            r"literature review|background and related",
            re.IGNORECASE,
        ),
    ),
    (
        "background",
        re.compile(
            r"^background|^preliminar|^prerequisite|^notation|^setup and notation|"
            r"^problem (setup|setting|statement|formulation)|^definitions|^setting\b",
            re.IGNORECASE,
        ),
    ),
    (
        "results",
        re.compile(
            r"^result|^main result|^finding|^performance|^comparison|^main experiment|^quantitative|"
            r"^qualitative",
            re.IGNORECASE,
        ),
    ),
    (
        "method",
        re.compile(
            r"method|approach|model|framework|technique|algorithm|architecture|"
            r"formulation|our |proposed|design|^theory\b|mechanism|solution|"
            r"^derivation|^the proposed",
            re.IGNORECASE,
        ),
    ),
    (
        "theory",
        re.compile(
            r"theoretical|theor(y|em|etic)|proof|analysis of|convergence|"
            r"generalization|bound|guarantee",
            re.IGNORECASE,
        ),
    ),
    (
        "experiments",
        re.compile(
            r"experiment|empirical|evaluation|implementation|setup|simulation|"
            r"benchmark|protocol|dataset|baseline|hyperparameter|numerical",
            re.IGNORECASE,
        ),
    ),
    (
        "ablation",
        re.compile(
            r"ablation|sensitivity|robustness|variance|analysis$", re.IGNORECASE
        ),
    ),
    (
        "analysis",
        re.compile(
            r"^analysis|^discussion|interpretation|insight|"
            r"case stud|error analysis|visualization|understanding",
            re.IGNORECASE,
        ),
    ),
    (
        "limitations",
        re.compile(
            r"limitation|negative result|failure|future work|outlook|open problem|"
            r"societal impact|broader impact|ethic|safety|risk|bias|impact statement",
            re.IGNORECASE,
        ),
    ),
    (
        "conclusion",
        re.compile(
            r"conclusion|concluding|summary|takeaway|wrap.up|"
            r"final remark",
            re.IGNORECASE,
        ),
    ),
    (
        "acknowledgments",
        re.compile(
            r"acknowledg|funding|author contribution|"
            r"competing interest|declaration",
            re.IGNORECASE,
        ),
    ),
    (
        "reproducibility",
        re.compile(
            r"reproducib|code release|data availab|"
            r"ethics statement|checklist",
            re.IGNORECASE,
        ),
    ),
    ("references", re.compile(r"reference|bibliograph|works cited", re.IGNORECASE)),
    (
        "appendix",
        re.compile(
            r"appendix|supplement|appendices|extended|"
            r"additional|proof of|extra|supporting",
            re.IGNORECASE,
        ),
    ),
]

NUM_PREFIX_RX = re.compile(r"^(?:[ivxlc]+\.?|\d+\.?|[a-z]\.?|\d+\.\d+(?:\.\d+)*\.?)\s+")


def canon_section(raw: str) -> str:
    t = detex(raw)[0].strip().lower()
    t = NUM_PREFIX_RX.sub("", t).strip()
    t = re.sub(r"\s+", " ", t)
    for bucket, rx in BUCKET_RULES:
        if rx.search(t):
            return bucket
    return "other"


# ---------------- 单篇分析 ----------------


def analyze_paper(pdir: Path) -> dict:
    pid = pdir.name
    ext = pdir / "extracted"
    if not ext.is_dir():
        return {"arxiv_id": pid, "status": "no_extracted"}
    main = find_main_tex(ext)
    if main is None:
        return {"arxiv_id": pid, "status": "no_main"}
    try:
        full, unresolved = expand_inputs(ext, main)
    except Exception as e:
        return {"arxiv_id": pid, "status": "expand_error", "error": str(e)}
    text = strip_comments(full)
    bm = BEGIN_DOC.search(text)
    if not bm:
        return {"arxiv_id": pid, "status": "no_document"}
    em = None
    for _em in END_DOC.finditer(text):
        em = _em
    body = text[bm.end() : em.start() if em else len(text)]

    # abstract
    am = ABSTRACT_RX.search(body)
    abstract_words = 0
    if am:
        abstract_words = count_words(detex(am.group(1))[0])

    # 边界点扫描：section / appendix / references 标记
    marks: list[tuple[int, str, dict]] = []
    for m in SEC_RX.finditer(body):
        title, _end = _grab_brace(body, m.end() - 1)
        marks.append(
            (
                m.start(),
                "section",
                {
                    "level": {"section": 1, "subsection": 2, "subsubsection": 3}[
                        m.group(1)
                    ],
                    "title": title,
                    "star": bool(m.group(2)),
                    "end": _end,
                },
            )
        )
    marks.extend((m.start(), "appendix", {}) for m in APPENDIX_CMD_RX.finditer(body))
    marks.extend((m.start(), "refs", {}) for m in REFS_RX.finditer(body))
    marks.sort(key=lambda x: x[0])

    sections: list[dict] = []
    cur_appendix = False
    pending: dict | None = None  # 上一个 section 待收尾
    preface_end = body[: marks[0][0]] if marks else body
    preface_words = count_words(detex(preface_end)[0])

    def _close_section(end_pos: int, start_pos: int, meta: dict) -> None:
        raw_span = body[start_pos:end_pos]
        w, ch, capw = detex_count(raw_span)
        title = meta.get("title", "")
        bucket = meta.get("force_bucket") or canon_section(title)
        if meta.get("in_appendix") and bucket == "other":
            bucket = "appendix"
        sections.append(
            {
                "raw": meta.get("raw") or detex(title)[0].strip()[:120] or "(untitled)",
                "bucket": bucket,
                "level": meta["level"],
                "order": len(sections) + 1,
                "words": w,
                "chars": ch,
                "caption_words": capw,
                # 与 PDF 臂同口径：appendix 段后的 refs 只计 refs_words 不再双计 appendix
                "appendix": meta["in_appendix"] and bucket != "references",
                "unnumbered": meta["star"],
            }
        )

    for pos, kind, meta in marks:
        if pending is not None:
            _close_section(pos, pending["content_start"], pending)
            pending = None
        if kind == "appendix":
            cur_appendix = True
            continue
        if kind == "refs":
            pending = {
                "level": 0,
                "star": True,
                "title": "",
                "raw": "(bibliography)",
                "force_bucket": "references",
                "in_appendix": cur_appendix,
                "content_start": pos,
            }
            continue
        meta["in_appendix"] = cur_appendix
        meta["content_start"] = meta.pop("end")
        pending = meta
    if pending is not None:
        _close_section(len(body), pending["content_start"], pending)

    n_sec = sum(1 for s in sections if s["level"] == 1)
    body_words = sum(
        s["words"]
        for s in sections
        if not s["appendix"] and s["bucket"] != "references"
    )
    appendix_words = sum(
        s["words"] for s in sections if s["appendix"] or s["bucket"] == "appendix"
    )
    refs_words = sum(s["words"] for s in sections if s["bucket"] == "references")
    # 参考文献条数：bbl \bibitem 优先，退 .bib @entry
    n_bib = len(re.findall(r"\\bibitem", body))
    if n_bib == 0:
        for bib in ext.rglob("*.bib"):
            with suppress(OSError):
                n_bib += len(re.findall(r"@\w+\s*\{", read_tex(bib)))
    status = "ok" if n_sec >= 1 else "no_sections"
    return {
        "arxiv_id": pid,
        "status": status,
        "main_tex": str(main.relative_to(ext)),
        "unresolved_inputs": unresolved,
        "preface_words": preface_words,
        "abstract_words": abstract_words,
        "n_top_sections": n_sec,
        "body_words": body_words,
        "appendix_words": appendix_words,
        "refs_words": refs_words,
        "n_bib_items": n_bib,
        "sections": sections,
    }


# ---------------- 主流程 ----------------


def paper_dirs(corpus: Path, ids: set[str] | None) -> list[Path]:
    out = []
    for d in sorted(corpus.iterdir()):
        if not d.is_dir() or d.name in ("nominations", "__pycache__"):
            continue
        if (d / "extracted").is_dir():
            if ids is None or d.name in ids:
                out.append(d)
        else:
            for s in sorted(d.iterdir()):
                if s.is_dir() and (s / "extracted").is_dir():
                    rid = f"{d.name}/{s.name}"
                    if ids is None or rid in ids:
                        out.append(s)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", help="只分析名单内 id（每行一个 arxiv_id）")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    corpus = Path(a.corpus)
    ids = None
    if a.ids:
        ids = {line.strip() for line in open(a.ids) if line.strip()}
    dirs = paper_dirs(corpus, ids)
    if a.limit:
        dirs = dirs[: a.limit]
    outp = Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)

    from collections import Counter

    stat = Counter()
    n_done = 0
    done_ids = set()
    for r in benchlib.read_jsonl(outp):  # 断点续跑（缺文件/坏行容忍）
        done_ids.add(r["arxiv_id"])
    with outp.open("a") as f:
        for d in dirs:
            rid = d.name if (d / "extracted").is_dir() else f"{d.parent.name}/{d.name}"
            if rid in done_ids:
                continue
            try:
                rec = analyze_paper(d)
            except Exception as e:
                rec = {
                    "arxiv_id": rid,
                    "status": "crash",
                    "error": f"{type(e).__name__}: {e}",
                }
            rec["arxiv_id"] = rid
            stat[rec["status"]] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_done += 1
            if n_done % 500 == 0:
                f.flush()
                log(f"{n_done} analyzed | {dict(stat)}")
    log(f"done: {n_done} analyzed | {dict(stat)} -> {outp}")


if __name__ == "__main__":
    main()
