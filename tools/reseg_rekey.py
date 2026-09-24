"""存量任务 chunk 重键：分段器演进致 rescan≠dual 时对齐到当前 chunk 流。

remark_rebuild 的 parity 闸拒收错位任务（宁缺勿滥）——本工具先把
chunks 表/dual.json 重键到当前 rescan 流，使 remark 放行。

匹配优先级（携带 status/translation/error/attempts/warnings）：
  1. (src_file, byte_start, byte_end) 精确 —— span 未动的块保原 chunk_id
  2. 同文件规范化 src_text 唯一匹配 —— span 漂移的块
新块 status=pending；孤儿旧行随 DELETE 删除。tasks.total/done/failed
重算。dual.json chunks 行按 _dual_chunk_row 同构重写（en=content、
zh=delivered 口径、kind/status/chunk_id 全键）。

安全：单事务；旧行+旧 dual 先备份 tmp/rekey-<tid>.json。
用法：.venv/bin/python tools/reseg_rekey.py [task_id...]（缺省=parity 失配全量）
"""

import json
import re
import sqlite3
import sys
import time
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, "src")
from texlate.latex.api import scan_tex_tree  # noqa: E402
from texlate.pipecore import delivered_db, ran_front_matter  # noqa: E402
from texlate.server.upload import pdf_pages  # noqa: E402
from texlate.server.worker._common import chunk_db_id  # noqa: E402
from texlate.xlat.prompts import normalize_kind  # noqa: E402

ROOT = Path.home() / ".texlate"
DB = ROOT / "texlate.db"
TASKS = ROOT / "tasks"

_WS = re.compile(r"\s+")
_PH_TOK_RX = re.compile(r"\[\[[A-Z]+_\d+\]\]")


def _norm(t: str) -> str:
    return _WS.sub("", t or "")


def _remap_ph_ids(old_src: str, new_src: str, tr: str | None) -> str | None:
    """携带译文的旧 ph id 重映射到新编号。

    分段器演进重排 ph 序号（``[[MATH_76]]``→``[[MATH_78]]``）而携带译文
    仍持旧 id——不映射则译文 ph 查无实体留字面进成品（t_f748 实证 11
    处 ``[[MATH_76]]`` 直印 zh.pdf）。映射按**解析序**逐位 zip（旧 src
    第 i 个 ph ↔ 新 src 第 i 个 ph），译文内乱序引用同 id 一映射——
    逐位 type 前缀全等才生效，失配即弃映留原文（宁字面不冤映）。
    """
    if not tr:
        return tr
    old_phs = _PH_TOK_RX.findall(old_src or "")
    new_phs = _PH_TOK_RX.findall(new_src or "")
    if not old_phs or len(old_phs) != len(new_phs):
        return tr
    remap: dict[str, str] = {}
    for o, n in zip(old_phs, new_phs, strict=True):
        if o[2 : o.index("_")] != n[2 : n.index("_")]:
            return tr
        remap[o] = n
    return _PH_TOK_RX.sub(lambda m: remap.get(m.group(0), m.group(0)), tr)


def _rescan(tdir: Path, meta: dict) -> list[tuple[str, object]]:
    fm = ran_front_matter(meta["options"])
    tree = scan_tex_tree(tdir / "base", front_matter=fm)
    return [(rel, c) for _f, rel, res in tree.parsed for c in res.chunks]


def rekey_task(db: sqlite3.Connection, tid: str) -> str:
    tdir = TASKS / tid
    meta_r = db.execute(
        "select main_tex, options_json from tasks where id=?", (tid,)
    ).fetchone()
    if not meta_r or not meta_r[0]:
        return "skip: 无任务行/main_tex"
    if not (tdir / "base").is_dir():
        return "skip: 无 base/"
    meta = {"main_tex": meta_r[0], "options": json.loads(meta_r[1] or "{}")}
    flat = _rescan(tdir, meta)
    dual_p = tdir / "dual.json"
    dual = json.loads(dual_p.read_text(encoding="utf-8")) if dual_p.is_file() else {}
    old_dual_chunks = [c for c in dual.get("chunks") or [] if isinstance(c.get("seq"), int)]
    if len(flat) == len(old_dual_chunks):
        return f"skip: chunk 数已齐（{len(flat)}）——直接走 remark_rebuild"

    old = [
        dict(zip(cols, r, strict=True))
        for r in db.execute(
            "select seq, chunk_id, src_file, byte_start, byte_end, kind,"
            " src_text, status, translation, error_code, attempts, warnings"
            " from chunks where task_id=? order by seq",
            (tid,),
        )
        for cols in [
            ("seq", "chunk_id", "src_file", "byte_start", "byte_end", "kind",
             "src_text", "status", "translation", "error_code", "attempts",
             "warnings")
        ]
    ]

    by_span = {(r["src_file"], r["byte_start"], r["byte_end"]): r for r in old}
    by_text: dict[tuple[str, str], list[dict]] = {}
    for r in old:
        by_text.setdefault((r["src_file"], _norm(r["src_text"])), []).append(r)

    used: set[int] = set()
    carry: list[dict | None] = []
    for rel, c in flat:
        hit = by_span.get((rel, c.span.start, c.span.end))
        if hit is not None and id(hit) not in used:
            carry.append(hit)
            used.add(id(hit))
            continue
        cands = [
            r
            for r in by_text.get((rel, _norm(c.content)), [])
            if id(r) not in used
        ]
        if len(cands) == 1:
            carry.append(cands[0])
            used.add(id(cands[0]))
        elif cands:  # 多候选取 byte_start 最近者
            best = min(cands, key=lambda r: abs(r["byte_start"] - c.span.start))
            carry.append(best)
            used.add(id(best))
        else:
            carry.append(None)

    n_exact = sum(
        1
        for (rel, c), r in zip(flat, carry, strict=True)
        if r is not None
        and (r["src_file"], r["byte_start"], r["byte_end"])
        == (rel, c.span.start, c.span.end)
    )
    n_text = sum(1 for r in carry if r is not None) - n_exact
    orphans = [r for r in old if id(r) not in used]
    print(
        f"  rekey {tid}: new={len(flat)} old={len(old)} "
        f"exact={n_exact} text={n_text} orphan={len(orphans)} "
        f"insert={sum(1 for r in carry if r is None)}"
    )

    backup = {
        "tid": tid,
        "ts": time.time(),
        "chunks": old,
        "dual_chunks": old_dual_chunks,
    }
    bp = Path("tmp") / f"rekey-{tid}.json"
    bp.parent.mkdir(exist_ok=True)
    bp.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")

    rows = []
    for seq, ((rel, c), r) in enumerate(zip(flat, carry, strict=True)):
        row = {
            "seq": seq,
            "chunk_id": chunk_db_id(rel, c.span.start, c.span.end),
            "src_file": rel,
            "byte_start": c.span.start,
            "byte_end": c.span.end,
            "kind": normalize_kind(c.context),
            "src_text": c.content,
            "status": "pending",
            "translation": None,
            "error_code": None,
            "attempts": 0,
            "warnings": None,
        }
        if r is not None:
            for k in ("status", "error_code", "attempts", "warnings"):
                row[k] = r[k]
            row["translation"] = _remap_ph_ids(
                r["src_text"], c.content, r["translation"]
            )
        rows.append(row)

    with db:  # 单事务
        db.execute("delete from chunks where task_id=?", (tid,))
        db.executemany(
            "insert into chunks (task_id, seq, chunk_id, src_file, byte_start,"
            " byte_end, kind, src_text, status, translation, error_code,"
            " attempts, warnings) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    tid,
                    r["seq"],
                    r["chunk_id"],
                    r["src_file"],
                    r["byte_start"],
                    r["byte_end"],
                    r["kind"],
                    r["src_text"],
                    r["status"],
                    r["translation"],
                    r["error_code"],
                    r["attempts"],
                    r["warnings"],
                )
                for r in rows
            ],
        )
        n_done = sum(
            1 for r in rows if r["status"] not in ("pending", "translating")
        )
        n_fail = sum(1 for r in rows if r["status"] == "failed")
        db.execute(
            "update tasks set total_chunks=?, done_chunks=?, failed_chunks=?,"
            " updated_at=? where id=?",
            (len(rows), n_done, n_fail, time.time(), tid),
        )

    # dual.json chunks 重写（_dual_chunk_row 同构；documents/alignment 留给
    # remark_rebuild 重建——重编译后 pdf 字节变、sha/pages 必过期）。
    if dual_p.is_file():
        dual["chunks"] = [
            {
                "seq": r["seq"],
                "chunk_id": r["chunk_id"],
                "src_file": r["src_file"],
                "en": r["src_text"],
                "zh": r["translation"]
                if delivered_db(r["status"], r["translation"])
                and isinstance(r["translation"], str)
                else "",
                "kind": r["kind"],
                "status": str(r["status"]),
            }
            for r in rows
        ]
        en_p, zh_p = tdir / "en.pdf", tdir / "zh.pdf"
        for side, p in (("original", en_p), ("translated", zh_p)):
            if p.is_file():
                dual["documents"][side] = {
                    "version": sha256(p.read_bytes()).hexdigest(),
                    "pages": pdf_pages(p),
                }
        dual_p.write_text(json.dumps(dual, ensure_ascii=False), encoding="utf-8")

    return (
        f"rekeyed {len(old)}→{len(rows)} "
        f"(exact={n_exact} text={n_text} orphan={len(orphans)} new={len(rows) - n_exact - n_text})"
    )


def main() -> None:
    tids = sys.argv[1:]
    db = sqlite3.connect(str(DB))
    if not tids:
        tids = [
            d.name
            for d in sorted(TASKS.iterdir())
            if (d / "dual.json").is_file() and (d / "base").is_dir()
        ]
    for tid in tids:
        t0 = time.time()
        try:
            r = rekey_task(db, tid)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            r = f"CRASH {type(e).__name__}: {e}"
        print(f"{tid}: {r} [{time.time() - t0:.0f}s]", flush=True)
    db.close()


if __name__ == "__main__":
    main()
