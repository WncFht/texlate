import json, sys, time
from pathlib import Path
sys.path.insert(0, "/home/fanghaotian/src/texlate/bench/py")
import fixloop_bench as flb
from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import Ruleset, fixloop

BASE = Path("/home/fanghaotian/src/texlate/bench/results/verifier-batch8-2026-09-17")
wid = BASE / "work" / "synth-belt"
splice = wid / "splice"
texmf = wid / "_texmf"
flb._init_usertree(texmf)
eng = flb._NoSandbox(XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET))
idx = flb._index()
if idx is not None:
    eng.filemap = idx.query
rs = Ruleset.load()
cell = fixloop(splice, eng, ruleset=rs, engine_name="xelatex", corpus_id="synth-belt",
               cond="fixloop", runner=flb._texmf_runner(texmf), llm_hook=None,
               compile_timeout=120.0)
print(json.dumps({k: cell.get(k) for k in ("verdict", "rounds", "actions")}, ensure_ascii=False, indent=1))
