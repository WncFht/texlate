"""review2-web-2026-09-17 后端 API 二轮修复钉板（fix-be-api 批）。

chunks 分页端点（U1）/ ``?status=`` 枚举校验 / settings ``ignored``
回显 / JSON 端点 4MB 体闸 / retry 不注 ``options.source`` 默认 /
reader_put 字段级合并 / share manifest 字段级上限 + 注入后尺寸闸
重跑 / per-IP 配额兜底 / server health 深度 / 内容寻址产物
Cache-Control / upload spool 启停清扫。
"""

from __future__ import annotations

import json
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")
pytest.importorskip("uvicorn", reason="server extra 未装")

from conftest import (
    force_status,
    get_row,
    make_app,
    mk_api_task,
    mk_chunk_row,
    reg_artifact,
    upload_tex,
)
from starlette.testclient import TestClient

from texlate.share import (
    MANIFEST_NAME,
    ShareError,
    pack_share,
    unpack_share,
)

if TYPE_CHECKING:
    from pathlib import Path

ARXIV = "2401.00071"
KEY_B = {"X-Texlate-Key": "sk-tenant-b"}
KEY_C = {"X-Texlate-Key": "sk-tenant-c"}


def _mk_chunks(client: TestClient, tid: str, n: int) -> None:
    """插 n 条 pending chunk（seq 0..n-1）。"""
    client.portal.call(
        partial(
            client.app.state.store.insert_chunks,
            tid,
            [
                mk_chunk_row(
                    i,
                    chunk_id=f"c{i:03d}",
                    kind="para",
                    src_text=f"english segment {i}",
                )
                for i in range(n)
            ],
        )
    )


# ---------------------------------------------------------------- chunks 端点


class TestTaskChunks:
    def test_page_shape_and_total(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _mk_chunks(client, tid, 3)
        client.portal.call(
            partial(
                client.app.state.store.flush_chunk_batch,
                tid,
                [("c001", {"status": "ok", "translation": "译文一"})],
                [],
                {},
            )
        )
        r = client.get(f"/api/task/{tid}/chunks")
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["total"] == 3  # noqa: PLR2004 -- 样本量
        assert [c["seq"] for c in body["chunks"]] == [0, 1, 2]
        c1 = body["chunks"][1]
        assert c1["kind"] == "para"
        assert c1["status"] == "ok"
        assert c1["en"] == "english segment 1"
        assert c1["zh"] == "译文一"
        # pending 块 zh 回空串而非 null
        assert body["chunks"][0]["zh"] == ""

    def test_offset_limit_pagination(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        _mk_chunks(client, tid, 5)
        body = client.get(
            f"/api/task/{tid}/chunks", params={"offset": 2, "limit": 2}
        ).json()
        assert body["total"] == 5  # noqa: PLR2004 -- total 是全集非本页
        assert [c["seq"] for c in body["chunks"]] == [2, 3]

    def test_param_validation_400(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        for bad in ({"limit": 0}, {"limit": 1001}, {"offset": -1}):
            r = client.get(f"/api/task/{tid}/chunks", params=bad)
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad

    def test_empty_task(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        body = client.get(f"/api/task/{tid}/chunks").json()
        assert body == {"chunks": [], "total": 0}

    def test_unknown_task_404(self, client: TestClient) -> None:
        r = client.get("/api/task/t_0000000000000abc/chunks")
        assert r.status_code == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------- 静默吞错面


class TestStatusValidation:
    def test_bogus_status_400(self, client: TestClient) -> None:
        """非法 ``?status=`` → 400——旧面静默返空 200，调用方分不出打错参数。"""
        r = client.get("/api/tasks", params={"status": "bogus"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_valid_statuses_ok(self, client: TestClient) -> None:
        for st in ("queued", "done", "fault", "needs_auth"):
            r = client.get("/api/tasks", params={"status": st})
            assert r.status_code == HTTPStatus.OK, st


class TestSettingsIgnored:
    def test_unknown_field_echoed_ignored(self, client: TestClient) -> None:
        """未识别键不落盘但要回显——静默 200 会让调用方以为写入生效。"""
        r = client.put(
            "/api/settings",
            json={"concurrency": 4, "bogus_field": "x"},
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ignored"] == ["bogus_field"]
        # 合法键照常生效
        assert client.get("/api/settings").json()["concurrency"] == 4  # noqa: PLR2004

    def test_pseudo_fields_not_ignored(self, client: TestClient) -> None:
        """``has_api_key``/``clear_api_key`` 是合法伪字段——不进 ignored。"""
        r = client.put("/api/settings", json={"has_api_key": True, "zz": 1})
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ignored"] == ["zz"]

    def test_all_known_no_ignored_key(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"concurrency": 2})
        assert r.status_code == HTTPStatus.OK
        assert "ignored" not in r.json()


# ---------------------------------------------------------------- JSON 体闸


class TestJsonBodyCap:
    def test_oversize_body_413(self, client: TestClient) -> None:
        """JSON 端点独立 4MB 闸——与 upload 80MB 分开（be#17）。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"pad": "x" * (4 << 20)},
        )
        assert r.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert r.json()["code"] == "body_too_large"

    def test_under_cap_passes(self, client: TestClient) -> None:
        """3MB 体照常受理（202）——闸只切 >4MB。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"pad": "x" * (3 << 20)},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_upload_unaffected(self, client: TestClient) -> None:
        """multipart 路不走 JSON 闸——正常上传仍 202（spool 流式落盘后）。"""
        body = upload_tex(client)
        assert body["task_id"]


# ---------------------------------------------------------------- retry options


class TestRetryOptions:
    def test_absent_source_not_rewritten(self, client: TestClient) -> None:
        """retry 合并臂不注 ``source`` 默认——html 任务的存量 ``"html"`` 保留。"""
        tid = mk_api_task(client, ARXIV, options={"source": "html"})
        force_status(client, tid, "fault")
        r = client.post(f"/api/task/{tid}/retry", json={"options": {"concurrency": 2}})
        assert r.status_code == HTTPStatus.ACCEPTED
        opts = json.loads(get_row(client, tid)["options_json"])
        assert opts["source"] == "html"  # 旧 bug：被合并器改回 "eprint"
        assert opts["concurrency"] == 2  # noqa: PLR2004

    def test_explicit_source_overrides(self, client: TestClient) -> None:
        """body 真实出现的 ``source`` 仍校验+回写——白名单外值 400。"""
        tid = mk_api_task(client, ARXIV, options={"source": "html"})
        force_status(client, tid, "fault")
        r = client.post(
            f"/api/task/{tid}/retry", json={"options": {"source": "eprint"}}
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        opts = json.loads(get_row(client, tid)["options_json"])
        assert opts["source"] == "eprint"
        force_status(client, tid, "fault")
        bad = client.post(
            f"/api/task/{tid}/retry", json={"options": {"source": "nope"}}
        )
        assert bad.status_code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------- reader 位置


class TestReaderPutMerge:
    def _read_json(self, client: TestClient, tid: str) -> dict:
        path = client.app.state.data_dir / "tasks" / tid / "reading.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_field_level_merge(self, client: TestClient) -> None:
        """body 出现的键更新、缺席的保留；``positions`` 按侧键深合并（fe-M4）。"""
        tid = mk_api_task(client, ARXIV)
        r1 = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"en": {"page": 3}}, "zoom": 1.25},
        )
        assert r1.status_code == HTTPStatus.OK
        r2 = client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"zh": {"page": 7}}, "mode": "single"},
        )
        assert r2.status_code == HTTPStatus.OK
        data = self._read_json(client, tid)
        assert data["positions"] == {"en": {"page": 3}, "zh": {"page": 7}}
        assert data["zoom"] == 1.25  # noqa: PLR2004 -- 上写值保留
        assert data["mode"] == "single"

    def test_same_side_overwrites_other_side_kept(self, client: TestClient) -> None:
        """单栏保存只改本侧——旧整覆写会把对侧位置抹掉。"""
        tid = mk_api_task(client, ARXIV)
        client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"en": {"page": 3}, "zh": {"page": 7}}},
        )
        client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"en": {"page": 9}}},
        )
        assert self._read_json(client, tid)["positions"] == {
            "en": {"page": 9},
            "zh": {"page": 7},
        }

    def test_non_dict_positions_replaces(self, client: TestClient) -> None:
        """新 positions 非 dict 时整体生效（reset 语义）——不做交叉合并。"""
        tid = mk_api_task(client, ARXIV)
        client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": {"en": {"page": 3}}},
        )
        client.put(
            f"/api/task/{tid}/reader/position",
            json={"positions": "reset"},
        )
        assert self._read_json(client, tid)["positions"] == "reset"


# ---------------------------------------------------------------- share manifest 字段上限

_PARTS: dict[str, object] = {
    "arxiv_id": "1706.03762",
    "version": "v5",
    "model": "deepseek-chat",
    "prompt_ver": "xlat-prompt-v3",
    "target_lang": "zh-CN",
    "glossary_hash": "",
    "pipeline_ver": "texlate-0.1.0|xlat-prompt-v3",
}


def _make_work(root: Path) -> Path:
    """最小产物两件套任务目录（zh-src.zip + dual.json = REQUIRED）。"""
    w = root / "task"
    w.mkdir()
    (w / "dual.json").write_text(
        json.dumps({"version": 1, "documents": {}, "chunks": []}),
        encoding="utf-8",
    )
    with zipfile.ZipFile(w / "zh-src.zip", "w") as zf:
        zf.writestr("main.tex", "\\documentclass{article}x")
    return w


class TestManifestFieldCaps:
    """``_MANIFEST_FIELD_MAX`` 256B 字段级闸——双侧同口径（be#4）。"""

    def test_pack_overlong_contributor_rejected(self, tmp_path: Path) -> None:
        work = _make_work(tmp_path)
        with pytest.raises(ShareError, match="contributor"):
            pack_share(work, {**_PARTS, "contributor": "x" * 300})

    def test_pack_overlong_created_at_rejected(self, tmp_path: Path) -> None:
        work = _make_work(tmp_path)
        with pytest.raises(ShareError, match="created_at"):
            pack_share(work, {**_PARTS, "created_at": "x" * 300})

    def test_pack_overlong_key_part_rejected(self, tmp_path: Path) -> None:
        work = _make_work(tmp_path)
        with pytest.raises(ShareError, match="too large"):
            pack_share(work, {**_PARTS, "model": "m" * 300})

    def test_field_at_cap_ok(self, tmp_path: Path) -> None:
        """恰 256B 放行——界值内不受闸。"""
        work = _make_work(tmp_path)
        bundle = pack_share(
            work, {**_PARTS, "contributor": "x" * 256}, out_dir=tmp_path / "o"
        )
        mf = unpack_share(bundle, tmp_path / "d")
        assert mf.contributor == "x" * 256

    def test_unpack_overlong_field_rejected(self, tmp_path: Path) -> None:
        """篡改包的 oversized contributor → unpack 同口径拒。"""
        work = _make_work(tmp_path)
        bundle = pack_share(work, _PARTS, out_dir=tmp_path / "o")
        with zipfile.ZipFile(bundle) as zf:
            doc = json.loads(zf.read(MANIFEST_NAME))
            payloads = {n: zf.read(n) for n in zf.namelist() if n != MANIFEST_NAME}
        doc["contributor"] = "x" * 300
        evil = tmp_path / "evil.share.zip"
        with zipfile.ZipFile(evil, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(doc, ensure_ascii=False))
            for name, blob in payloads.items():
                zf.writestr(name, blob)
        with pytest.raises(ShareError, match="contributor"):
            unpack_share(evil, tmp_path / "d")


class TestShareImportOptionsCap:
    """``options["share"]`` 在 64KB 闸之后注入——注入后尺寸闸重跑（be#4 第二臂）。"""

    def _import(self, client: TestClient, bundle: Path, options: dict) -> int:
        return client.post(
            "/api/share/import",
            files={"file": ("b.share.zip", bundle.read_bytes(), "application/zip")},
            data={"options": json.dumps(options)},
        ).status_code

    def test_injection_pushes_over_cap_400(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        """用户 options 界内 + share 审计载荷 → 总序列化超 64KB → 400。"""
        bundle = pack_share(_make_work(tmp_path), _PARTS, out_dir=tmp_path / "o")
        # 用户侧 ~65.4KB 过首闸；注入 ~0.4KB share 载荷后必超 64KB
        pad = "x" * (65536 - 11 - 200)
        assert self._import(client, bundle, {"pad": pad}) == HTTPStatus.BAD_REQUEST

    def test_under_cap_imports_ok(self, tmp_path: Path, client: TestClient) -> None:
        bundle = pack_share(_make_work(tmp_path), _PARTS, out_dir=tmp_path / "o")
        assert self._import(client, bundle, {"pad": "x" * 1000}) == HTTPStatus.ACCEPTED


# ---------------------------------------------------------------- quota per-IP


class TestPerIpQuota:
    def test_key_rotation_cannot_evade(self, server_client: TestClient) -> None:
        """同 IP 换 key 开新 tenant 桶——per-IP 兜底桶照样 429（be#2）。"""
        server_client.portal.call(
            partial(
                server_client.app.state.settings_store.save,
                {"quota_max_tasks": 1},
            )
        )
        mk_api_task(server_client, "2401.00091", headers=KEY_B)
        r = server_client.post(
            "/api/arxiv/2401.00092/translate", json={}, headers=KEY_C
        )
        assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS
        assert r.json()["code"] == "quota_exceeded"
        assert "同 IP" in r.json()["detail"]


# ---------------------------------------------------------------- health / cache


class TestHealthDepth:
    def test_server_mode_db_and_queue(self, server_client: TestClient) -> None:
        """server 形态 ``{ok, db, queue_depth}``——db 是真 SELECT 探测。"""
        body = server_client.get("/api/health").json()
        assert body["ok"] is True
        assert body["db"] is True
        assert isinstance(body["queue_depth"], int)


class TestFilesCacheControl:
    def _register(self, client: TestClient, tid: str) -> str:
        """落 zh.pdf + 登记 → 返回 sha256。"""
        return reg_artifact(client, tid, "zh_pdf", "zh.pdf")["sha256"]

    def test_version_match_immutable(self, client: TestClient) -> None:
        """``?version=<sha256>`` 命中 → ``private, immutable``（be#11）。"""
        tid = mk_api_task(client, ARXIV)
        sha = self._register(client, tid)
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": sha})
        assert r.status_code == HTTPStatus.OK
        assert r.headers["Cache-Control"] == "private, immutable"

    def test_no_version_no_store(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        self._register(client, tid)
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.headers["Cache-Control"] == "no-store"

    def test_version_mismatch_409(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        self._register(client, tid)
        r = client.get(f"/api/files/{tid}/zh.pdf", params={"version": "0" * 64})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "version_mismatch"


# ---------------------------------------------------------------- spool 清扫


class TestSpoolSweep:
    def test_lifespan_sweeps_stale_parts(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """崩溃残留的 ``tmp/upload-spool/.part-*`` 在下次启动扫掉。"""
        with TestClient(make_app(tmp_path)):
            pass
        spool = tmp_path / "data" / "tmp" / "upload-spool"
        stale = spool / ".part-deadbeef"
        stale.write_bytes(b"x")
        with TestClient(make_app(tmp_path)):
            pass
        assert not stale.exists()
        assert spool.is_dir()
