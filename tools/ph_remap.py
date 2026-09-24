"""rekey 遗留 ph id 修复：旧编号译文 → 新编号（reseg_rekey 补网）。

reseg_rekey 早期版本携带译文不重映射 ph id——分段器重排序号后
``[[MATH_76]]`` 族查无实体，splice 留字面进 zh 成品（t_f748 实证）。
本工具读 ``tmp/rekey-<tid>.json`` 备份（旧 chunks 含旧 src_text），
按 chunk_id 对现 DB 行做**解析序逐位**映射并回写 translation/dual。

失配即弃映（宁字面不冤映）；无备份/无漂移 = 幂等空转。
用法：.venv/bin/python tools/ph_remap.py <task_id>...
"""

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from texlate.pipecore import delivered_db  # noqa: E402

ROOT = Path.home() / ".texlate"
DB = ROOT / "texlate.db"
TASKS = ROOT / "tasks"

_PH_TOK_RX = re.compile(r"\[\[[A-Z]+_\d+\]\]")


def _type(t: str) -> str:
    return t[2 : t.index("_")]


def _remap(old_src: str, new_src: str, tr: str) -> str:
    """解析序逐位 zip（同 ``reseg_rekey._remap_ph_ids`` 口径）。"""
    old_phs = _PH_TOK_RX.findall(old_src or "")
    new_phs = _PH_TOK_RX.findall(new_src or "")
    if not old_phs or len(old_phs) != len(new_phs):
        return tr
    remap: dict[str, str] = {}
    for o, n in zip(old_phs, new_phs, strict=True):
        if _type(o) != _type(n):
            return tr
        remap[o] = n
    return _PH_TOK_RX.sub(lambda m: remap.get(m.group(0), m.group(0)), tr)


def remap_task(db: sqlite3.Connection, tid: str) -> str:
    bp = Path("tmp") / f"rekey-{tid}.json"
    if not bp.is_file():
        return "skip: 无 rekey 备份"
    old_by_cid = {
        r["chunk_id"]: r
        for r in json.loads(bp.read_text(encoding="utf-8"))["chunks"]
    }
    cur = [
        dict(zip(cols, r, strict=True))
        for r in db.execute(
            "select seq, chunk_id, src_text, status, translation from chunks"
            " where task_id=? order by seq",
            (tid,),
        )
        for cols in [("seq", "chunk_id", "src_text", "status", "translation")]
    ]
    n_fix = n_skip = 0
    with db:
        for r in cur:
            tr = r["translation"]
            if not isinstance(tr, str) or "[[" not in tr:
                continue
            old = old_by_cid.get(r["chunk_id"])
            if old is None:
                n_skip += 1  # rekey 新增块——无旧编号可映
                continue
            fixed = _remap(old["src_text"], r["src_text"], tr)
            if fixed != tr:
                db.execute(
                    "update chunks set translation=? where task_id=? and chunk_id=?",
                    (fixed, tid, r["chunk_id"]),
                )
                n_fix += 1
        dual_p = TASKS / tid / "dual.json"
        if n_fix and dual_p.is_file():
            dual = json.loads(dual_p.read_text(encoding="utf-8"))
            zmap = {
                r[0]: (r[1], r[2])
                for r in db.execute(
                    "select seq, status, translation from chunks where task_id=?",
                    (tid,),
                )
            }
            for c in dual.get("chunks") or []:
                hit = zmap.get(c.get("seq"))
                if hit:
                    st, tr_ = hit
                    c["status"] = str(st)
                    c["zh"] = (
                        tr_
                        if isinstance(tr_, str) and delivered_db(st, tr_)
                        else ""
                    )
            dual_p.write_text(
                json.dumps(dual, ensure_ascii=False), encoding="utf-8"
            )
        db.execute(
            "update tasks set updated_at=? where id=?", (time.time(), tid)
        )
    return f"remapped {n_fix} chunks (skip {n_skip} 无旧行)"


def main() -> None:
    db = sqlite3.connect(str(DB))
    for tid in sys.argv[1:]:
        t0 = time.time()
        try:
            r = remap_task(db, tid)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            r = f"CRASH {type(e).__name__}: {e}"
        print(f"{tid}: {r} [{time.time() - t0:.0f}s]", flush=True)
    db.close()


if __name__ == "__main__":
    main()
