#!/usr/bin/env python3
"""scratch-rules.yaml 构建: 现行 rules.yaml + fragment 条目替换.

fragment 文件注释行后的 `acm_proc_article-sp.cls:` map 即替换件 (缩进对齐
shim_map 槽位 10 空格).
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RULES = Path("/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml")
OLD = '          acm_proc_article-sp.cls: { loads: "acmart", needs: ["acmart.cls"] }'

frag_lines = [
    ln
    for ln in (BASE / "rules-fragment.yaml").read_text().splitlines()
    if ln.strip() and not ln.lstrip().startswith("#")
]
entry = "\n".join("          " + ln for ln in frag_lines)

text = RULES.read_text()
assert text.count(OLD) == 1, "old entry not found exactly once"
out = text.replace(OLD, entry)
(BASE / "scratch-rules.yaml").write_text(out)

# 装载冒烟: Ruleset 校验过才算数
sys.path.insert(0, "/home/fanghaotian/src/texlate/bench/py")
from texlate.compile.fixloop import Ruleset

rs = Ruleset.load(BASE / "scratch-rules.yaml")
shim = next(r for r in rs.rules if r.id == "legacy_pkg_shim")
spec = shim.raw["action"]["params"]["shim_map"]["acm_proc_article-sp.cls"]
assert spec["needs"] == ["acmart.cls"]
assert "\\titlenote" in spec["body"] and "\\alignauthor" in spec["body"]
print("scratch-rules.yaml OK, body head:", spec["body"][:90].replace("\n", "|"))
