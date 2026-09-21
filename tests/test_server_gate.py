"""SEC-1..7 入站闸回归（server-security-fix）：

share 解压两闸 / server 匿名写 401+读面独立桶 / mutating 跨站与 Content-Type /
settings/test 跨槽 / upload 点文件名 / local Host 白名单 / model 控制字符。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import MINI_TEX, make_app, refused_base_url, upload_tex
from starlette.testclient import TestClient

from texlate.server.settings import SettingsStore, resolve_auth, validate_model
from texlate.share import (
    _ARTIFACT_MAX,
    SHARE_FORMAT,
    ShareError,
    share_key,
    unpack_share,
)

if TYPE_CHECKING:
    from pathlib import Path

ARXIV = "2401.00031"
KEY = {"X-Texlate-Key": "sk-tenant-a"}


def _bundle(
    path: Path,
    artifacts: dict[str, bytes],
    declared: dict[str, int] | None = None,
) -> Path:
    """share bundle 构造器：sha256 全真值；``declared`` 可谎报 manifest bytes。"""
    parts = {
        "arxiv_id": "2401.00031",
        "version": "v1",
        "model": "m",
        "prompt_ver": "p1",
        "target_lang": "zh-CN",
        "glossary_hash": "",
        "pipeline_ver": "t|p1",
    }
    manifest = {
        "format": SHARE_FORMAT,
        "share_key": share_key(
            parts["arxiv_id"],
            parts["version"],
            parts["model"],
            parts["prompt_ver"],
            parts["target_lang"],
            parts["glossary_hash"],
            parts["pipeline_ver"],
        ),
        "key_parts": parts,
        "artifacts": {
            n: {
                "sha256": hashlib.sha256(b).hexdigest(),
                "bytes": (declared or {}).get(n, len(b)),
            }
            for n, b in artifacts.items()
        },
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for n, b in artifacts.items():
            zf.writestr(n, b)
    return path


def _flood_arts() -> dict[str, bytes]:
    """``_ARTIFACT_MAX``+1 条的洪泛产物集——两枚合法名 + junk 填满到超 cap 一条。"""
    arts = {"zh-src.zip": b"x", "dual.json": b"{}"}
    arts.update(
        {f"junk-{i}.bin": b"z" for i in range(_ARTIFACT_MAX + 1 - len(arts))}
    )
    return arts


class TestShareInflateCaps:
    """SEC-1：artifacts 条数上限 + 聚合解压上限，拒绝全落 ShareError。"""

    def test_artifact_count_cap(self, tmp_path: Path) -> None:
        arts = _flood_arts()
        with pytest.raises(ShareError, match="too many artifacts"):
            unpack_share(_bundle(tmp_path / "b.zip", arts), tmp_path / "out")

    def test_aggregate_cap(self, tmp_path: Path) -> None:
        """声明 bytes 合计超 _INFLATED_MAX 即拒——不需真写 300MB 成员。

        单成员声明仍须 ≤_MEMBER_MAX（过大先撞 malformed 闸）——两枚
        200MB 声明合计 400MB 触发聚合闸。
        """
        bundle = _bundle(
            tmp_path / "b.zip",
            {
                "zh-src.zip": b"x",
                "dual.json": b"{}",
                "pad1.bin": b"z",
                "pad2.bin": b"z",
            },
            declared={"pad1.bin": 200 << 20, "pad2.bin": 200 << 20},
        )
        with pytest.raises(ShareError, match="too large in aggregate"):
            unpack_share(bundle, tmp_path / "out")

    def test_legit_bundle_still_unpacks(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        mf = unpack_share(
            _bundle(
                tmp_path / "b.zip",
                {"zh-src.zip": b"zz", "dual.json": b"{}", "zh.pdf": b"%PDF"},
            ),
            dest,
        )
        assert (dest / "dual.json").is_file()
        assert mf.share_key

    def test_http_import_flood_400(self, client: TestClient, tmp_path: Path) -> None:
        """HTTP 面：洪泛包经 /api/share/import → 400 share_invalid。"""
        bundle = _bundle(tmp_path / "b.zip", _flood_arts())
        r = client.post(
            "/api/share/import",
            files={"file": ("b.share.zip", bundle.read_bytes())},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "share_invalid"


class TestServerAnonGate:
    """SEC-2：server 形态匿名 mutation 401；读面独立匿名桶、绝不带部署方 key。"""

    def test_anon_mutations_401(self, server_client: TestClient) -> None:
        assert (
            server_client.post(f"/api/arxiv/{ARXIV}/translate", json={}).status_code
            == HTTPStatus.UNAUTHORIZED
        )
        assert (
            server_client.post(
                "/api/upload",
                files={"file": ("main.tex", MINI_TEX.encode())},
            ).status_code
            == HTTPStatus.UNAUTHORIZED
        )
        assert (
            server_client.delete("/api/task/t_0000000000000000").status_code
            == HTTPStatus.UNAUTHORIZED
        )
        assert (
            server_client.post("/api/task/t_0000000000000000/cancel").status_code
            == HTTPStatus.UNAUTHORIZED
        )
        assert (
            server_client.put("/api/settings", json={}).status_code
            == HTTPStatus.UNAUTHORIZED
        )
        body = server_client.post(f"/api/arxiv/{ARXIV}/translate", json={}).json()
        assert body["code"] == "auth_required"

    def test_anon_reads_open_anon_bucket(self, server_client: TestClient) -> None:
        """匿名读面通，只见匿名桶——k-A 的任务对匿名者 404。"""
        r = server_client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"model": "m"}, headers=KEY
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        tid = r.json()["task_id"]
        assert server_client.get("/api/tasks").status_code == HTTPStatus.OK
        assert server_client.get("/api/tasks").json()["tasks"] == []
        assert server_client.get(f"/api/task/{tid}").status_code == HTTPStatus.NOT_FOUND

    def test_anon_never_inherits_settings_key(self, tmp_path: Path) -> None:
        """resolve_auth 单元钉：server+settings 有 key、无 header → api_key 空。"""
        store = SettingsStore(tmp_path / "d")
        (tmp_path / "d").mkdir(parents=True, exist_ok=True)
        store.save({"api_key": "sk-deployer"})
        auth = resolve_auth(store.load(), mode="server", salt="s")
        assert auth.api_key == ""
        assert auth.source == "none"
        local = resolve_auth(store.load(), mode="local", salt="s")
        assert local.api_key == "sk-deployer"

    def test_keyed_mutation_still_works(self, server_client: TestClient) -> None:
        r = server_client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"model": "m"}, headers=KEY
        )
        assert r.status_code == HTTPStatus.ACCEPTED


class TestCrossSiteGate:
    """SEC-3：fetch-metadata/Origin 同源闸 + JSON Content-Type。"""

    def test_local_cross_site_rejected(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_local_foreign_origin_rejected(self, client: TestClient) -> None:
        """Origin 须与 Host 同源含端口——localhost:9999 也不再是合法源。"""
        for origin in ("https://evil.example", "http://localhost:9999"):
            r = client.post(
                f"/api/arxiv/{ARXIV}/translate",
                json={},
                headers={"Origin": origin},
            )
            assert r.status_code == HTTPStatus.FORBIDDEN, origin

    def test_same_origin_accepted(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"model": "m"},
            headers={"Origin": "http://localhost"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_server_cross_site_rejected(self, server_client: TestClient) -> None:
        for headers in (
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "https://evil.example"},
        ):
            r = server_client.post(
                f"/api/arxiv/{ARXIV}/translate",
                json={"model": "m"},
                headers={**KEY, **headers},
            )
            assert r.status_code == HTTPStatus.FORBIDDEN, headers

    def test_server_cors_allowlist_passes(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """allowlist 内 Origin 的跨站 mutation 是 CORS 部署面——放行。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        data = tmp_path / "data"
        data.mkdir()
        SettingsStore(data).save({"cors_origins": ["https://ok.example"]})
        with TestClient(make_app(tmp_path)) as c:
            r = c.post(
                f"/api/arxiv/{ARXIV}/translate",
                json={"model": "m"},
                headers={
                    **KEY,
                    "Origin": "https://ok.example",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
            assert r.status_code == HTTPStatus.ACCEPTED

    def test_non_browser_no_headers_passes(self, server_client: TestClient) -> None:
        """无 Origin/fetch-site 的 curl 式客户端过闸（再走 auth）。"""
        r = server_client.post(
            f"/api/arxiv/{ARXIV}/translate", json={"model": "m"}, headers=KEY
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_json_content_type_required(self, client: TestClient) -> None:
        """非空 body 非 application/json → 415（simple-request CSRF 封死）。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=b'{"options":{}}',
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        assert r.json()["code"] == "unsupported_media_type"

    def test_charset_param_tolerated(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            content=b'{"options":{}}',
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert r.status_code == HTTPStatus.ACCEPTED

    def test_empty_body_no_ct_passes(self, client: TestClient) -> None:
        """无 body 无 CT 的 POST 照旧（retry/cancel 类 curl 式调用）。"""
        tid = upload_tex(client)["task_id"]
        r = client.post(f"/api/task/{tid}/cancel")
        assert r.status_code == HTTPStatus.OK


class TestRootPathGate:
    """``--root-path``/反代子路径部署：路由按剥掉 ``root_path`` 的路径匹配，
    闸若看 ``request.url.path``（含 ``root_path``）则 ``/tex/api/…`` 骗过
    ``startswith("/api")`` 而路由照样命中——匿名 401/跨站闸/no-store 全失守
    （gate-redteam 发现）。闸与路由必须共用 ``get_route_path`` 视图。"""

    def test_server_mode_anon_and_crosssite_under_root_path(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        with TestClient(make_app(tmp_path), root_path="/tex") as c:
            r = c.post(f"/tex/api/arxiv/{ARXIV}/translate", json={})
            assert r.status_code == HTTPStatus.UNAUTHORIZED
            r = c.post(
                f"/tex/api/arxiv/{ARXIV}/translate",
                json={"model": "m"},
                headers={**KEY, "Sec-Fetch-Site": "cross-site"},
            )
            assert r.status_code == HTTPStatus.FORBIDDEN
            r = c.post(
                f"/tex/api/arxiv/{ARXIV}/translate",
                json={"model": "m"},
                headers=KEY,
            )
            assert r.status_code == HTTPStatus.ACCEPTED
            assert (
                c.get("/tex/api/tasks", headers=KEY).headers["cache-control"]
                == "no-store"
            )

    def test_local_mode_foreign_origin_under_root_path(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        with TestClient(make_app(tmp_path), root_path="/tex") as c:
            r = c.post(
                f"/tex/api/arxiv/{ARXIV}/translate",
                json={},
                headers={"Origin": "https://evil.example"},
            )
            assert r.status_code == HTTPStatus.FORBIDDEN


class TestSettingsTestCrossSlot:
    """SEC-4：body.base_url 提供则 body.api_key 必须同给。"""

    def test_base_url_without_key_400(self, client: TestClient) -> None:
        client.put("/api/settings", json={"api_key": "sk-stored"})
        r = client.post("/api/settings/test", json={"base_url": "http://127.0.0.1:9"})
        assert r.status_code == HTTPStatus.BAD_REQUEST

    def test_base_url_with_key_probes(self, client: TestClient) -> None:
        with refused_base_url() as base_url:
            r = client.post(
                "/api/settings/test",
                json={
                    "base_url": base_url,
                    "api_key": "sk-explicit",
                },
            )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["ok"] is False

    def test_stored_pair_probe_still_ok(self, client: TestClient) -> None:
        """不带覆盖 → 用已存配置探活，不触发跨槽闸（连通性无关断言）。"""
        client.put("/api/settings", json={"api_key": "sk-stored"})
        r = client.post("/api/settings/test", json={})
        assert r.status_code == HTTPStatus.OK
        assert "ok" in r.json()


class TestUploadFilename:
    """SEC-5：``.``/``..`` 文件名 400 且无孤儿目录。"""

    def test_dotdot_400_no_orphan(self, client: TestClient) -> None:
        r = client.post("/api/upload", files={"file": ("..", MINI_TEX.encode())})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        tasks = client.app.state.data_dir / "tasks"
        assert not tasks.exists() or list(tasks.iterdir()) == []

    def test_dot_and_normal_names_ok(self, client: TestClient) -> None:
        for fname in (".", "a/b/c.tex", "a\\b.tex", "x y.tex"):
            r = client.post("/api/upload", files={"file": (fname, MINI_TEX.encode())})
            assert r.status_code == HTTPStatus.ACCEPTED, fname

    def test_overlong_name_400_not_500(self, client: TestClient) -> None:
        """净化后名 >NAME_MAX(255B)：建行前 400——漏闸时 write_bytes 抛
        ENAMETOOLONG 成 500（gate-redteam 发现）。255 恰界仍收。"""
        r = client.post("/api/upload", files={"file": ("x" * 256, MINI_TEX.encode())})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        r = client.post(
            "/api/upload", files={"file": ("dir/" + "y" * 300, MINI_TEX.encode())}
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        r = client.post("/api/upload", files={"file": ("z" * 255, MINI_TEX.encode())})
        assert r.status_code == HTTPStatus.ACCEPTED


class TestLocalHostGate:
    """SEC-6：local 形态 Host 剥端口须 loopback——DNS rebinding 收口。"""

    def test_foreign_host_rejected(self, client: TestClient) -> None:
        for host in ("evil.example", "evil.example:8765", "169.254.1.1"):
            r = client.get("/api/health", headers={"Host": host})
            assert r.status_code == HTTPStatus.FORBIDDEN, host

    def test_loopback_hosts_ok(self, client: TestClient) -> None:
        for host in ("localhost", "localhost:8765", "127.0.0.1:9", "[::1]:9"):
            r = client.get("/api/health", headers={"Host": host})
            assert r.status_code == HTTPStatus.OK, host

    def test_server_mode_host_free(self, server_client: TestClient) -> None:
        """server 形态不查 Host（反代/域名部署面）。"""
        r = server_client.get("/api/health", headers={"Host": "app.example"})
        assert r.status_code == HTTPStatus.OK


class TestModelControlChars:
    """SEC-7：model 名拒控制字符——log/事件注入面收口。"""

    def test_validate_model_rejects_ctrl(self) -> None:
        for bad in ("m\ninjected", "m\rx", "m\tx", "m\x00", "m\x1b[31m"):
            with pytest.raises(ValueError, match="invalid model"):
                validate_model(bad)

    def test_validate_model_allows_normal(self) -> None:
        assert validate_model("openai/gpt-4o mini") == "openai/gpt-4o mini"
        assert validate_model("通义-max") == "通义-max"

    def test_translate_bad_model_400(self, client: TestClient) -> None:
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={"model": "m\ninjected"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
