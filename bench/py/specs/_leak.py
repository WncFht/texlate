"""LEAK_PATTERNS — the six leak-regex families (docs/spec/corpus.md 泄漏判据).

Single source for the "unprotected LaTeX leaked into a translatable chunk"
detector: a chunk that matches ANY family counts as a leak; per-family
hit counts ride metrics. Moved out of ``parsebench.py`` so the
parsebench spec and quality_proxies share the exact
口径 — copy drift between them would silently fork the corpus 0.040%
baseline.
"""

from __future__ import annotations

import re

LEAK_PATTERNS = {
    "dollar": re.compile(r"\$"),
    "cite_family": re.compile(r"\\cite[a-zA-Z]*"),
    "ref_family": re.compile(r"\\(?:eq|auto|c|page|name|sub)?ref(?![a-zA-Z])"),
    "begin_env": re.compile(r"\\begin\{"),
    "conditional": re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])"),
    "input_include": re.compile(r"\\(?:input|include)\{"),
}
