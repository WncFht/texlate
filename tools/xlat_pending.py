"""存量任务 pending chunks 离线补译——reseg_rekey 后新块 status=pending，
经 XlatPipeline 走真实网关补译并回写 chunks/dual.json/tasks 计数。

凭证：任务 config_json.base_url/model + settings.json.api_key（服务侧
``_resolve_translator`` 同构，离线无 ctx.secrets 时的等价装配）。
状态映射 PIPE_TO_DB / error_code chunk_error_code 与 _flush_translate 同口径。

用法：.venv/bin/python tools/xlat_pending.py <task_id>...
"""

import asyncio
import json
import sqlite3
import sys
import time

from _env import DB, TASKS, TEXLATE_ROOT
from texlate.chunk import ChunkIn
from texlate.pipecore import PIPE_TO_DB, delivered_db
from texlate.server.worker._common import chunk_error_code
from texlate.validate.l0 import pair_feedback
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    GatewayTranslator,
    PipelineConfig,
    XlatPipeline,
)


async def translate_pending(db: sqlite3.Connection, tid: str) -> str:
    row = db.execute("select config_json from tasks where id=?", (tid,)).fetchone()
    if not row:
        return "skip: 无任务行"
    cfg = json.loads(row[0] or "{}")
    settings = json.loads((TEXLATE_ROOT / "settings.json").read_text(encoding="utf-8"))
    # 网关/模型恒取 settings 现状（devin-2api + swe-2-medium）——任务
    # config_json 的 llm7/GLM/gpt-4o-mini 是已死供应商的历史残影，照走必败
    # （t_e300/t_32fc 实证）；tasks.model/config_json 同步刷新到现行通道。
    base_url = settings["base_url"]
    model = settings["model"]
    api_key = settings.get("api_key", "")
    rows = [
        {"seq": r[0], "chunk_id": r[1], "src_text": r[2], "kind": r[3]}
        for r in db.execute(
            "select seq, chunk_id, src_text, kind from chunks"
            " where task_id=? and status in ('pending','translating')"
            " order by seq",
            (tid,),
        )
    ]
    if not rows:
        # 无 pending 仍走 dual 同步——旧版 dual.json chunks 无 chunk_id 键
        # （seq 为唯一关联键），早期版本按键匹配全 miss 会留陈 zh=en
        # （t_e300 实证 101/131 锚校验失配）。
        with db:
            _sync_task_and_dual(db, tid, cfg, base_url, model)
        return "skip: 无 pending（dual 已同步）"
    client = ChatClient(base_url, api_key)
    try:
        tr = GatewayTranslator(client, model)
        pipe = XlatPipeline(
            tr,
            config=PipelineConfig(
                concurrency=int(cfg.get("concurrency") or 3),
            ),
            validator=pair_feedback,
        )
        inputs = [
            ChunkIn(chunk_id=r["chunk_id"], content=r["src_text"], kind=r["kind"])
            for r in rows
        ]
        results = await pipe.run(inputs)
    finally:
        await client.aclose()
    by_cid = {r.chunk_id: r for r in results}
    n_ok = n_fail = 0
    with db:
        for r in rows:
            res = by_cid.get(r["chunk_id"])
            if res is None:
                continue
            db_status = PIPE_TO_DB.get(res.status, "failed")
            db.execute(
                "update chunks set status=?, translation=?, error_code=?,"
                " attempts=?, warnings=? where task_id=? and chunk_id=?",
                (
                    db_status,
                    res.translation or None,
                    chunk_error_code(res),
                    res.attempts,
                    json.dumps(res.warnings, ensure_ascii=False)
                    if res.warnings
                    else None,
                    tid,
                    r["chunk_id"],
                ),
            )
            if db_status == "ok":
                n_ok += 1
            else:
                n_fail += 1
        _sync_task_and_dual(db, tid, cfg, base_url, model)
    return f"translated ok={n_ok} fail={n_fail} of {len(rows)}"


def _sync_task_and_dual(
    db: sqlite3.Connection,
    tid: str,
    cfg: dict,
    base_url: str,
    model: str,
) -> None:
    """tasks 计数/网关字段 + dual.json chunks zh/status 同步（seq 关联）。

    dual chunks 以 ``seq`` 为唯一关联键——旧 schema 无 ``chunk_id`` 键，
    顺带按 DB 回填对齐新 schema。
    """
    c = db.execute(
        "select count(*),"
        " sum(status not in ('pending','translating')),"
        " sum(status in ('fallback_orig','failed'))"
        " from chunks where task_id=?",
        (tid,),
    ).fetchone()
    cfg["base_url"] = base_url
    cfg["model"] = model
    db.execute(
        "update tasks set total_chunks=?, done_chunks=?, failed_chunks=?,"
        " model=?, config_json=?, updated_at=? where id=?",
        (
            c[0],
            c[1] or 0,
            c[2] or 0,
            model,
            json.dumps(cfg, ensure_ascii=False),
            time.time(),
            tid,
        ),
    )
    dual_p = TASKS / tid / "dual.json"
    if not dual_p.is_file():
        return
    dual = json.loads(dual_p.read_text(encoding="utf-8"))
    zmap = {
        r[0]: (r[1], r[2], r[3])
        for r in db.execute(
            "select seq, status, translation, chunk_id from chunks where task_id=?",
            (tid,),
        )
    }
    for c in dual.get("chunks") or []:
        hit = zmap.get(c.get("seq"))
        if hit is None:
            continue
        st, tr_, cid = hit
        c["status"] = str(st)
        c["zh"] = tr_ if isinstance(tr_, str) and delivered_db(st, tr_) else ""
        if cid and not c.get("chunk_id"):
            c["chunk_id"] = cid
    dual_p.write_text(json.dumps(dual, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    db = sqlite3.connect(str(DB))
    for tid in sys.argv[1:]:
        t0 = time.time()
        try:
            r = asyncio.run(translate_pending(db, tid))
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            r = f"CRASH {type(e).__name__}: {e}"
        print(f"{tid}: {r} [{time.time() - t0:.0f}s]", flush=True)
    db.close()


if __name__ == "__main__":
    main()
