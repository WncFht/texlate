"""copy-latex 后端端点验收：``POST /api/task/{id}/latex``（实现文档 §后端）。

夹具策略：``base/`` 树写真 ``.tex`` + chunks 行 span 用 ``str.index`` 实算
（与 ``parse_file`` 产出的 ``decode_tex`` 字符偏移同口径）——whole 档基线
即 ``decode_tex(base/file)[s:e]`` 逐字节对照。
"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")

from conftest import (
    make_targz,
    mk_store,
    mk_task_row,
    reg_artifact,
    store_call,
)

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from starlette.testclient import TestClient

_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "First paragraph has two sentences. Second sentence here.\n"
    "\n"
    "% comment line between paragraphs\n"
    "\\label{sec:one}\n"
    "Second paragraph begins here. It continues further onward.\n"
    "\n"
    "Third paragraph final.\n"
    "\\end{document}\n"
)
_P0 = "First paragraph has two sentences. Second sentence here."
#: 句界夹具注意：``abbrev_cut`` 对 ≤3 字母尾词不切（``now.``/``on.`` 无界），
#: 钉版句须以 >3 字母词收尾（``here.``/``onward.``）才有 ``sentence_ends`` 切点。
_P1 = "Second paragraph begins here. It continues further onward."
_P2 = "Third paragraph final."
_SEC_FILE = "sec/intro.tex"
_SEC = "Alpha section body one. Beta sentence two.\n"
_P3 = "Alpha section body one. Beta sentence two."


def _mk_task(client: TestClient, **kw: object) -> str:
    """store 层建行（绕 HTTP 提交面——M1 keyless 闸与本件正交）。"""
    store = client.app.state.store
    row = store_call(client, partial(mk_task_row, store, **kw))
    return str(row["id"])


def _mk_src_task(
    client: TestClient,
    files: dict[str, str],
    chunks: dict[str, list[str]],
    *,
    kind: str = "arxiv",
) -> str:
    """建行 + ``base/`` 树 + chunks 行（span = ``str.index`` 真实切片坐标）。"""
    tid = _mk_task(client, kind=kind)
    tdir = client.app.state.data_dir / "tasks" / tid
    rows: list[dict] = []
    seq = 0
    for rel, text in files.items():
        p = tdir / "base" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        pos = 0
        for piece in chunks.get(rel, []):
            s = text.index(piece, pos)
            rows.append(
                {
                    "seq": seq,
                    "chunk_id": f"c{seq}",
                    "src_file": rel,
                    "byte_start": s,
                    "byte_end": s + len(piece),
                    "kind": "para",
                    "src_text": piece,
                }
            )
            pos = s + len(piece)
            seq += 1
    store_call(client, client.app.state.store.insert_chunks, tid, rows)
    return tid


def _mk_main_task(client: TestClient, **kw: object) -> str:
    """单文件三段落夹具（seq0/1/2 = _P0/_P1/_P2）。"""
    return _mk_src_task(
        client,
        {"main.tex": _MAIN},
        {"main.tex": [_P0, _P1, _P2]},
        **kw,
    )


def _write_dual(client: TestClient, tid: str, chunks: list[dict]) -> None:
    """``tasks/{tid}/dual.json`` 落盘（approx 臂物料）。"""
    tdir: Path = client.app.state.data_dir / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "dual.json").write_text(
        json.dumps({"version": 1, "chunks": chunks}), encoding="utf-8"
    )


def _post(client: TestClient, tid: str, body: dict, **kw: object) -> httpx.Response:
    return client.post(f"/api/task/{tid}/latex", json=body, **kw)


# ------------------------------------------------------------ repo 方法


class TestSpansBySeqs:
    def test_order_cols_empty(self, tmp_path: Path) -> None:
        """命中行 seq 升序 + span 列集齐 + 空集短路。"""
        store = mk_store(tmp_path)
        row = mk_task_row(store)
        tid = str(row["id"])
        store.insert_chunks(
            tid,
            [
                {
                    "seq": s,
                    "chunk_id": f"c{s}",
                    "src_file": "main.tex",
                    "byte_start": s * 10,
                    "byte_end": s * 10 + 5,
                    "kind": "para",
                    "src_text": f"t{s}",
                }
                for s in (0, 1, 2)
            ],
        )
        rows = store.spans_by_seqs(tid, [2, 0])
        assert [r["seq"] for r in rows] == [0, 2]
        assert set(rows[0]) == {
            "seq",
            "chunk_id",
            "src_file",
            "byte_start",
            "byte_end",
            "kind",
            "src_text",
        }
        assert rows[0]["byte_end"] - rows[0]["byte_start"] == 5  # noqa: PLR2004 -- 夹具钉值
        assert store.spans_by_seqs(tid, []) == []
        assert store.spans_by_seqs(tid, [99]) == []
        store.close()


# ------------------------------------------------------------ whole/gaps 档


class TestWhole:
    def test_whole_baseline(self, client: TestClient) -> None:
        """whole+gaps:false → 逐块切片 + 壳边扩展，``\\n\\n`` 连接。

        P1 壳头界=前一空白行右端——其前注释/``\\label`` 行随壳入切。
        """
        tid = _mk_main_task(client)
        r = _post(client, tid, {"seqs": [0, 1, 2], "mode": "whole", "gaps": False})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["latex"] == (
            f"{_P0}\n\n"
            f"% comment line between paragraphs\n\\label{{sec:one}}\n{_P1}\n\n"
            f"{_P2}"
        )
        assert body["chunks"] == 3  # noqa: PLR2004 -- 三切片
        assert body["files"] == ["main.tex"]
        assert body["mode_used"] == "whole"
        assert "approx" not in body
        assert "truncated" not in body

    def test_gaps_recover_comment(self, client: TestClient) -> None:
        """缺省 gaps=true：同文件 seq 相邻块间回收注释/\\label 料。"""
        tid = _mk_main_task(client)
        r = _post(client, tid, {"seqs": [0, 1, 2]})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert "% comment line between paragraphs" in body["latex"]
        assert "\\label{sec:one}" in body["latex"]
        # gap 料夹在 P0 与 P1 之间
        i0 = body["latex"].index(_P0)
        ig = body["latex"].index("% comment line")
        i1 = body["latex"].index(_P1)
        assert i0 < ig < i1

    def test_cross_file_marker(self, client: TestClient) -> None:
        """跨 src_file 块插 ``% ── file:`` 界标；files 按出现序去重。"""
        tid = _mk_src_task(
            client,
            {"main.tex": _MAIN, _SEC_FILE: _SEC},
            {"main.tex": [_P2], _SEC_FILE: [_P3]},
        )
        r = _post(client, tid, {"seqs": [0, 1], "gaps": False})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert f"% ── file: {_SEC_FILE} ──" in body["latex"]
        assert body["files"] == ["main.tex", _SEC_FILE]
        assert body["latex"].endswith(_P3)

    def test_partial_failure_marker(self, client: TestClient) -> None:
        """单块源全不可得 → ``%`` 占位注释，其余切片正常交付（不 422）。"""
        tid = _mk_src_task(
            client,
            {"main.tex": _MAIN},
            {"main.tex": [_P0]},
        )
        # seq1 指向不存在文件 gone.tex 的块（手动建行）
        store_call(
            client,
            client.app.state.store.insert_chunks,
            tid,
            [
                {
                    "seq": 1,
                    "chunk_id": "c1",
                    "src_file": "gone.tex",
                    "byte_start": 0,
                    "byte_end": 5,
                    "kind": "para",
                    "src_text": "gone!",
                }
            ],
        )
        r = _post(client, tid, {"seqs": [0, 1], "gaps": False})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert _P0 in body["latex"]
        assert "% [seq 1: source unavailable]" in body["latex"]
        assert body["chunks"] == 1
        assert body["files"] == ["main.tex"]


# ------------------------------------------------------------ env 配平/巨间区

_TAB_ROWS = "".join(f"row{i} & value{i}\\\\\n" for i in range(400))  # ~7KB 间区
_TAB_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "Intro paragraph text before the float.\n"
    "\n"
    "\\begin{table}[htbp]\n"
    "\\centering\n"
    "\\caption{Caption text for the table.}\n"
    "\\label{tab:big}\n"
    "\\begin{tabular}{ll}\n" + _TAB_ROWS + "\\end{tabular}\n"
    "\\end{table}\n"
    "\n"
    "After paragraph text past the float.\n"
    "\\end{document}\n"
)
_TAB_P0 = "Intro paragraph text before the float."
_TAB_CAP = "Caption text for the table."
_TAB_P1 = "After paragraph text past the float."


class TestOpaqueGap:
    def test_large_env_gap_recovered(self, client: TestClient) -> None:
        """seq 相邻块间区 >2KB 的 tabular（非 chunk 料）一体回收。

        回归钉：旧 ``GAP_MAX=2048`` 让 caption→后段 run 断裂，整个
        ``\\begin{tabular}…\\end{tabular}`` 随间区丢弃（实证
        2609.25611v1 seq121→122 语言表）。
        """
        tid = _mk_src_task(
            client,
            {"main.tex": _TAB_MAIN},
            {"main.tex": [_TAB_P0, _TAB_CAP, _TAB_P1]},
        )
        r = _post(client, tid, {"seqs": [0, 1, 2]})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        for frag in (
            "\\begin{table}[htbp]",
            "\\begin{tabular}{ll}",
            "row399 & value399",
            "\\end{tabular}",
            "\\end{table}",
            "\\label{tab:big}",
            _TAB_P1,
        ):
            assert frag in body["latex"], frag

    def test_caption_only_balanced_slice(self, client: TestClient) -> None:
        """单块选 caption：壳头带 ``\\begin{table}`` → 尾吃到 ``\\end{table}``。

        壳头回扫带进 ``\\begin{env}`` 时尾必须配平——否则输出半截
        ``\\caption{…`` 开花括号（线上实证碎形）。
        """
        tid = _mk_src_task(
            client,
            {"main.tex": _TAB_MAIN},
            {"main.tex": [_TAB_CAP]},
        )
        r = _post(client, tid, {"seqs": [0]})
        assert r.status_code == HTTPStatus.OK, r.text
        latex = r.json()["latex"]
        assert "\\end{tabular}" in latex
        assert "\\end{table}" in latex
        assert latex.count("\\begin{") == latex.count("\\end{")

    def test_orphan_begin_cut(self, client: TestClient) -> None:
        """尾区孤儿 ``\\begin{env}``（无配对 \\end）→ 截在其前不带半张表。

        ``\\end{itemize}`` 落在空白行界之后：尾区只罩进 env 头时宁缺不滥。
        """
        main = (
            "\\documentclass{article}\n\\begin{document}\n"
            + _P0
            + "\n\\begin{itemize}\n\\item x\n\n\\end{itemize}\n\n"
            + _P1
            + "\n\\end{document}\n"
        )
        # 尾区界=\\item x 后空白行——\\begin{itemize} 无配对 \end 成孤儿
        tid = _mk_src_task(client, {"main.tex": main}, {"main.tex": [_P0]})
        r = _post(client, tid, {"seqs": [0]})
        assert r.status_code == HTTPStatus.OK, r.text
        latex = r.json()["latex"]
        assert "\\begin{itemize}" not in latex


# ------------------------------------------------------------ sent 档


class TestSent:
    def test_sent_head_clip(self, client: TestClient) -> None:
        """head anchor 落在第二句中段 → 外扩到句首（第二句起）。"""
        tid = _mk_main_task(client)
        r = _post(
            client,
            tid,
            {"seqs": [0, 1, 2], "mode": "sent", "head": "Second sentence here"},
        )
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["mode_used"] == "sent"
        assert body["latex"].startswith("Second sentence here.")
        assert "First paragraph" not in body["latex"]

    def test_sent_tail_clip(self, client: TestClient) -> None:
        """tail anchor 落在尾块首句中段 → 外扩到句终（首句止）。"""
        tid = _mk_main_task(client)
        r = _post(
            client,
            tid,
            {
                "seqs": [0, 1],
                "mode": "sent",
                "tail": "Second paragraph begins",
            },
        )
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["mode_used"] == "sent"
        assert body["latex"].endswith("Second paragraph begins here.")
        assert "It continues further onward." not in body["latex"]

    def test_sent_single_chunk_head_tail(self, client: TestClient) -> None:
        """单块双侧 clip：head 进第二句、tail 在句尾 → 只留第二句。"""
        tid = _mk_main_task(client)
        r = _post(
            client,
            tid,
            {
                "seqs": [0],
                "mode": "sent",
                "head": "Second sentence",
                "tail": "here.",
            },
        )
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["mode_used"] == "sent"
        assert body["latex"] == "Second sentence here."

    def test_sent_anchor_mismatch_whole(self, client: TestClient) -> None:
        """anchor 失配（最长块 <0.6 阈值）→ 该侧退 whole，不报错。"""
        tid = _mk_main_task(client)
        r = _post(
            client,
            tid,
            {
                "seqs": [0],
                "mode": "sent",
                "head": "zzzzz unrelated anchor text never appears anywhere",
            },
        )
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["mode_used"] == "whole"
        assert body["latex"] == _P0

    def test_sent_no_anchor_is_whole(self, client: TestClient) -> None:
        """mode=sent 无 anchor（zh 侧等价形）→ 整段语义 + mode_used=whole。"""
        tid = _mk_main_task(client)
        r = _post(client, tid, {"seqs": [0], "mode": "sent"})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["latex"] == _P0
        assert body["mode_used"] == "whole"


# ------------------------------------------------------------ 回落链


class TestFallback:
    def test_tar_arm(self, client: TestClient) -> None:
        """base/ 缺席 → src.tar 成员切片（内容未漂移 → 校验头过）。"""
        tid = _mk_task(client)
        tdir = client.app.state.data_dir / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)  # 无 base/ 目录
        store_call(
            client,
            client.app.state.store.insert_chunks,
            tid,
            [
                {
                    "seq": 0,
                    "chunk_id": "c0",
                    "src_file": "main.tex",
                    "byte_start": _MAIN.index(_P0),
                    "byte_end": _MAIN.index(_P0) + len(_P0),
                    "kind": "para",
                    "src_text": _P0,
                }
            ],
        )
        reg_artifact(client, tid, "src_tar", "src.tar", make_targz({"main.tex": _MAIN}))
        r = _post(client, tid, {"seqs": [0], "gaps": False})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["latex"] == _P0
        assert "approx" not in body

    def test_tar_drift_approx(self, client: TestClient) -> None:
        """tar 原件被 normalize 改写（注头漂移）→ 校验头弃臂 → dual approx。"""
        tid = _mk_task(client)
        tdir = client.app.state.data_dir / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        en0 = "First paragraph has [[CITE_1]] sentences. Second sentence here."
        store_call(
            client,
            client.app.state.store.insert_chunks,
            tid,
            [
                {
                    "seq": 0,
                    "chunk_id": "c0",
                    "src_file": "main.tex",
                    "byte_start": _MAIN.index(_P0),
                    "byte_end": _MAIN.index(_P0) + len(_P0),
                    "kind": "para",
                    "src_text": en0,
                }
            ],
        )
        # tar 成员 = 注入 ~1KB 头的漂移件——同 span 切到别处，校验头必败
        drifted = "% normalize injected header\n" * 60 + _MAIN
        reg_artifact(
            client,
            tid,
            "src_tar",
            "src.tar",
            make_targz({"main.tex": drifted}),
        )
        _write_dual(
            client,
            tid,
            [
                {
                    "seq": 0,
                    "src_file": "main.tex",
                    "en": en0,
                    "ph": {"[[CITE_1]]": "\\cite{two}"},
                    "kind": "para",
                    "status": "ok",
                }
            ],
        )
        r = _post(client, tid, {"seqs": [0], "gaps": False})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["approx"] is True
        # ph 反掩码还原——[[CITE_1]] → \cite{two}
        assert "\\cite{two}" in body["latex"]
        assert "[[CITE_1]]" not in body["latex"]

    def test_no_source_422(self, client: TestClient) -> None:
        """base/tar/dual 全缺席 → 422 源全不可得。"""
        tid = _mk_task(client)
        tdir = client.app.state.data_dir / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        store_call(
            client,
            client.app.state.store.insert_chunks,
            tid,
            [
                {
                    "seq": 0,
                    "chunk_id": "c0",
                    "src_file": "main.tex",
                    "byte_start": 0,
                    "byte_end": 5,
                    "kind": "para",
                    "src_text": "hello",
                }
            ],
        )
        r = _post(client, tid, {"seqs": [0]})
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, r.text

    def test_seq_no_hit_422(self, client: TestClient) -> None:
        """seqs 全部无命中行 → 422。"""
        tid = _mk_main_task(client)
        r = _post(client, tid, {"seqs": [99]})
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, r.text


# ------------------------------------------------------------ 闸面


class TestGates:
    def test_arxiv_html_422(self, client: TestClient) -> None:
        """arxiv_html 链无 .tex 源 → 早拒 422。"""
        tid = _mk_task(client, kind="arxiv_html")
        r = _post(client, tid, {"seqs": [0]})
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, r.text

    def test_seqs_validation(self, client: TestClient) -> None:
        """seqs 非法面逐项 → 400。"""
        tid = _mk_main_task(client)
        for body in (
            {"seqs": []},
            {"seqs": list(range(301))},
            {"seqs": ["x"]},
            {"seqs": [True]},
            {"seqs": [-1]},
            {"seqs": "0,1"},
            {"seqs": [0], "mode": "x"},
            {"seqs": [0], "gaps": "yes"},
            {"seqs": [0], "head": 42},
        ):
            r = _post(client, tid, body)
            assert r.status_code == HTTPStatus.BAD_REQUEST, (body, r.text)

    def test_cross_tenant_404(self, server_client: TestClient) -> None:
        """换 key 即换租户——他人任务 latex 端点 404。"""
        tid = _mk_main_task(server_client)
        r = server_client.post(
            f"/api/task/{tid}/latex",
            json={"seqs": [0]},
            headers={"X-Texlate-Key": "k-A"},
        )
        assert r.status_code == HTTPStatus.NOT_FOUND, r.text
