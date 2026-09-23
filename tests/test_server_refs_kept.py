"""M4：kept_refs CRUD/CASCADE/租户隔离 + refs.bib 三臂导出端点验收。

端点面（misc-pack 实现文档 §M4）：``GET/PUT/DELETE /api/task/{id}/refs/kept``
与 ``GET /api/task/{id}/refs.bib?keys=&all=1&download=1``；远端臂全部经
``refs._client`` 注入的 httpx client——测试用 ``MockTransport`` 桩死，
远端失败断言自动降级 ``@misc`` + ``X-Refs-Degraded`` 头，绝不 502。
"""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("httpx", reason="server extra 未装")

import httpx
from conftest import (
    force_status,
    make_targz,
    mk_api_task,
    mk_task_row,
    reg_artifact,
    store_call,
)

from texlate.server.routers import refs

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.testclient import TestClient

ARXIV = "2401.00004"

_BIB = r"""
@string{jmlr = {Journal of Machine Learning Research}}
@article{Alpha2024,
  title   = {Alpha Paper},
  author  = {Doe, Jane},
  journal = jmlr,
  year    = {2024},
}
@misc{Beta2024, title = {Beta Paper}, year = {2023}}
"""

_BBL = r"""
\begin{thebibliography}{9}
\bibitem{Gamma2023} Gamma et al. Cool result. arXiv:2301.12345.
\bibitem{Delta2022} Delta et al. Old fashioned entry, no ids anywhere.
\end{thebibliography}
"""


def _mk_task(client: TestClient, **kw: object) -> str:
    """store 层建行（绕 HTTP 提交面——M1 keyless 闸与本件正交）。"""
    store = client.app.state.store
    row = store_call(client, partial(mk_task_row, store, **kw))
    return str(row["id"])


def _mk_src_task(client: TestClient) -> str:
    """建行 + 登记含 .bib/.bbl 的 src.tar 产物。"""
    tid = _mk_task(client)
    blob = make_targz({"refs.bib": _BIB, "main.bbl": _BBL})
    reg_artifact(client, tid, "src_tar", "src.tar", blob)
    return tid


def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    """``MockTransport`` 包出的 AsyncClient（替换 ``refs._client`` 面）。"""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def _fail_all(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(502, text="upstream down")


# ------------------------------------------------------------ kept CRUD


class TestKeptCrud:
    def test_put_get_overwrite(self, client: TestClient) -> None:
        tid = _mk_task(client)
        r = client.put(
            f"/api/task/{tid}/refs/kept",
            json={
                "key": "Alpha2024",
                "payload": {"text": "Doe 2024", "meta": {"title": "Alpha"}},
            },
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json() == {"kept": True}
        got = client.get(f"/api/task/{tid}/refs/kept").json()["kept"]
        assert got["Alpha2024"]["meta"]["title"] == "Alpha"
        # 同 key 覆盖
        client.put(
            f"/api/task/{tid}/refs/kept",
            json={"key": "Alpha2024", "payload": {"text": "v2"}},
        )
        got = client.get(f"/api/task/{tid}/refs/kept").json()["kept"]
        assert got["Alpha2024"]["text"] == "v2"

    def test_unkeep_and_delete(self, client: TestClient) -> None:
        tid = _mk_task(client)
        client.put(
            f"/api/task/{tid}/refs/kept",
            json={"key": "k1", "payload": {"text": "t"}},
        )
        # payload:null = unkeep（幂等）
        r = client.put(
            f"/api/task/{tid}/refs/kept", json={"key": "k1", "payload": None}
        )
        assert r.json() == {"kept": False}
        assert client.get(f"/api/task/{tid}/refs/kept").json()["kept"] == {}
        # 再 unkeep 仍 200（幂等）
        assert (
            client.put(
                f"/api/task/{tid}/refs/kept",
                json={"key": "k1", "payload": None},
            ).status_code
            == HTTPStatus.OK
        )
        # DELETE 未命中 → 404
        assert (
            client.delete(f"/api/task/{tid}/refs/kept/k1").status_code
            == HTTPStatus.NOT_FOUND
        )
        client.put(
            f"/api/task/{tid}/refs/kept",
            json={"key": "k2", "payload": {"text": "t"}},
        )
        r = client.delete(f"/api/task/{tid}/refs/kept/k2")
        assert r.status_code == HTTPStatus.OK
        assert client.get(f"/api/task/{tid}/refs/kept").json()["kept"] == {}

    def test_validation(self, client: TestClient) -> None:
        tid = _mk_task(client)
        base = f"/api/task/{tid}/refs/kept"
        assert (
            client.put(base, json={"payload": {}}).status_code == HTTPStatus.BAD_REQUEST
        )
        assert (
            client.put(base, json={"key": "x" * 161, "payload": {}}).status_code
            == HTTPStatus.BAD_REQUEST
        )
        assert (
            client.put(base, json={"key": "k", "payload": ["not", "dict"]}).status_code
            == HTTPStatus.BAD_REQUEST
        )
        # 64KB 闸（序列化后超限 → StoreError → 400）
        assert (
            client.put(
                base,
                json={"key": "k", "payload": {"text": "x" * 70000}},
            ).status_code
            == HTTPStatus.BAD_REQUEST
        )
        # 未知任务 → 404（租户闸同径）
        assert (
            client.get("/api/task/t_deadbeefdeadbeef/refs/kept").status_code
            == HTTPStatus.NOT_FOUND
        )

    def test_cascade_on_task_delete(self, client: TestClient) -> None:
        """任务删行 → kept_refs ON DELETE CASCADE 殉葬。"""
        tid = _mk_task(client)
        client.put(
            f"/api/task/{tid}/refs/kept",
            json={"key": "k1", "payload": {"text": "t"}},
        )
        force_status(client, tid, "done")
        assert client.delete(f"/api/task/{tid}").status_code == HTTPStatus.OK
        store = client.app.state.store
        assert store_call(client, store.kept_list, tid) == {}


class TestKeptTenant:
    def test_cross_tenant_404(self, server_client: TestClient) -> None:
        """BYOK 换租户 → kept 面不可见（与任务同 blast radius）。"""
        tid = mk_api_task(
            server_client, ARXIV, model="m", headers={"X-Texlate-Key": "k-A"}
        )
        ha, hb = {"X-Texlate-Key": "k-A"}, {"X-Texlate-Key": "k-B"}
        assert (
            server_client.put(
                f"/api/task/{tid}/refs/kept",
                json={"key": "k1", "payload": {"text": "t"}},
                headers=ha,
            ).status_code
            == HTTPStatus.OK
        )
        for method, url in (
            ("GET", f"/api/task/{tid}/refs/kept"),
            ("PUT", f"/api/task/{tid}/refs/kept"),
            ("DELETE", f"/api/task/{tid}/refs/kept/k1"),
            ("GET", f"/api/task/{tid}/refs.bib"),
        ):
            r = server_client.request(
                method,
                url,
                headers=hb,
                json={"key": "x", "payload": {}} if method == "PUT" else None,
            )
            assert r.status_code == HTTPStatus.NOT_FOUND, (method, url)


# ------------------------------------------------------------ refs.bib


class TestRefsBib:
    def test_lane_a_verbatim(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """.bib 命中 → verbatim 直出 + @STRING defs 闭包置顶。"""
        tid = _mk_src_task(client)
        monkeypatch.setattr(refs, "_client", lambda: _mock_client(_fail_all))
        r = client.get(f"/api/task/{tid}/refs.bib?keys=Alpha2024")
        assert r.status_code == HTTPStatus.OK
        assert r.headers["content-type"].startswith("text/x-bibtex")
        assert r.headers["X-Refs-Degraded"] == "0"
        body = r.text
        assert "@article{Alpha2024," in body
        assert "journal = jmlr" in body  # verbatim 不展开宏
        assert "@string{jmlr" in body  # defs 闭包随行

    def test_remote_hit_rewrites_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lane B：bibitem 抽 arXiv id → DataCite bibtex → key 改写文档键。"""
        tid = _mk_src_task(client)

        def handler(req: httpx.Request) -> httpx.Response:
            assert "doi.org" in req.url.host
            return httpx.Response(
                200,
                text="@article{datacite_key,\n"
                "  title = {Gamma Paper},\n  year = {2023}\n}",
            )

        monkeypatch.setattr(refs, "_client", lambda: _mock_client(handler))
        r = client.get(f"/api/task/{tid}/refs.bib?keys=Gamma2023")
        assert r.headers["X-Refs-Degraded"] == "0"
        assert "@article{Gamma2023," in r.text
        assert "datacite_key" not in r.text  # key 已改写

    def test_remote_failure_degrades(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """远端臂全挂 → 自动退 ``@misc{note={text}}`` + degraded 头/注释。"""
        tid = _mk_src_task(client)
        monkeypatch.setattr(refs, "_client", lambda: _mock_client(_fail_all))
        r = client.get(f"/api/task/{tid}/refs.bib?keys=Gamma2023")
        assert r.status_code == HTTPStatus.OK  # 绝不 502
        assert r.headers["X-Refs-Degraded"] == "1"
        body = r.text
        assert "% degraded" in body
        assert "Gamma2023" in body.split("\n")[1]
        assert "@misc{Gamma2023," in body
        assert "note = {" in body

    def test_no_id_no_text_shell(self, client: TestClient) -> None:
        """无线索 key → ``@misc{key}`` 壳，不计 degraded（远端无从尝）。"""
        tid = _mk_task(client)
        r = client.get(f"/api/task/{tid}/refs.bib?keys=GhostKey")
        assert r.headers["X-Refs-Degraded"] == "0"
        assert "@misc{GhostKey}" in r.text

    def test_kept_default_and_all(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """keys 缺省=kept 全集；``all=1``=全可解 key；kept meta 合成字段。"""
        tid = _mk_src_task(client)
        monkeypatch.setattr(refs, "_client", lambda: _mock_client(_fail_all))
        client.put(
            f"/api/task/{tid}/refs/kept",
            json={
                "key": "KeptOnly",
                "payload": {
                    "text": "Kept text",
                    "meta": {"title": "Kept Title", "year": 2025},
                },
            },
        )
        # 缺省 → 只出 kept
        r = client.get(f"/api/task/{tid}/refs.bib")
        body = r.text
        assert "KeptOnly" in body
        assert "Alpha2024" not in body
        assert "title = {Kept Title}" in body
        # all=1 → universe（.bib ∪ bibitem ∪ kept）
        r = client.get(f"/api/task/{tid}/refs.bib?all=1")
        body = r.text
        for k in ("Alpha2024", "Beta2024", "Gamma2023", "Delta2022", "KeptOnly"):
            assert k in body, k

    def test_download_and_truncation(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tid = _mk_src_task(client)
        monkeypatch.setattr(refs, "_client", lambda: _mock_client(_fail_all))
        r = client.get(f"/api/task/{tid}/refs.bib?keys=Alpha2024&download=1")
        cd = r.headers["Content-Disposition"]
        assert cd.startswith('attachment; filename="texlate-')
        assert cd.endswith('-refs.bib"')
        # 超 _MAX_REFS 截短 + X-Refs-Truncated
        many = ",".join(f"k{i}" for i in range(refs._MAX_REFS + 5))  # noqa: SLF001
        r = client.get(f"/api/task/{tid}/refs.bib?keys={many}")
        assert r.headers["X-Refs-Truncated"] == "1"
        assert "truncated" in r.text.split("\n")[1]

    def test_crossref_gate_rejects_low_overlap(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Crossref 末臂 title-overlap<0.5 → 拒收降级（不门控=毒导出）。"""
        tid = _mk_src_task(client)
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if "crossref.org" in req.url.host:
                return httpx.Response(
                    200,
                    json={"message": {"items": [{"DOI": "10.1/unrelated"}]}},
                )
            # doi.org 回一个标题零重叠的 bibtex → 门控应拒
            return httpx.Response(200, text="@article{x,\n title = {Quantum Zebra},\n}")

        monkeypatch.setattr(refs, "_client", lambda: _mock_client(handler))
        r = client.get(f"/api/task/{tid}/refs.bib?keys=Delta2022")
        assert r.headers["X-Refs-Degraded"] == "1"
        assert "Quantum Zebra" not in r.text  # 门控拒收
        assert "@misc{Delta2022," in r.text
