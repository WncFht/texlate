"""dossier 合成账自检（原 ``verbs/dossier.py`` 内嵌 ``--selftest`` 的 pytest 化）。

合成内存账 + tmp workdir → ``work_inventory``/``build_dossier``/``render_md``
全链——不碰真 index。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from verbs import dossier

if TYPE_CHECKING:
    from pathlib import Path


def test_dossier_selftest(tmp_path: Path) -> None:
    recs = {
        "ingest": [
            {
                "id": "9999.0001",
                "idc": "9999.0001",
                "stage": "ingest",
                "arm": "-",
                "upstream": "-",
                "status": "ok",
                "dur_s": 0.1,
                "metrics": {},
                "errors": [],
                "sig": "",
                "run": "t/run",
            }
        ],
        "parse": [
            {
                "id": "9999.0001",
                "idc": "9999.0001",
                "stage": "parse",
                "arm": "-",
                "upstream": "-",
                "status": "ok",
                "dur_s": 0.2,
                "metrics": {
                    "main_rel": "m.tex",
                    "engine_resolved": "xelatex",
                    "route": {},
                    "totals": {"chunks": 3},
                },
                "errors": [],
                "sig": "",
                "run": "t/run",
            }
        ],
        "xlat": [
            {
                "id": "9999.0001",
                "idc": "9999.0001",
                "stage": "xlat",
                "arm": "mock",
                "upstream": "-",
                "status": "ok",
                "dur_s": 1.0,
                "metrics": {"translate": {"chunks": 2, "ok": 1, "fault": 1}},
                "errors": [],
                "sig": "",
                "run": "t/run",
            }
        ],
        "compile": [
            {
                "id": "9999.0001",
                "idc": "9999.0001",
                "stage": "compile",
                "arm": "zh",
                "upstream": "mock",
                "status": "fail",
                "dur_s": 1.0,
                "metrics": {
                    "engine": "xelatex",
                    "verdict": {
                        "status": "fail",
                        "category": "missing_file",
                        "payload": "foo.sty",
                        "cjk_chars": -1,
                    },
                    "compile": {
                        "pdf_bytes": 0,
                        "first_error": "! LaTeX Error: File `foo.sty' not found.",
                    },
                    "inject": {"status": "injected", "mode": "ctex"},
                },
                "errors": [
                    {
                        "code": "missing_file",
                        "cat": "missing_file",
                        "payload": "foo.sty",
                    }
                ],
                "sig": "missing_file:foo.sty",
                "run": "t/run",
            }
        ],
        "fixloop": [
            {
                "id": "9999.0001",
                "idc": "9999.0001",
                "stage": "fixloop",
                "arm": "fix",
                "upstream": "mock",
                "status": "clean",
                "dur_s": 2.0,
                "metrics": {
                    "compile_status_before": "fail",
                    "fixloop_verdict": "clean",
                    "rounds": 1,
                },
                "errors": [],
                "sig": "clean",
                "run": "t/run",
            }
        ],
    }
    wdir = tmp_path / "9999.0001"
    (wdir / "zh").mkdir(parents=True)
    (wdir / "splice").mkdir(parents=True)
    (wdir / "zh" / ".xlat-arm.json").write_text('{"arm":"mock"}', encoding="utf-8")
    (wdir / "parse.json").write_text(
        json.dumps(
            {
                "id": "9999.0001",
                "status": "ok",
                "main_rel": "m.tex",
                "engine_resolved": "xelatex",
                "route": {},
                "totals": {"chunks": 3},
            }
        ),
        encoding="utf-8",
    )
    (wdir / "splice" / "m.log").write_text(
        "x\n! LaTeX Error: File `foo.sty' not found.\ny\n", encoding="utf-8"
    )
    (wdir / "xlat-mock.jsonl").write_text(
        '{"chunk_id":"0:0","status":"ok"}\n'
        '{"chunk_id":"0:1","status":"fault","error_kind":"timeout"}\n',
        encoding="utf-8",
    )
    inv = dossier.work_inventory(wdir)
    d = dossier.build_dossier(
        "9999.0001",
        {"9999.0001"},
        recs,
        [],
        wdir,
        inv,
        run_label="t/run",
        prior_waves=["t/run"],
    )
    md = dossier.render_md(d)
    for needle in (
        "断点=compile",
        "missing_file:foo.sty",
        "0:1",
        "xelatex",
        "first_error",
        "csb=fail",
    ):
        assert needle in md, f"缺 {needle}\n{md}"
    assert d["gap_flags"]["needs_subclass"] is False
    assert d["signature"]["sig_raw"] == "missing_file:foo.sty"
