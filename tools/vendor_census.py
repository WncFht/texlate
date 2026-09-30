#!/usr/bin/env python3
"""vendor/ 普查 + 可达性扫描 → jsonl——``vendor/MANIFEST.md`` 的生成数据源。

走 ``src/texlate/compile/fixloop/vendor/{files,shims,stubs}``，解析每件首个
\\ProvidesX 头，继而在 fixloop/**/*.py、fixloop/rules/*.yaml 与 compile/**/*.py
grep basename 引用，并扫描 vendored 兄弟件内部互相装载（stem/basename 双形
+ 构造名补丁）。分类：a=代码/规则点名、b=basename 可达（lib 库存/twin 字节
拷贝/dep 兄弟装载）、c=孤儿。

用法：``python3 tools/vendor_census.py [out.jsonl]``——缺省写
``tmp/vendor-census-<今天>.jsonl``。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src/texlate/compile/fixloop/vendor"
FIXLOOP = ROOT / "src/texlate/compile/fixloop"
COMPILE = ROOT / "src/texlate/compile"
_TODAY = datetime.now().astimezone().date()  # 本地日期戳（run 目录同约定）
OUT = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else ROOT / "tmp" / f"vendor-census-{_TODAY:%Y-%m-%d}.jsonl"
)

PROVIDES_RE = re.compile(
    r"\\Provides(?:Package|Class|File|ExplPackage|ExplClass|ExplFile)"
    r"(?:\s|%[^\n]*)*\{([^}]*)\}"
    r"(?:\s|%[^\n]*)*(?:\[([^\]]{0,120})\]|\{([^}]{0,120})\})?"
)


# files whose bytes are not utf-8 text (binary font metrics etc.)
def read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def provides(path: Path) -> tuple[str | None, str | None]:
    t = read_text(path)
    if t is None:
        return None, None
    m = PROVIDES_RE.search(t)
    if not m:
        return None, None
    name = m.group(1).strip()
    ver = (m.group(2) or m.group(3) or "").strip()
    ver = re.sub(r"\s+", " ", ver)
    return name, ver or None


# ---- haystack: consumer code/rules ----
def haystack_files() -> list[Path]:
    files: list[Path] = []
    files += sorted(FIXLOOP.glob("*.py"))
    files += sorted((FIXLOOP / "rules").glob("*.yaml"))
    files += sorted(COMPILE.rglob("*.py"))
    # dedupe preserving order
    seen: set[Path] = set()
    uniq = []
    for f in files:
        if f not in seen and f.is_file():
            seen.add(f)
            uniq.append(f)
    return uniq


HAY = [
    (f, f.read_text(encoding="utf-8", errors="replace").splitlines())
    for f in haystack_files()
]


def refs_in_code(basename: str) -> list[str]:
    """file:line hits of literal basename in consumer code/rules."""
    hits: list[str] = []
    for f, lines in HAY:
        if not str(f).startswith(str(FIXLOOP)) and not str(f).startswith(str(COMPILE)):
            continue
        for i, line in enumerate(lines, 1):
            if basename in line:
                rel = f.relative_to(ROOT).as_posix()
                hits.append(f"{rel}:{i}")
    return hits


# ---- vendor inventory ----
entries = []
for tier in ("files", "shims", "stubs"):
    for p in sorted((VENDOR / tier).iterdir()):
        if not p.is_file():
            continue
        data = p.read_bytes()
        name, ver = provides(p)
        if name:
            # docstrip 续行注释面：`{%\nltxutil%\n.sty%` → ltxutil.sty
            name = re.sub(r"%|\s", "", name) or None
        entries.append(
            {
                "tier": tier,
                "path": p.relative_to(VENDOR).as_posix(),
                "basename": p.name,
                "stem": p.stem,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "provides_name": name,
                "provides_ver": ver,
                "_abspath": p,
            }
        )

by_base = {e["basename"]: e for e in entries}
by_stem: dict[str, list[dict]] = {}
for e in entries:
    by_stem.setdefault(e["stem"], []).append(e)

# sibling references: does another vendored file mention basename or stem?
WORD = lambda s: re.compile(
    r"(?<![A-Za-z0-9_.-])" + re.escape(s) + r"(?![A-Za-z0-9_.-])"
)

for e in entries:
    base = e["basename"]
    stem = e["stem"]
    sib_hits: list[str] = []
    for o in entries:
        if o is e:
            continue
        t = read_text(o["_abspath"])
        if t is None:
            continue
        if base in t:
            sib_hits.append(o["path"])
            continue
        # stem form (e.g. \input pst-plot / \usepackage{pst-xkey})
        if stem and len(stem) >= 4 and WORD(stem).search(t):
            sib_hits.append(o["path"] + f"(stem:{stem})")
    e["sibling_refs"] = sorted(set(sib_hits))

# byte-identical same-stem twin (extensionless copy of X.tex)
by_stem_sha: dict[tuple[str, str], list[dict]] = {}
for e in entries:
    by_stem_sha.setdefault((e["stem"], e["sha256"]), []).append(e)
for e in entries:
    twins = [
        o["basename"]
        for o in by_stem_sha.get((e["stem"], e["sha256"]), [])
        if o is not e
    ]
    e["twin_of"] = twins[0] if twins and e["basename"] == e["stem"] else None

# constructed-name sibling edges the literal scan cannot see:
#   jabbrv.sty:496 \InputIfFileExists{jabbrv-ltwa-\jabbrv@lang.ldf}
EXTRA_SIB = {"jabbrv-ltwa-en.ldf": "files/jabbrv.sty:496"}
for e in entries:
    if e["basename"] in EXTRA_SIB:
        e["sibling_refs"].append(EXTRA_SIB[e["basename"]] + "(constructed)")

for e in entries:
    e["code_refs"] = refs_in_code(e["basename"])
    # also search for stem when basename is extensionless or stem is a load name
    # (payloads request stems: \usepackage{quantikz} → quantikz.sty). Stems
    # are NOT class-(a) evidence unless the basename itself is absent — stems
    # are how the basename lookup is reached, so they confirm (b) not (a).
    # We still record stem hits separately for context.
    stem = e["stem"]
    stem_hits: list[str] = []
    if stem != e["basename"]:
        pat = WORD(stem)
        for f, lines in HAY:
            for i, line in enumerate(lines, 1):
                if e["basename"] in line:
                    continue
                if pat.search(line):
                    rel = f.relative_to(ROOT).as_posix()
                    stem_hits.append(f"{rel}:{i}")
    e["stem_refs"] = stem_hits


# classify
def classify(e: dict) -> tuple[str, str]:
    if e["code_refs"]:
        return "a", ";".join(e["code_refs"][:4])
    if e["twin_of"]:
        return "b", f"twin:{e['twin_of']}"
    if e["sibling_refs"]:
        return "b", "sibling→" + ",".join(e["sibling_refs"][:4])
    if e["provides_name"]:
        return "b", "library stock (\\ProvidesX)"
    # plausible library item: standard TeX-loadable extension means a
    # missing_file payload of this basename can legitimately occur
    if e["basename"].rsplit(".", 1)[-1] in (
        "sty",
        "cls",
        "tex",
        "def",
        "cfg",
        "clo",
        "ldf",
        "rtx",
        "con",
        "fd",
        "tfm",
        "mf",
        "bbx",
        "cbx",
        "lbx",
        "map",
        "enc",
        "pro",
    ):
        return "b", "library stock (no header)"
    return "c", "no refs, no header, non-loadable name"


for e in entries:
    cls, ev = classify(e)
    e["class"] = cls
    e["evidence"] = ev
    e.pop("_abspath")

with OUT.open("w") as fh:
    for e in entries:
        fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

# summary
from collections import Counter

c = Counter((e["tier"], e["class"]) for e in entries)
for k in sorted(c):
    print(k, c[k])
print("orphans:")
for e in entries:
    if e["class"] == "c":
        print(" ", e["path"], e["bytes"], repr(e["provides_name"]))
print("provides-name != stem:")
for e in entries:
    n = e["provides_name"]
    if n and n != e["stem"]:
        print(" ", e["path"], "stem=", e["stem"], "provides=", n)
print("written", OUT)
