#!/usr/bin/env python3
"""M1 literal-residue scout v3：译文 cell 内悬挂的 in_arg 字面段。

每行剥离：% 注释、\\begin{env}[opt]/\\end{env}、\\\\[opt]、\\cmd[opt]{arg}x3、
\\cmd 本体、$..$ 数学（含未闭合尾）。cell 文本 = 这是译文 marker 间切片。
残留签名：graphicx kv 键、[dimen]/{dimen}/{n}{*}/{*} 括片、[位置]孤括号、
裸 dimen 原子（glue/assign 尾参类——记 dim 备人工复核）。
"""
import json
import re
import sys
from pathlib import Path

MARK = "这是译文"
COMMENT_RX = re.compile(r"(?<!\\)%.*")
MATH_RX = re.compile(r"\$[^$]*\$|\$[^$]*$")
ENV_TAG_RX = re.compile(r"\\(?:begin|end)\s*\{[^{}\n]*\}\s*(?:\[[^\[\]\n]*\])?")
BSBS_RX = re.compile(r"\\\\\*?\s*(?:\[[^\[\]\n]*\])?")
CMD_RX = re.compile(
    r"\\[a-zA-Z@]+\*?\s*(?:\[[^\[\]\n]*\])?\s*(?:\{[^{}\n]*\}\s*){0,3}"
    r"|\\[^a-zA-Z@]"
)
KV_RX = re.compile(
    r"(?<![\\a-zA-Z])(?:origin|width|height|totalheight|scale|xscale|yscale|"
    r"angle|trim|viewport|bb|bbllx|bblly|bburx|bbury|natwidth|natheight|"
    r"hiresbb|clip|keepaspectratio|pagebox|interpolate|draft|page)\s*="
)
FRAG_RX = re.compile(
    r"[\[\{]\s*-?[0-9]+\.?[0-9]*\s*(?:true\s+)?"
    r"(?:pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu|zh|zw)\s*[\]\}]"
    r"|\{\s*\d+\s*\}\s*\{\s*\*?\s*\}"
    r"|\{\s*\*\s*\}"
)
POS_RX = re.compile(r"(?<![\\a-zA-Z{])\[(?:[tcb]|[TBLRH]{1,4}|[hlr]{1,3})\]")
DIMEN_RX = re.compile(
    r"(?<![\\$a-zA-Z0-9.])-?[0-9]+\.?[0-9]*\s*(?:true\s+)?"
    r"(?:pt|pc|bp|cm|mm|dd|cc|sp|em|ex|mu)\b"
)


def main(roots: list[str]) -> None:
    for root in roots:
        for p in sorted(Path(root).rglob("*.tex")):
            s = str(p)
            if "/zh/" not in s and "/build-zh/" not in s:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if MARK not in line:
                    continue
                line2 = COMMENT_RX.sub("", line)
                for seg in line2.split(MARK)[1:]:
                    c = MATH_RX.sub(" ", seg)
                    c = ENV_TAG_RX.sub(" ", c)
                    c = BSBS_RX.sub(" ", c)
                    c = CMD_RX.sub(" ", c)
                    rem = c
                    kinds = []
                    if KV_RX.search(rem):
                        kinds.append("kv")
                    if FRAG_RX.search(rem):
                        kinds.append("frag")
                    if POS_RX.search(rem):
                        kinds.append("pos")
                    if DIMEN_RX.search(rem):
                        kinds.append("dim")
                    if kinds:
                        print(
                            json.dumps(
                                {
                                    "file": s,
                                    "line": ln,
                                    "kinds": kinds,
                                    "rem": rem.strip()[:140],
                                },
                                ensure_ascii=False,
                            )
                        )
                        break


if __name__ == "__main__":
    main(sys.argv[1:] or ["bench/results/stagerun-loop1-2026-09-16/work"])
