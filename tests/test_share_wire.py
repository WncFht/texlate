"""隐式 share 命中（shared-cache.md §8）：translate 任务 parse 后自动查共享
index——命中走 ``_stage_share_apply`` 对账通道（零 token），miss/包坏/包缺
回退正常管线，``prefer=fresh`` 不查。

生产端真跑产包 → ``share_pack_publish`` 直落消费端 ``share_dir``（包 +
index 行同口径）；消费端同 ``FakeFetcher`` 载荷保证 chunk 对账全命中。
``worker.USER_GLOSSARY_PATH`` 钉死不存在路径——``glossary_hash`` 双侧恒
``""``，键组分与 ``share_pack_manifest`` 派生面逐项对齐。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _sharekit import mk_share_apps, share_parts
from conftest import wait_terminal
from starlette.testclient import TestClient

from texlate.server.worker import share_pack_publish
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI

_ARXIV = "2401.00003"


def _apps(
    tmp_path: Path,
    consumer_mock: MockTranslator,
) -> tuple[FastAPI, FastAPI, Path, Path]:
    """``mk_share_apps`` 薄壳——消费端 translator 注入共享 ``consumer_mock``，
    零 token 断言数其调用。"""
    return mk_share_apps(tmp_path, cons_mock=consumer_mock)


@pytest.fixture
def pair(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用（env 清洗）
) -> Iterator[tuple[TestClient, TestClient, Path, Path, MockTranslator]]:
    """(生产 client, 消费 client, 生产 data_dir, 消费 data_dir, 消费 mock)。"""
    mock = MockTranslator()
    prod, cons, pa_dir, pb_dir = _apps(tmp_path, mock)
    with TestClient(prod) as pa, TestClient(cons) as pb:
        yield pa, pb, pa_dir, pb_dir, mock


def _seed_index(pa: TestClient, pa_dir: Path, pb_dir: Path) -> dict:
    """生产端真跑 arxiv 任务 → ``share_pack_publish`` 落消费端 index → 任务快照。"""
    r = pa.post(f"/api/arxiv/{_ARXIV}/translate", json={})
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    snap = wait_terminal(pa, r.json()["task_id"])
    assert snap["status"] == "done", snap
    # 生产端默认 fm={abstract,title}（parse 写回后 manifest 同口径）
    # ——消费端键组分含 fm，seed 不带此键必 miss
    parts = share_parts(
        arxiv_id=_ARXIV,
        version="v1",
        model=snap["model"],
        target_lang=snap["target_lang"],
    )
    tdir = pa_dir / "tasks" / str(snap["task_id"])
    share_pack_publish(tdir, parts, pb_dir / "share")
    return snap


def _request(pb: TestClient, model: str, **body: object) -> dict:
    payload: dict[str, object] = {"model": model}
    payload.update(body)
    r = pb.post(f"/api/arxiv/{_ARXIV}/translate", json=payload)
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return wait_terminal(pb, r.json()["task_id"])


class TestImplicitShareHit:
    def test_hit_done_zero_token(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """命中：kind 仍 arxiv + done 终态 + 产物齐 + MockTranslator 零调用。"""
        pa, pb, pa_dir, pb_dir, mock = pair
        prod_snap = _seed_index(pa, pa_dir, pb_dir)
        snap = _request(pb, prod_snap["model"])
        assert snap["status"] == "done", snap
        assert snap["kind"] == "arxiv"  # 隐式命中不改行 kind
        assert mock.calls == []  # 零 token 承诺——translate 段整体跳过
        for kind in ("src_tar", "en_pdf", "zh_pdf", "zh_src_zip", "dual_json"):
            assert kind in snap["artifacts"], snap["artifacts"]
        dual = pb.get(f"/api/files/{snap['task_id']}/dual.json").json()
        assert dual["chunks"]
        assert all(c["zh"] for c in dual["chunks"])

    def test_hit_marks_reuse_and_blocks_pack(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """命中任务写 ``reuse_hit`` 标记——share/pack 端点 422 拒自包。"""
        pa, pb, pa_dir, pb_dir, _mock = pair
        prod_snap = _seed_index(pa, pa_dir, pb_dir)
        snap = _request(pb, prod_snap["model"])
        assert snap["status"] == "done", snap
        r = pb.post(f"/api/task/{snap['task_id']}/share/pack")
        assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, r.text
        assert r.json()["code"] == "share_pack_rejected"

    def test_miss_falls_back_to_translate(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """index 无行（未命中）→ 正常自译 done，translator 有调用。"""
        _pa, pb, _pa_dir, _pb_dir, mock = pair
        r = pb.post(f"/api/arxiv/{_ARXIV}/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        snap = wait_terminal(pb, r.json()["task_id"])
        assert snap["status"] == "done", snap
        assert len(mock.calls) > 0

    def test_corrupt_bundle_falls_back(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """index 行在、包字节坏 → unpack 校验失败回退自译，不 500。"""
        pa, pb, pa_dir, pb_dir, mock = pair
        prod_snap = _seed_index(pa, pa_dir, pb_dir)
        bundles = list((pb_dir / "share").glob("*.share.zip"))
        assert len(bundles) == 1
        bundles[0].write_bytes(b"not a zip at all")
        snap = _request(pb, prod_snap["model"])
        assert snap["status"] == "done", snap
        assert len(mock.calls) > 0

    def test_missing_bundle_falls_back(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """index 行在、包文件不在 → 回退自译（行包分离容忍）。"""
        pa, pb, pa_dir, pb_dir, mock = pair
        prod_snap = _seed_index(pa, pa_dir, pb_dir)
        for bundle in (pb_dir / "share").glob("*.share.zip"):
            bundle.unlink()
        snap = _request(pb, prod_snap["model"])
        assert snap["status"] == "done", snap
        assert len(mock.calls) > 0

    def test_prefer_fresh_skips_lookup(
        self, pair: tuple[TestClient, TestClient, Path, Path, MockTranslator]
    ) -> None:
        """``options.prefer=fresh`` → 不查 index，正常自译。"""
        pa, pb, pa_dir, pb_dir, mock = pair
        prod_snap = _seed_index(pa, pa_dir, pb_dir)
        r = pb.post(
            f"/api/arxiv/{_ARXIV}/translate",
            json={"model": prod_snap["model"], "options": {"prefer": "fresh"}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        snap = wait_terminal(pb, r.json()["task_id"])
        assert snap["status"] == "done", snap
        assert len(mock.calls) > 0

    def test_zero_match_falls_back_to_translate(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        """键命中但对账零命中（包与本源不对应）→ 摘标记回退自译——不替用户拒包。"""
        mock = MockTranslator()
        # 生产端源 = MINI_TEX；消费端源 = 完全不同的工程 → 对账必零命中
        other_tex = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\section{Other}\n"
            "Completely unrelated content that shares no chunks at all.\n"
            "\\end{document}\n"
        )
        prod, cons, pa_dir, pb_dir = mk_share_apps(
            tmp_path, cons_mock=mock, cons_tex=other_tex
        )
        with TestClient(prod) as pa, TestClient(cons) as pb:
            snap = _seed_index(pa, pa_dir, pb_dir)
            hit = _request(pb, snap["model"])
            assert hit["status"] == "done", hit
            assert len(mock.calls) > 0
            # 回退后 share/reuse_hit 标记已摘——本跑自产可正常打包
            r = pb.post(f"/api/task/{hit['task_id']}/share/pack")
            assert r.status_code == HTTPStatus.OK, r.text
