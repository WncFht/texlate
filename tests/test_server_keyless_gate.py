"""M1 缺 key 硬闸（B0 止血）——keyless 建行落 needs_auth + mock_run 审计键围栅。

覆盖面（misc-pack §M1 后端臂）：

- keyless create → 202 建行但 ``status=needs_auth`` 终态不入队 + ``reader_url`` 照带；
- 同 ``cache_key`` 再撞 needs_auth 行 → 200 ``reused`` 收编同一 task_id（非 409 死信）；
- ``mock_run`` 标记 done 行 → retry 放行（done→queued）且注入 ``prefer=fresh``/
  ``no_seg_cache`` fresh 口径；非 mock done 行 retry → 409（常规闸不松）；
- ``X-Texlate-Key`` 常规路径 → 202 ``queued`` 不回归；needs_auth retry 401 契约不回归；
- store 面：``find_reusable``/``find_active_by_cache_key`` 排除 ``mock_run`` 行。
"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

from conftest import force_status, get_row, mk_api_task, mk_task_row

if TYPE_CHECKING:
    from starlette.testclient import TestClient

ARXIV = "2401.00001"
KEY = {"X-Texlate-Key": "sk-test-key"}


def _mk_done(
    client: TestClient, *, mock_run: bool, cache_key: str | None = None
) -> str:
    """直建行 → force done（``mock_run``/``cache_key`` 可控的终态行工厂）。"""
    opts = {"mock_run": 1} if mock_run else {}
    row = client.portal.call(
        partial(
            mk_task_row,
            client.app.state.store,
            arxiv_id=ARXIV,
            options=opts,
            cache_key=cache_key,
        )
    )
    tid = str(row["id"])
    force_status(client, tid, "done")
    return tid


class TestKeylessGate:
    def test_keyless_lands_needs_auth(self, client: TestClient) -> None:
        """无 key 提交 → 202 + needs_auth 终态行（不入队）+ reader_url 照带。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        body = r.json()
        assert body["status"] == "needs_auth"
        # 前端照跳 reader——ResultBody needs_auth 面板（内联 key + retry）承接
        assert "reader_url" in body
        row = get_row(client, body["task_id"])
        assert row is not None
        assert row["status"] == "needs_auth"
        assert row["message"] == "未配置 API Key"

    def test_keyless_resubmit_reuses_needs_auth(self, client: TestClient) -> None:
        """同 cache_key 再撞 needs_auth 行 → 200 reused 同一 task_id。"""
        first = client.post(f"/api/arxiv/{ARXIV}/translate", json={})
        assert first.json()["status"] == "needs_auth"
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={})
        assert r.status_code == HTTPStatus.OK, r.text
        body = r.json()
        assert body["reused"] is True
        assert body["task_id"] == first.json()["task_id"]
        # 不堆新行——全库仍只有一条该键任务
        rows = client.portal.call(
            partial(
                client.app.state.store.find_needs_auth_by_cache_key,
                get_row(client, body["task_id"])["cache_key"],
            )
        )
        assert rows is not None
        assert rows["id"] == body["task_id"]

    def test_keyless_upload_lands_needs_auth(self, client: TestClient) -> None:
        """upload 路径同闸（kind=upload_tex ≠ share——share 链零 token 豁免）。"""
        r = client.post(
            "/api/upload",
            files={
                "file": (
                    "main.tex",
                    b"\\documentclass{article}\n\\begin{document}hi\\end{document}",
                    "application/octet-stream",
                )
            },
        )
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert r.json()["status"] == "needs_auth"

    def test_keyed_create_still_queues(self, client: TestClient) -> None:
        """X-Texlate-Key 路径不回归——202 queued 正常入队。"""
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={}, headers=KEY)
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert r.json()["status"] == "queued"

    def test_needs_auth_retry_requires_key(self, client: TestClient) -> None:
        """needs_auth 行 retry 无 X-Texlate-Key → 401；带 key → queued（不回归）。"""
        tid = mk_api_task(client, ARXIV)
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.UNAUTHORIZED
        r = client.post(f"/api/task/{tid}/retry", json={}, headers=KEY)
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        assert get_row(client, tid)["status"] == "queued"


class TestMockRunGate:
    def test_mock_done_retry_requeues_with_fresh(self, client: TestClient) -> None:
        """mock_run done 行 retry → 202 queued + prefer=fresh/no_seg_cache 注入。"""
        tid = _mk_done(client, mock_run=True)
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        row = get_row(client, tid)
        assert row["status"] == "queued"
        opts = json.loads(row["options_json"])
        # fresh 口径随 options 落库（sticky）——绕段缓存 + worker post-resolve dedup
        assert opts["prefer"] == "fresh"
        assert opts["no_seg_cache"] == 1
        # 审计标记保留——再落终态仍可识别
        assert opts["mock_run"] == 1

    def test_plain_done_retry_still_409(self, client: TestClient) -> None:
        """非 mock done 行 retry → 409（RETRYABLE_FROM 常规闸不松）。"""
        tid = _mk_done(client, mock_run=False)
        r = client.post(f"/api/task/{tid}/retry", json={})
        assert r.status_code == HTTPStatus.CONFLICT, r.text

    def test_find_reusable_excludes_mock_run(self, client: TestClient) -> None:
        """store 面：同 cache_key 下 mock_run done 行不进 reuse 命中集。"""
        ck = "ck-mock-excl-1"
        mock_tid = _mk_done(client, mock_run=True, cache_key=ck)
        store = client.app.state.store
        hit = client.portal.call(partial(store.find_reusable, ck))
        assert hit is None, f"mock_run 行被 find_reusable 命中: {mock_tid}"
        # 对照：未标记行同键照常命中（排除谓词不误伤）
        real_tid = _mk_done(client, mock_run=False, cache_key=ck)
        hit = client.portal.call(partial(store.find_reusable, ck))
        assert hit is not None
        assert hit["id"] == real_tid

    def test_find_active_excludes_mock_run(self, client: TestClient) -> None:
        """同键 active mock 行不进 find_active_by_cache_key（唯一槽仍由它占）。"""
        ck = "ck-mock-excl-2"
        tid = _mk_done(client, mock_run=True, cache_key=ck)
        force_status(client, tid, "queued")  # 持槽态
        store = client.app.state.store
        hit = client.portal.call(partial(store.find_active_by_cache_key, ck))
        assert hit is None
        # 对照臂：未标记 active 行照常命中
        plain = client.portal.call(
            partial(mk_task_row, store, arxiv_id=ARXIV, cache_key="ck-plain-1")
        )
        hit = client.portal.call(partial(store.find_active_by_cache_key, "ck-plain-1"))
        assert hit is not None
        assert hit["id"] == plain["id"]
