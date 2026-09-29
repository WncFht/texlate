"""v5 臂逐篇账本：网关逐调用统计 + task_usage 权威总额，落 tmp/v5-ledger.json。

口径:texlate-v5 夜跑在 key_hash=268cd341e843e55f(=sha256("240127")[:16]);
窗取 tmp/v5-arm-wins.json 的 t0_hms/t1_hms(当日起止,严格相等 task_usage
对账校验:Σ(in+cr)==prompt_tokens,calls 一致才算干净窗)。
输出每篇:calls/in/cr/out(网关)+in_p50/in_max/cr_max/hit_calls+tu_calls/
tu_prompt/tu_completion/tu_latency+chunks/doc_ph+status/secs。
"""

import json
import re
import sqlite3
import statistics as st
import sys
from pathlib import Path

import _env

GW = Path.home() / ".local/state/devin-2api/devin-2api.db"
TX = _env.DB
WINS = _env.REPO / "tmp/v5-arm-wins.json"
OUT = _env.REPO / "tmp/v5-ledger.json"
KEY = "268cd341e843e55f"
PH_RX = re.compile(r"\[\[([A-Z]+)_(\d+)\]\]")
BASE = 1790553600  # 2026-09-28 00:00 UTC


def ms(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return (BASE + h * 3600 + m * 60 + s - 8 * 3600) * 1000


def main() -> None:
    wins = json.loads(WINS.read_text())
    gw = sqlite3.connect(f"file:{GW}?mode=ro", uri=True)
    tx = sqlite3.connect(f"file:{TX}?mode=ro", uri=True)
    out = {}
    for pid_raw, w in wins.items():
        pid = pid_raw.split("v")[0]
        tid = w.get("task_id")
        rec = {"task_id": tid, "status": w.get("status"), "secs": w.get("secs")}
        if not tid or not w.get("t0_hms"):
            out[pid] = rec
            continue
        # epoch 优先；缺时回退 hms，跨零点篇 t1<t0 则 +86400s
        t0_ms = int(w["t0"] * 1000) if w.get("t0") else ms(w["t0_hms"])
        t1_ms = int(w["t1"] * 1000) if w.get("t1") else ms(w["t1_hms"])
        if t1_ms < t0_ms:
            t1_ms += 86400_000
        rows = gw.execute(
            "select input_tokens, cache_read_tokens, output_tokens from logs"
            " where api='openai-chat' and key_hash=? and time>=? and time<=?",
            (KEY, t0_ms, t1_ms),
        ).fetchall()
        ins = [r[0] for r in rows]
        crs = [r[1] for r in rows]
        rec.update(
            calls=len(rows),
            input=sum(ins),
            cache_read=sum(crs),
            output=sum(r[2] for r in rows),
            in_p50=int(st.median(ins)) if ins else 0,
            in_max=max(ins) if ins else 0,
            cr_max=max(crs) if crs else 0,
            hit_calls=sum(1 for c in crs if c > 0),
        )
        tu = tx.execute(
            "select calls, prompt_tokens, completion_tokens, latency_s"
            " from task_usage where task_id=?",
            (tid,),
        ).fetchone()
        if tu:
            rec.update(
                tu_calls=tu[0],
                tu_prompt=tu[1],
                tu_completion=tu[2],
                tu_latency_s=round(tu[3], 1),
            )
            rec["window_balanced"] = (
                rec["input"] + rec["cache_read"] == tu[1] and rec["calls"] == tu[0]
            )
        ch = tx.execute(
            "select count(*),"
            " sum(case when translation is not null then 1 else 0 end)"
            " from chunks where task_id=?",
            (tid,),
        ).fetchone()
        doc_ph = tx.execute(
            "select src_text from chunks where task_id=?", (tid,)
        ).fetchall()
        ids = set()
        for (s,) in doc_ph:
            if s:
                ids |= {f"{t}_{n}" for t, n in PH_RX.findall(s)}
        rec.update(chunks=ch[0], translated=ch[1], doc_ph=len(ids))
        out[pid] = rec
        print(pid, json.dumps(rec, ensure_ascii=False))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    sys.exit(main())
