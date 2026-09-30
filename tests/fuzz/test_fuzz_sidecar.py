"""server 旁路件对抗性性质 fuzz——settings/babeldoc/staticfiles/__main__/cmap 资源。

不变量清单（oracle 均为独立代码路径或固定语料）：

settings.py 侧：

- ``validate_base_url``：scheme∈http(s)、无 userinfo/query/fragment、远程
  http 仅放行 loopback/tailnet（CGNAT 边界 100.64.0.0/10 两端取反、
  ``*.ts.net`` 后缀、``::1``/IPv6 映射/十六进制与十进制 IP 伪装全拒）；
  任意输入只许 ``ValueError`` 或归一化串；
- ``validate_model``：空/超 200/非 printable 拒，CJK/emoji 放行；
- ``_check_cors_origins``：非字符串数组拒、逐项 ``_parse_origin``、去重保序；
- ``SettingsStore``：``save``→``load`` round-trip 全字段回读一致；
  ``api_key`` 空串不覆盖、``clear_api_key`` 显式清且压过同帧 api_key、
  ``has_api_key`` 伪字段不落盘；两文件恒 0600；``public()`` 永不携带
  ``api_key``；未知键写进文件但 ``load`` 滤掉；base_url 切换按
  connections 槽召回旧 key（A→B→A 钥匙归位）；``load`` 对非 dict/
  截断 JSON 与错型字段容错回落；多线程并发 ``save`` 文件永远是整份
  JSON（tmp+rename 原子性）；``connections()`` 滤非 dict 值；
- ``resolve_auth``：``header > settings > env`` 逐项回落；server 形态无
  header key 时绝不外借 settings/env 凭据（匿名桶）；非法 header
  base_url/model 抛 ``ValueError`` 不静默回落；``tenant_for`` 确定性 +
  local 恒 ``local``；
- ``scrub``/``RedactFilter``：显式 key + 已知 secret 形态抹除且幂等；
  命中时 ``record.msg`` 改写 + ``args`` 清空防二次格式化；未命中记录
  ``msg``/``args`` 原样；``key_provider`` 抛错不炸日志；
  ``install_log_scrub`` 重复装配幂等（每 logger/handler 恰一枚 filter）；
- ``server_salt``：首轮生成 32hex 0600 持久；空白文件视为未初始化重生成；
- env 辅助面：``cache_scope`` 合法值/非法回落；``env_key_for``
  ``TEXLATE_API_KEY`` 优先于 provider 兜底；``data_dir`` 0700；
  ``provider_presets`` active/has_env_key 与 url/env 一致。

babeldoc.py 侧（不 spawn 真进程——``_Feed``/``assess_tracking``/``_judge_run``/
``harvest_outputs``/``write_config`` 全离线）：

- ``_Feed``：任意字节流（含 ANSI/截断 UTF-8/NUL/仅 ``\r``/大块）不抛；
  ``errors`` deque 恒 ≤ ``_MAX_ERRORS`` 且 keep-last；``_tail`` 恒 ≤40；
  ``\r``/``\n``/``\r\n`` 帧边界等价 + 跨 feed carry + flush 收尾；
  统计行/完成行/错误行归类；同 pct 不重复回调；进度帧不进 ``on_log``；
- ``assess_tracking``：三节合计、part_* 兜底、截断/不可读/非 dict 顶层
  容错成零计数；
- ``_judge_run`` 判定矩阵：``status∈{ok,degraded,failed}``、``error_code``
  恰在 failed 时非空、``retryable=False`` 恰为 ``scanned_pdf``；
- ``_classify_rc``：auth>rate>compile 优先级、空 feed 兜默认消息；
- ``harvest_outputs``：stem 含 glob 元字符（``[``/``*``/``?``/空格）经
  ``glob_escape`` 字面命中不误配、``.no_watermark.`` 优先、缺目录→``{}``；
- ``write_config``：落盘即 0600、``tomllib`` 可解析回读出同一 key
  （引号/换行/空格注入全被 ``json.dumps`` 转义收编）；
- ``build_argv``：任意 api_key 值（含 ``--`` 前缀形）绝不进 argv；
- ``write_glossary_csv``：BOM + 敌对字段（引号/换行/NUL）经 csv 读回一致；
- ``cjk_ratio``：坏文件/缺席/空文件一律 ``None``（sanity 信号永不炸主链）；
- ``default_timeout`` env 解析矩阵。

staticfiles.py / ``__main__`` / cmap 资源：

- ``spa_dir``：env 目录无 ``index.html`` 回落包内；``mount_spa`` 产物缺席
  返回 ``False`` 不挂；缓存策略按 serve 出的文件归一（``index.html``
  ``no-cache`` 含子目录 index、``assets/`` 下任意深度 ``immutable``、
  其余默认无 ``Cache-Control``）；软链目录 realpath 基准下缓存头仍对；
  穿越形请求（``..``/``%2e``/双写）全 4xx；
- ``__main__._port``：1-65535 闸；``int()`` 怪癖形（空白/``+``/下划线/
  全角数字）收敛为合法端口；``main()`` 未知参数 ``SystemExit(2)``；
- ``compile/cmaps/Adobe-GB1-UCS2``：注入层共享资源存在且 CMap 结构完整
  （``begincmap``/``endcmap`` + bf 段）。
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import secrets
import stat
import threading
import tomllib
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from _fuzzkit import fuzz_rng
from conftest import make_app

from texlate.server import babeldoc as bd
from texlate.server import settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import ClassVar

    from starlette.testclient import TestClient

_FEED_BYTES = 300
_FEED_CHUNKS = 200
_SAVE_THREADS = 8
_SAVE_ITERS = 25


def _store_with(root: Path, data: object) -> settings.SettingsStore:
    """手改 settings.json 现场（load 容错路径的输入面）。"""
    (root / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    return settings.SettingsStore(root)


def _job(tmp_path: Path, stem: str, **kw: object) -> bd.BabeldocJob:
    args: dict[str, Any] = {
        "src": tmp_path / f"{stem}.pdf",
        "outdir": tmp_path / "out",
        "workdir": tmp_path / "work",
        "model": "m",
        "base_url": "",
    }
    args.update(kw)
    return bd.BabeldocJob(**args)  # type: ignore[arg-type]


# ---------------------------------------------------------------- base_url


class TestValidateBaseUrl:
    """``validate_base_url`` 接受/拒绝矩阵 + 全输入面只许 ``ValueError``。"""

    _REJECT: ClassVar[tuple[str, ...]] = (
        "ftp://h",
        "h",
        "",
        "   ",
        "http://",
        "https://",
        "http://user@localhost",
        "http://user:pw@localhost",
        "https://a.com/?x=1",
        "https://a.com#f",
        "http://evil.com",  # 远程 http 拒
        "http://192.168.1.1",  # 私网非 tailnet 拒
        "http://10.0.0.1",
        "http://localhost.evil.com",  # 后缀伪装
        "http://127.0.0.1.evil.com",
        "http://0x7f000001",  # 十六进制 IP 伪装
        "http://2130706433",  # 十进制 IP 伪装（127.0.0.1）
        "http://0177.0.0.1",  # 八进制伪装
        "http://[::ffff:127.0.0.1]",  # v4 映射 v6 不在白名单
        "http://100.63.255.255",  # CGNAT 下沿之外
        "http://100.128.0.1",  # CGNAT 上沿之外
        "http://evil.ts.net.evil.com",  # ts.net 后缀伪装
        "javascript://x",
        "file:///etc/passwd",
        "//localhost",
    )

    _ACCEPT: ClassVar[tuple[str, ...]] = (
        "http://localhost",
        "http://localhost:8080",
        "http://127.0.0.1:3003",
        "http://[::1]:3003",
        "http://a.ts.net",
        "http://host.tail-scale.ts.net:443",
        "http://100.64.0.1",  # CGNAT 下沿
        "http://100.127.255.255",  # CGNAT 上沿
        "https://api.deepseek.com",
        "https://a.com.",
        "HTTPS://A.COM/",  # 大小写/尾斜杠归一化
        "  http://localhost  ",  # 首尾空白 strip
        "http://localhost/v1",  # 后缀剥除 → 裸根
        "http://localhost/v1/chat/completions",
        "https://h/sub/path",  # path 放行（反代子路径部署形）
        "https://a.com/?",  # 空 query 归一化为无 query
        "https://例え.jp",
    )

    def test_reject_corpus(self) -> None:
        from urllib.parse import urlsplit  # noqa: PLC0415 -- 校验面聚一处

        for url in self._REJECT:
            with pytest.raises(ValueError, match=r"."):
                settings.validate_base_url(url)
        # 拒绝语义必须独立于 urlsplit 的宽松解析——守卫不外包
        assert urlsplit("http://user@localhost").username

    def test_accept_corpus(self) -> None:
        for url in self._ACCEPT:
            out = settings.validate_base_url(url)
            assert out == out.strip().rstrip("/"), url

    def test_random_never_other_exception(self) -> None:
        """任意垃圾串：只许 ``ValueError`` 或合法串——不许第三类异常逃逸。"""
        from urllib.parse import urlsplit  # noqa: PLC0415

        rng = fuzz_rng(20260917)
        alphabet = "ab:/.@?#[]=&%\x00-_~é中"
        for _ in range(400):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randrange(40)))
            try:
                out = settings.validate_base_url(s)
            except ValueError:
                continue
            u = urlsplit(out)
            assert u.scheme in ("http", "https"), s
            assert u.hostname, s

    def test_port_never_validated(self) -> None:
        """端口/netloc 形状不合法 → 应拒（``_parse_origin`` 回 None、
        ``validate_base_url`` 抛 ``ValueError``）。"""
        for url in (
            "http://h:abc",
            "https://h:99999",
            "http://h:80:90",
            "http://h:-1",
            "https://h:",
            "http://localhost:abc",
            "http://h:0x50",
            "http://localhost:99999",
            "http://@localhost",
        ):
            assert settings._parse_origin(url) is None, url  # noqa: SLF001
            with pytest.raises(ValueError, match=r"."):
                settings.validate_base_url(url)


# ---------------------------------------------------------------- model/origin


class TestValidateModel:
    """``validate_model`` 边界：长度/可打印性/空白。"""

    def test_model_corpus(self) -> None:
        for value in (
            "",
            "   ",
            "\t\n ",
            "a" * 201,
            "m\x00del",
            "line\nbreak",
            "ctl\x7fchar",
            "c1\x9fsep",
            "sep\u2028line",  # U+2028 不可打印
            "x\ud800y",  # 孤 surrogate 不可打印
        ):
            with pytest.raises(ValueError, match="invalid model"):
                settings.validate_model(value)
        for value in (
            "gpt-4o-mini",
            "a" * 200,  # 边界放行
            "model 名",
            "emoji-\U0001f600-ok",
            "  padded  ",  # strip 后有效
        ):
            out = settings.validate_model(value)
            assert out == out.strip(), value
            assert out.isprintable(), value


class TestCorsOrigins:
    """``_check_cors_origins``/``_parse_origin`` 校验面。"""

    def test_dedupe_and_shape(self) -> None:
        raw = ["http://a.com", "https://b.com:8443", "http://a.com", "http://a.com/"]
        out = settings._check_cors_origins(raw)  # noqa: SLF001
        assert out == ["http://a.com", "https://b.com:8443"]
        for value in ("http://a.com", ["http://a.com", 123], [None], [["x"]]):
            with pytest.raises(ValueError, match=r"."):
                settings._check_cors_origins(value)  # noqa: SLF001

    def test_origin_corpus(self) -> None:
        for raw in (
            "not-a-url",
            "ftp://h",
            "http://u@h",
            "http://u:p@h",
            "http://h/p",
            "http://h?x=1",
            "http://h#f",
            "//h",
            "",
        ):
            assert settings._parse_origin(raw) is None, raw  # noqa: SLF001
        for raw in (
            "http://h",
            "https://h:8443",
            "http://a.ts.net",
            "http://[::1]:3000",
            "http://h/",  # 尾斜杠剥除
            "http://localhost:8080",
        ):
            out = settings._parse_origin(raw)  # noqa: SLF001
            assert out is not None, raw
            assert out == out.rstrip("/"), raw

    def test_origin_case_normalized(self) -> None:
        """大写 scheme/host 归一化为小写——原样存就是永不命中的死条目。"""
        for raw in ("HTTP://EXAMPLE.COM", "http://EXAMPLE.COM"):
            out = settings._parse_origin(raw)  # noqa: SLF001
            assert out in (None, raw.lower()), raw
        # 大小写折叠与默认端口剥除复合（端口契约归 test_fuzz_server 钉）
        assert settings._parse_origin("Https://H.COM:443") == "https://h.com"  # noqa: SLF001


# ---------------------------------------------------------------- store 容错读


class TestLoadTolerance:
    """``load()`` 对手改/损坏文件的容错契约。"""

    def test_corrupt_falls_back(self, tmp_path: Path) -> None:
        for i, content in enumerate(
            (
                "not json at all",
                '{"base_url": "http://x",',  # 截断
                "[1, 2, 3]",  # 非 dict
                '"just a string"',
                "null",
                "123",
            )
        ):
            root = tmp_path / f"c{i}"
            root.mkdir()
            (root / "settings.json").write_text(content, encoding="utf-8")
            data = settings.SettingsStore(root).load()
            assert data["base_url"], content
            assert data["model"], content
            assert isinstance(data["concurrency"], int), content

    def test_field_fallbacks(self, tmp_path: Path) -> None:
        cases = (
            ("concurrency", "abc", 3),  # 不可转 → 默认 3
            ("concurrency", 0, 3),  # 0 falsy → 默认 3（`value or 3` 口径）
            ("concurrency", -5, 1),  # 负 → clamp 1
            ("concurrency", 2.9, 2),  # float 截断
            ("quota_max_tasks", "abc", 0),
            ("quota_max_tasks", -7, 0),  # 负 → 0（不限）
            ("quota_max_bytes", "x", 0),
            ("cors_origins", "http://a", []),  # 非 list → []
            ("cors_origins", [123, "http://ok", "bad"], ["http://ok"]),
        )
        for i, (field, raw, expected) in enumerate(cases):
            root = tmp_path / f"f{i}"
            root.mkdir()
            data = _store_with(root, {field: raw}).load()
            assert data[field] == expected, (field, raw)

    def test_load_is_json_serializable(self, tmp_path: Path) -> None:
        """``public()`` 出参恒可 JSON 序列化（错型入参经 ``str()``/容错收编）。"""
        data = _store_with(
            tmp_path,
            {
                "api_key": {"nested": 1},
                "base_url": 123,
                "cors_origins": [{"o": 1}],
                "quota_max_tasks": "9",
            },
        ).public()
        json.dumps(data)
        assert "api_key" not in data

    def test_inf_bricks_load(self, tmp_path: Path) -> None:
        """inf 量值 → 期望容错回落而非 ``OverflowError`` 穿透。"""
        for i, content in enumerate(
            (
                '{"concurrency": 1e999}',
                '{"concurrency": -1e999}',
                '{"concurrency": Infinity}',
                '{"quota_max_tasks": 1e999}',
                '{"quota_max_bytes": -Infinity}',
            )
        ):
            root = tmp_path / f"i{i}"
            root.mkdir()
            (root / "settings.json").write_text(content, encoding="utf-8")
            data = settings.SettingsStore(root).load()
            assert isinstance(data["concurrency"], int), content

    def test_surrogate_bricks_save(self, tmp_path: Path) -> None:
        """文件里一个孤 surrogate → 期望 load 消毒或 save 不炸。"""
        store = _store_with(tmp_path, {"model": "x\ud800y"})
        merged = store.save({"concurrency": 4})
        assert merged["model"].isprintable()

    def test_enum_fields_sanitized(self, tmp_path: Path) -> None:
        for i, (field, raw, fallback) in enumerate(
            (("engine", "nuclear", "auto"), ("target_lang", "klingon", "zh-CN"))
        ):
            root = tmp_path / f"e{i}"
            root.mkdir()
            data = _store_with(root, {field: raw}).load()
            assert data[field] == fallback, field


# ---------------------------------------------------------------- store 语义


class TestStoreSemantics:
    """``save``→``load`` 合并语义 + 文件面不变量。"""

    def test_round_trip_and_file_modes(self, tmp_path: Path) -> None:
        store = settings.SettingsStore(tmp_path)
        merged = store.save(
            {
                "model": "m-x",
                "api_key": "sk-rt-12345678",
                "concurrency": 7,
                "engine": "tectonic",
                "target_lang": "zh-TW",
                "quota_max_tasks": "5",
                "cors_origins": ["http://a.com", "https://b.com:9"],
                "context_guidance": False,
            }
        )
        loaded = store.load()
        for k in merged:
            assert loaded[k] == merged[k], k
        assert loaded["quota_max_tasks"] == 5  # noqa: PLR2004 -- str→int 收编
        for name in ("settings.json", "connections.json"):
            mode = stat.S_IMODE((tmp_path / name).stat().st_mode)
            assert mode == stat.S_IRUSR | stat.S_IWUSR, name

    def test_key_hygiene(self, tmp_path: Path) -> None:
        """``public()`` 永不携带 api_key；空串不覆盖；clear 显式清且压过同帧。"""
        store = _store_with(tmp_path, {"api_key": {"weird": "type"}})
        pub = store.public()
        assert "api_key" not in pub
        assert pub["has_api_key"] is True
        assert (
            settings.SettingsStore(tmp_path / "fresh").public()["has_api_key"] is False
        )
        store2 = settings.SettingsStore(tmp_path / "s2")
        store2.save({"api_key": "sk-keep-1111"})
        merged = store2.save({"api_key": "", "model": "m2"})
        assert merged["api_key"] == "sk-keep-1111"  # 空串不覆盖
        merged = store2.save({"api_key": "sk-new-9999", "clear_api_key": True})
        assert merged["api_key"] == ""  # clear 压过同帧新 key
        raw = json.loads(
            (tmp_path / "s2" / "settings.json").read_text(encoding="utf-8")
        )
        assert "has_api_key" not in raw
        assert "clear_api_key" not in raw

    def test_connection_slot_recall(self, tmp_path: Path) -> None:
        """A→B→A 切换：B 存 key-b、回 A 召回 key-a（texglot 分槽语义）。"""
        store = settings.SettingsStore(tmp_path)
        a, b = "http://localhost:1", "https://api.deepseek.com"
        store.save({"base_url": a, "api_key": "key-a"})
        store.save({"base_url": b, "api_key": "key-b"})
        merged = store.save({"base_url": a})  # 不带 key → 召回 A 槽
        assert merged["api_key"] == "key-a"
        merged = store.save({"base_url": b})
        assert merged["api_key"] == "key-b"
        conns = store.connections()
        assert conns[a]["api_key"] == "key-a"
        assert conns[b]["api_key"] == "key-b"

    def test_unknown_keys_and_connections_filter(self, tmp_path: Path) -> None:
        """未知键 ``save`` 写时即滤（FIELDS 白名单闸直调面）；手改件注入
        未知键 ``load`` 仍滤。"""
        store = settings.SettingsStore(tmp_path)
        store.save({"totally_unknown": {"x": 1}})
        raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert "totally_unknown" not in raw
        raw["totally_unknown"] = {"x": 1}
        (tmp_path / "settings.json").write_text(json.dumps(raw), encoding="utf-8")
        assert "totally_unknown" not in store.load()
        (tmp_path / "connections.json").write_text(
            json.dumps({"a": {"api_key": "k"}, "b": 5, "c": "s", "d": None}),
            encoding="utf-8",
        )
        assert store.connections() == {"a": {"api_key": "k"}}

    def test_connections_nonstr_fields_sanitized(self, tmp_path: Path) -> None:
        """槽位字段非 str（手改 connections.json）→ ``_load_str`` 口径归一
        为 str——不携 dict/int 进 httpx 头构造面。"""
        store = settings.SettingsStore(tmp_path)
        (tmp_path / "connections.json").write_text(
            json.dumps(
                {"http://x": {"api_key": {"nested": 1}, "model": 42, "extra": None}}
            ),
            encoding="utf-8",
        )
        conns = store.connections()
        assert conns["http://x"]["model"] == "42"
        assert all(isinstance(v, str) for v in conns["http://x"].values())

    def test_concurrent_saves_never_torn(self, tmp_path: Path) -> None:
        """并发 ``save``：文件永远是一份合法 JSON（tmp+rename 原子写）。"""
        store = settings.SettingsStore(tmp_path)
        path = tmp_path / "settings.json"
        errors: list[BaseException] = []

        def writer(i: int) -> None:
            try:
                for j in range(_SAVE_ITERS):
                    store.save({"model": f"m-{i}-{j}", "concurrency": (j % 5) + 1})
            except BaseException as e:  # noqa: BLE001 -- 汇总线程异常断言
                errors.append(e)

        def reader() -> None:
            for _ in range(_SAVE_ITERS * _SAVE_THREADS):
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    assert isinstance(data, dict)
                loaded = store.load()
                assert isinstance(loaded["concurrency"], int)

        threads = [
            threading.Thread(target=writer, args=(i,)) for i in range(_SAVE_THREADS)
        ]
        threads.append(threading.Thread(target=reader))
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert not errors
        assert store.load()["model"].startswith("m-")

    def test_save_concurrency_clamps(self, tmp_path: Path) -> None:
        store = settings.SettingsStore(tmp_path)
        for raw, expected in ((99, 16), (-3, 1), ("8", 8), (2.9, 2)):
            assert store.save({"concurrency": raw})["concurrency"] == expected, raw

    def test_wrong_type_escapes(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """错型/inf 输入 → 期望 ``ValueError``/400，而非裸 TypeError/500。"""
        store = settings.SettingsStore(tmp_path)
        for value in (None, [3], {"x": 1}, float("inf"), float("-inf")):
            with pytest.raises(ValueError, match=r"."):
                store.save({"concurrency": value})
        from starlette.testclient import TestClient  # noqa: PLC0415

        with TestClient(make_app(tmp_path / "app"), raise_server_exceptions=False) as c:
            for body in ({"concurrency": None}, {"concurrency": [3]}):
                r = c.put("/api/settings", json=body)
                assert r.status_code == HTTPStatus.BAD_REQUEST, body
            # httpx ``json=`` 拒编码 inf（allow_nan=False）——``1e999`` 只能
            # 以原始字节送达，服务端 ``json.loads`` 解析出 inf 才是
            # ``_check_quota`` 的 OverflowError 触发面
            r = c.put(
                "/api/settings",
                content=b'{"quota_max_tasks": 1e999}',
                headers={"content-type": "application/json"},
            )
            assert r.status_code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------- resolve_auth


class TestResolveAuth:
    """``resolve_auth`` 三级回落矩阵 + 租户指纹。"""

    _SETTINGS: ClassVar[dict[str, str]] = {
        "base_url": "http://localhost:3003",
        "model": "m-settings",
        "api_key": "sk-settings-1",
    }

    def test_fallback_order(self, clean_env: pytest.MonkeyPatch) -> None:
        """``header > settings > env`` 逐项回落。"""
        ctx = settings.resolve_auth(
            self._SETTINGS,
            header_key="sk-header-9",
            header_base_url="http://localhost:4000",
            header_model="m-header",
            salt="s",
        )
        assert (ctx.api_key, ctx.source) == ("sk-header-9", "header")
        assert ctx.base_url == "http://localhost:4000"
        assert ctx.model == "m-header"
        ctx = settings.resolve_auth(self._SETTINGS, salt="s")
        assert (ctx.api_key, ctx.source) == ("sk-settings-1", "settings")
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        bare = {"base_url": "", "model": "", "api_key": ""}
        ctx = settings.resolve_auth(bare, salt="s")
        assert (ctx.api_key, ctx.source) == ("sk-env-7", "env")

    def test_server_key_isolation(self, clean_env: pytest.MonkeyPatch) -> None:
        """server 形态无 header key → 匿名桶：settings/env 凭据一律不外借。"""
        clean_env.setenv("TEXLATE_API_KEY", "sk-env-7")
        ctx = settings.resolve_auth(self._SETTINGS, mode="server", salt="s")
        assert ctx.api_key == ""
        assert ctx.source == "none"
        assert ctx.tenant.startswith("k_")  # 匿名桶指纹而非 local
        ctx = settings.resolve_auth(
            self._SETTINGS, header_key="sk-h", mode="server", salt="s"
        )
        assert ctx.source == "header"
        expected = "k_" + __import__("hashlib").sha256(b"sk-hs").hexdigest()[:12]
        assert ctx.tenant == expected

    def test_bad_header_matrix(self, clean_env: pytest.MonkeyPatch) -> None:
        del clean_env
        for kw, match in (
            ({"header_base_url": "ftp://x"}, "invalid base_url"),
            ({"header_base_url": "http://evil.com"}, "HTTPS"),
            ({"header_model": "a\nb"}, "invalid model"),
        ):
            with pytest.raises(ValueError, match=match):
                settings.resolve_auth(self._SETTINGS, **kw)  # type: ignore[arg-type]
        ctx = settings.resolve_auth(self._SETTINGS, header_model="")
        assert ctx.model == "m-settings"  # 空 header_model 不校验走回落

    def test_tenant_invariants(self) -> None:
        """local 恒 ``local``；server 指纹确定性 + salt 敏感。"""
        assert settings.tenant_for("k", mode="local", salt="s") == "local"
        assert settings.tenant_for("anything", mode="x", salt="s") == "local"
        t1 = settings.tenant_for("k", mode="server", salt="s1")
        assert t1 == settings.tenant_for("k", mode="server", salt="s1")
        assert t1 != settings.tenant_for("k", mode="server", salt="s2")
        assert t1 != settings.tenant_for("k2", mode="server", salt="s1")
        assert t1.startswith("k_")
        assert len(t1) == 14  # noqa: PLR2004 -- k_ + sha256[:12]


# ---------------------------------------------------------------- env 辅助面


class TestEnvHelpers:
    """env 读取面矩阵。"""

    def test_cache_scope_matrix(self, clean_env: pytest.MonkeyPatch) -> None:
        for value, expected in (
            ("shared", "shared"),
            ("per_key", "per_key"),
            ("tenant", "per_key"),  # 旧名同义
            ("PER_KEY", "per_key"),
            ("  per_key  ", "per_key"),
            ("junk", "shared"),  # 非法回落
            ("", "shared"),
            ("sharedx", "shared"),
        ):
            clean_env.setenv("TEXLATE_CACHE_SCOPE", value)
            assert settings.cache_scope() == expected, value

    def test_env_key_and_env_overrides(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("DEEPSEEK_API_KEY", "sk-ds")
        clean_env.setenv("TEXLATE_API_KEY", "sk-tx")
        assert settings.env_key_for("https://api.deepseek.com") == "sk-tx"
        clean_env.delenv("TEXLATE_API_KEY")
        assert settings.env_key_for("https://api.deepseek.com") == "sk-ds"
        assert settings.env_key_for("https://unknown.example") == ""
        clean_env.setenv("TEXLATE_BASE_URL", "  http://x  ")
        clean_env.setenv("TEXLATE_MODEL", "  m  ")
        assert settings.env_base_url() == "http://x"
        assert settings.env_model() == "m"

    def test_data_and_share_dirs(
        self, tmp_path: Path, clean_env: pytest.MonkeyPatch
    ) -> None:
        clean_env.setenv("TEXLATE_DATA_DIR", str(tmp_path / "dd"))
        got = settings.data_dir()
        assert got == tmp_path / "dd"
        assert stat.S_IMODE(got.stat().st_mode) == 0o700  # noqa: PLR2004
        assert settings.share_dir() == tmp_path / "dd" / "share"
        clean_env.setenv("TEXLATE_SHARE_DIR", str(tmp_path / "ext"))
        assert settings.share_dir() == tmp_path / "ext"
        clean_env.setenv("TEXLATE_SHARE_DIR", "   ")
        assert settings.share_dir() == tmp_path / "dd" / "share"

    def test_provider_presets(self, clean_env: pytest.MonkeyPatch) -> None:
        presets = settings.provider_presets({"base_url": "https://api.deepseek.com"})
        assert len(presets) == 6  # noqa: PLR2004
        assert [p["id"] for p in presets if p["active"]] == ["deepseek"]
        assert all("has_env_key" in p for p in presets)
        clean_env.setenv("OPENAI_API_KEY", "sk-x")
        presets = settings.provider_presets({"base_url": "https://api.openai.com"})
        openai = next(p for p in presets if p["id"] == "openai")
        assert openai["active"] is True
        assert openai["has_env_key"] is True


# ---------------------------------------------------------------- server_salt


class TestServerSalt:
    """``server_salt`` 生成/持久化/边界。"""

    def test_salt_lifecycle(self, tmp_path: Path) -> None:
        salt = settings.server_salt(tmp_path)
        assert len(salt) == 32  # noqa: PLR2004 -- token_hex(16)
        assert settings.server_salt(tmp_path) == salt  # 二次同值
        mode = stat.S_IMODE((tmp_path / "server_salt").stat().st_mode)
        assert mode == stat.S_IRUSR | stat.S_IWUSR
        (tmp_path / "server_salt").write_text("   \n ", encoding="utf-8")
        assert len(settings.server_salt(tmp_path)) == 32  # noqa: PLR2004 -- 空白重生成
        (tmp_path / "server_salt").write_text("  mysalt \n", encoding="utf-8")
        assert settings.server_salt(tmp_path) == "mysalt"  # 已有内容原样读

    def test_concurrent_first_call_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """两线程同时首调用 → 返回值与落盘值必须一致（确定性交错重现）。"""
        entered = threading.Event()
        release = threading.Event()
        results: dict[str, str] = {}
        real_hex = secrets.token_hex

        def slow_hex(n: int) -> str:
            entered.set()
            release.wait(5)
            return "a" * (n * 2)

        def call_a() -> None:
            results["a"] = settings.server_salt(tmp_path)

        monkeypatch.setattr(secrets, "token_hex", slow_hex)
        t = threading.Thread(target=call_a)
        t.start()
        assert entered.wait(5)
        monkeypatch.setattr(secrets, "token_hex", real_hex)
        results["b"] = settings.server_salt(tmp_path)
        release.set()
        t.join(5)
        final = (tmp_path / "server_salt").read_text(encoding="utf-8")
        assert results["a"] == results["b"] == final


# ---------------------------------------------------------------- 日志脱敏


class TestLogScrub:
    """``scrub``/``RedactFilter``/``install_log_scrub`` 脱敏面。"""

    def test_scrub_patterns_and_idempotent(self) -> None:
        out = settings.scrub(
            "h=Bearer tok-1 k=sk-abc12345 g=AIza1234567890 api_key=secret:v",
            "tok-1",
        )
        for needle in ("tok-1", "sk-abc12345", "AIza1234567890", "secret:v"):
            assert needle not in out, needle
        assert settings.scrub(out, "tok-1") == out  # 幂等
        assert settings.scrub("plain text", "") == "plain text"  # 空 key 不动

    def _capture(self, filt: logging.Filter) -> tuple[logging.Logger, io.StringIO]:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(filt)
        lg = logging.getLogger("sidecar_fuzz.scrub")
        lg.handlers = [handler]
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        return lg, stream

    def test_filter_record_handling(self) -> None:
        """命中：msg 改写 + args 清空；未命中：原样；非 str msg：放行。"""
        lg, stream = self._capture(settings.RedactFilter(lambda: ["sk-zzz-1"]))
        lg.warning("token=%s tail", "sk-zzz-1")
        out = stream.getvalue()
        assert "sk-zzz-1" not in out
        # `token[=:]\S+` 正则整段吞掉 ``token=sk-zzz-1``——key 与载体一起抹
        assert "*** tail" in out
        filt = settings.RedactFilter(lambda: ["k"])
        rec = logging.LogRecord("n", logging.INFO, "p", 1, "v=%s", ("x",), None)
        assert filt.filter(rec) is True
        assert rec.msg == "v=%s"
        assert rec.args == ("x",)  # 未命中原样
        rec2 = logging.LogRecord("n", logging.INFO, "p", 1, 42, None, None)
        assert filt.filter(rec2) is True  # 非 str msg 不炸

    def test_filter_provider_raise_never_breaks(self) -> None:
        def boom() -> list[str]:
            msg = "provider down"
            raise RuntimeError(msg)

        lg, _stream = self._capture(settings.RedactFilter(boom))
        lg.warning("still logged %s", "v")  # provider 炸 → 不过滤不炸日志

    def test_install_idempotent(self) -> None:
        settings.install_log_scrub(lambda: ["k1"])
        settings.install_log_scrub(lambda: ["k2"])
        for name in ("texlate", "uvicorn.error"):
            lg = logging.getLogger(name)
            n = sum(isinstance(f, settings.RedactFilter) for f in lg.filters)
            assert n == 1, name

    def test_exc_info_leaks_key(self) -> None:
        """exc_info 里的 key 必须被抹掉（当前原样穿透）。"""
        lg, stream = self._capture(settings.RedactFilter(lambda: ["sk-exc-77"]))
        try:
            msg = "bad key sk-exc-77 inside exc"
            raise ValueError(msg)  # noqa: TRY301 -- 就地构造 exc_info 现场
        except ValueError:
            lg.exception("operation failed")
        assert "sk-exc-77" not in stream.getvalue()


# ---------------------------------------------------------------- _Feed


class TestFeed:
    """``_Feed`` 字节流 → 进度/统计/错误的归类不变量。"""

    def test_random_bytes_and_bounds(self) -> None:
        rng = fuzz_rng(7)
        feed = bd._Feed()  # noqa: SLF001
        for _ in range(_FEED_CHUNKS):
            feed.feed(
                bytes(rng.randrange(256) for _ in range(rng.randrange(_FEED_BYTES)))
            )
        feed.flush()
        assert len(feed.errors) <= bd._MAX_ERRORS  # noqa: SLF001
        feed2 = bd._Feed()  # noqa: SLF001
        for i in range(120):
            feed2.feed(f"log line {i}\n".encode())
        feed2.flush()
        assert len(feed2._tail) == 40  # noqa: SLF001, PLR2004 -- 尾窗恒 40

    def test_frames_and_ansi(self) -> None:
        """``\\r``/``\\n``/``\\r\\n`` 与跨 feed 切分归一到同一帧序；ANSI 剥除。"""
        for blob in (
            b"line one\nline two\n",
            b"line one\rline two\r",
            b"line one\r\nline two\r\n",
        ):
            logs: list[str] = []
            feed = bd._Feed(on_log=logs.append)  # noqa: SLF001
            feed.feed(blob)
            feed.flush()
            assert logs == ["line one", "line two"], blob
        logs2: list[str] = []
        feed2 = bd._Feed(on_log=logs2.append)  # noqa: SLF001
        for half in (b"line o", b"ne\nli", b"ne two\n"):
            feed2.feed(half)
        feed2.flush()
        assert logs2 == ["line one", "line two"]
        logs3: list[str] = []
        feed3 = bd._Feed(on_log=logs3.append)  # noqa: SLF001
        feed3.feed(b"\x1b[32mgreen text\x1b[0m\n")
        feed3.flush()
        assert logs3 == ["green text"]

    def test_stats_and_completed(self) -> None:
        feed = bd._Feed()  # noqa: SLF001
        feed.feed(
            b"Total tokens: 42\n"
            b"Prompt tokens: 30\n"
            b"Completion tokens: 12\n"
            b"Cache hit prompt tokens: 5\n"
            b"Peak memory usage: 123.4 MB\n"
            b"Translation completed. Total: 9, Successful: 7, Fallback: 2\n"
        )
        feed.flush()
        s = feed.stats
        assert s["total_tokens"] == 42  # noqa: PLR2004
        assert s["peak_memory_mb"] == pytest.approx(123.4)
        assert s["translate_total"] == 9  # noqa: PLR2004
        assert s["translate_fallback"] == 2  # noqa: PLR2004

    def test_progress_semantics(self) -> None:
        """同 pct 单发、stage 跟行、进度帧不进 on_log、tqdm 兜底。"""
        progs: list[tuple[float, str]] = []
        logs: list[str] = []
        feed = bd._Feed(  # noqa: SLF001
            on_progress=lambda p, s: progs.append((p, s)), on_log=logs.append
        )
        feed.feed(b"Parse PDF (1/5) 10/10\n")
        feed.feed(b"translate 40/100\n")
        feed.feed(b"translate 40/100\n")  # 同 pct 不重发
        feed.feed(b"translate 100/100\n")
        feed.feed(b"real log\n")
        feed.flush()
        assert feed.stage == "Parse PDF"
        assert progs == [(40.0, "Parse PDF"), (100.0, "Parse PDF")]
        assert "real log" in logs
        assert not any("40/100" in ln for ln in logs)
        progs2: list[float] = []
        feed2 = bd._Feed(on_progress=lambda p, _s: progs2.append(p))  # noqa: SLF001
        feed2.feed(b"37%|### | stuff\n")
        feed2.flush()
        assert progs2 == [37.0]

    def test_error_dedup_and_trunc(self) -> None:
        feed = bd._Feed()  # noqa: SLF001
        feed.feed(b"Error: same\nError: same\n")
        feed.feed(("translate error: " + "x" * 500 + "\n").encode())
        feed.flush()
        errs = list(feed.errors)
        assert errs.count("same") == 1
        assert all(len(e) <= 300 for e in errs)  # noqa: PLR2004

    def test_stage_regex_keeps_logs(self) -> None:
        """``text (n/m)`` 日志行应进 ``on_log``（stage 判定须见进度证据）。"""
        for line in (
            "Error in part (3/5): kaboom",
            "Retrying batch (2/10) after rate limit",
            "Downloading font (7/12) subset",
        ):
            logs: list[str] = []
            feed = bd._Feed(on_log=logs.append)  # noqa: SLF001
            feed.feed(line.encode() + b"\n")
            feed.flush()
            assert line in logs, line


# ---------------------------------------------------------------- tracking


class TestTracking:
    """``assess_tracking`` 结构容错矩阵。"""

    def _put(self, workdir: Path, stem: str, payload: object, sub: str = "") -> Path:
        d = workdir / stem / sub
        d.mkdir(parents=True, exist_ok=True)
        p = d / "translate_tracking.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_counts_and_part_fallback(self, tmp_path: Path) -> None:
        tracker = {
            "has_error": True,
            "error_message": "e",
            "fallback_to_translate": True,
        }
        self._put(
            tmp_path,
            "doc",
            {
                "page": [{"paragraph": [{"llm_translate_trackers": [tracker]}]}],
                "cross_page": [{"paragraph": [{"llm_translate_trackers": [{}]}]}],
                "cross_column": [
                    {"paragraph": [{"llm_translate_trackers": [tracker]}]}
                ],
            },
        )
        res = bd.assess_tracking(tmp_path, "doc")
        assert (res["total"], res["errors"], res["fallbacks"]) == (3, 2, 2)
        assert res["tracking_found"] is True
        p = self._put(
            tmp_path,
            "part",
            {"page": [{"paragraph": [{"llm_translate_trackers": [{}]}]}]},
            sub="part_3",
        )
        res = bd.assess_tracking(tmp_path, "part")
        assert res["tracking_found"] is True
        assert res["total"] == 1
        assert bd.tracking_paths(tmp_path, "part") == [p]

    def test_malformed_tolerated(self, tmp_path: Path) -> None:
        for i, content in enumerate(
            (
                '{"page": [{"par',  # 截断 JSON
                "",  # 空文件
                "[1,2,3]",  # 非 dict 顶层
                '"str"',
            )
        ):
            d = tmp_path / f"doc{i}"
            d.mkdir()
            (d / "translate_tracking.json").write_text(content, encoding="utf-8")
            res = bd.assess_tracking(tmp_path, f"doc{i}")
            assert res["total"] == 0, content
            assert res["tracking_found"] is True  # 文件在、读不进 = found-but-zero

    def test_inner_nondict_tolerated(self, tmp_path: Path) -> None:
        """内层错型 → 零计数容错（逐层 ``isinstance`` 闸）。"""
        for i, payload in enumerate(
            (
                {"page": "x"},
                {"page": [1]},
                {"page": [{"paragraph": "x"}]},
                {"page": [{"paragraph": [None]}]},
                {"page": [{"paragraph": [{"llm_translate_trackers": ["nope"]}]}]},
                {"page": [{"paragraph": [{"llm_translate_trackers": [None]}]}]},
                {"page": [{"paragraph": [{"llm_translate_trackers": [123]}]}]},
            )
        ):
            self._put(tmp_path, f"d{i}", payload)
            res = bd.assess_tracking(tmp_path, f"d{i}")
            assert isinstance(res["total"], int), payload


# ---------------------------------------------------------------- judge/classify


class TestJudgeAndClassify:
    """``_judge_run`` 判定矩阵 + ``_classify_rc`` 优先级。"""

    class _F:
        def __init__(self, **kw: object) -> None:
            self.scanned = bool(kw.get("scanned"))
            self.stats = kw.get("stats", {})
            self.tail = str(kw.get("tail", ""))
            self.errors = list(kw.get("errors", ()))  # type: ignore[arg-type]

    def test_judge_matrix_invariants(self, tmp_path: Path) -> None:
        """rc×timeout×scanned×outputs×track 全组合 → 判定四元组形态合法。"""
        job = _job(tmp_path, "a")
        tracks = (
            {
                "total": 0,
                "errors": 0,
                "fallbacks": 0,
                "error_samples": [],
                "tracking_found": False,
            },
            {
                "total": 10,
                "errors": 6,
                "fallbacks": 0,
                "error_samples": ["e"],
                "tracking_found": True,
            },
            {
                "total": 10,
                "errors": 2,
                "fallbacks": 3,
                "error_samples": [],
                "tracking_found": True,
            },
        )
        for rc in (-1, 0, 1, 2, 137):
            for to in (False, True):
                for sc in (False, True):
                    for outs in (
                        {},
                        {"mono": tmp_path / "no.pdf"},
                        {"dual": tmp_path / "d.pdf"},
                    ):
                        for tr in tracks:
                            feed = self._F(scanned=sc, stats={"total_tokens": 5})
                            status, code, _err, retryable = bd._judge_run(  # noqa: SLF001
                                job,
                                rc=rc,
                                timed_out=to,
                                feed=feed,  # type: ignore[arg-type]
                                outputs=outs,
                                track=tr,
                                stats={},
                            )
                            assert status in ("ok", "degraded", "failed")
                            if status == "failed":
                                assert code
                            else:
                                assert code is None
                            if not retryable:
                                assert code == "scanned_pdf"

    def test_classify(self) -> None:
        """auth > rate > compile；空 feed 兜默认消息。"""
        feed = bd._Feed()  # noqa: SLF001
        feed.feed(b"RateLimitError 429\nAuthenticationError bad\n")
        feed.flush()
        assert bd._classify_rc(feed) == (  # noqa: SLF001
            "provider_auth",
            "AuthenticationError bad",
            False,
        )
        code, msg, retryable = bd._classify_rc(bd._Feed())  # noqa: SLF001
        assert (code, retryable) == ("compile", True)
        assert msg


# ---------------------------------------------------------------- harvest/config


class TestHarvestAndConfig:
    """``harvest_outputs``/``write_config``/``build_argv``/glossary/cjk."""

    def test_harvest_glob_semantics(self, tmp_path: Path) -> None:
        """glob 元字符 stem 字面命中不误配；``.no_watermark.`` 优先。"""
        out = tmp_path / "out"
        out.mkdir()
        for stem in ("a[1]", "a*b", "a?c", "a b", "normal", "x-y_1"):
            for kind in ("mono", "dual"):
                (out / f"{stem}.no_watermark.zh-CN.{kind}.pdf").write_bytes(b"x")
            (out / f"{stem}.zh-CN.glossary.csv").write_bytes(b"x")
            got = bd.harvest_outputs(_job(tmp_path, stem))
            assert sorted(got) == ["dual", "glossary_csv", "mono"], stem
        # stem ``a?`` 不得误配字面文件 ``aX``（``glob_escape`` 字面化）
        for p in out.iterdir():
            p.unlink()
        (out / "aX.no_watermark.zh-CN.mono.pdf").write_bytes(b"x")
        assert bd.harvest_outputs(_job(tmp_path, "a?")) == {}
        (out / "n.zh-CN.mono.pdf").write_bytes(b"plain")
        (out / "n.no_watermark.zh-CN.mono.pdf").write_bytes(b"nw")
        got = bd.harvest_outputs(_job(tmp_path, "n"))
        assert ".no_watermark." in got["mono"].name
        assert bd.harvest_outputs(_job(tmp_path / "ghost", "ghost")) == {}

    def test_write_config_toml_round_trip(self, tmp_path: Path) -> None:
        """敌对 key（引号/换行/空格）经 ``json.dumps`` 转义后 TOML 可读回。"""
        for i, key in enumerate(
            ("sk-live_key.123", 'evil"]\n[hacked', "with space", "中-key", "")
        ):
            job = _job(tmp_path / f"j{i}", "a", api_key=key)
            p = bd.write_config(job)
            mode = stat.S_IMODE(p.stat().st_mode)
            assert mode == stat.S_IRUSR | stat.S_IWUSR, key
            got = tomllib.loads(p.read_text(encoding="utf-8"))
            assert got["babeldoc"]["openai-api-key"] == (key or "texlate"), key

    def test_nonbmp_key_toml_round_trip(self, tmp_path: Path) -> None:
        job = _job(tmp_path, "a", api_key="k-\U0001f600-\U0001f4a5")
        p = bd.write_config(job)
        got = tomllib.loads(p.read_text(encoding="utf-8"))
        assert got["babeldoc"]["openai-api-key"] == "k-\U0001f600-\U0001f4a5"

    def test_api_key_never_in_argv(self, tmp_path: Path) -> None:
        """api_key 只走 ``-c`` 的 toml 配置——argv 永不带 key 旗标。"""
        for i, key in enumerate(
            (
                "sk-normal",
                "--output",
                "--openai-api-key",
                "/etc/passwd",
                "key with\nnewline",
                "\U0001f4a5",
            )
        ):
            job = _job(tmp_path / f"j{i}", "a", api_key=key)
            argv = bd.build_argv(job, "/bin/babeldoc")
            assert "--openai-api-key" not in argv, key
            assert "--max-pages-per-part" not in argv

    def test_glossary_csv_round_trip(self, tmp_path: Path) -> None:
        import csv  # noqa: PLC0415 -- 校验面聚一处

        assert bd.write_glossary_csv(tmp_path / "g.csv", []) is None
        p = tmp_path / "g.csv"
        bd.write_glossary_csv(p, [('a"b', "x\ny"), ("nul\x00t", "z"), ("", "")])
        assert p.read_bytes().startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["source", "target", "tgt_lng"]
        assert rows[1:] == [['a"b', "x\ny", ""], ["nul\x00t", "z", ""], ["", "", ""]]

    def test_cjk_ratio_and_timeout(
        self, tmp_path: Path, clean_env: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "junk.pdf").write_bytes(bytes(range(256)) * 4)
        (tmp_path / "empty.pdf").write_bytes(b"")
        assert bd.cjk_ratio(tmp_path / "junk.pdf") is None
        assert bd.cjk_ratio(tmp_path / "empty.pdf") is None
        assert bd.cjk_ratio(tmp_path / "ghost.pdf") is None
        for env, expected in (
            (None, bd.DEFAULT_TIMEOUT_S),
            ("30", 30.0),
            ("junk", bd.DEFAULT_TIMEOUT_S),
            ("-5", bd.DEFAULT_TIMEOUT_S),
            ("0", bd.DEFAULT_TIMEOUT_S),
            ("nan", bd.DEFAULT_TIMEOUT_S),
        ):
            if env is not None:
                clean_env.setenv("TEXLATE_BABELDOC_TIMEOUT", env)
            assert bd.default_timeout() == expected, env
            clean_env.delenv("TEXLATE_BABELDOC_TIMEOUT", raising=False)


# ---------------------------------------------------------------- SPA


class TestSpa:
    """``spa_dir``/``mount_spa`` 路径与缓存策略不变量。"""

    @pytest.fixture
    def spa_root(self, tmp_path: Path) -> Path:
        spa = tmp_path / "spa"
        (spa / "assets" / "deep").mkdir(parents=True)
        (spa / "pdfjs").mkdir()
        (spa / "sub").mkdir()
        (spa / "index.html").write_text("<html>root</html>", encoding="utf-8")
        (spa / "sub" / "index.html").write_text("<html>sub</html>", encoding="utf-8")
        (spa / "assets" / "app-A1B2.js").write_text("x=1", encoding="utf-8")
        (spa / "assets" / "deep" / "w-B2.woff2").write_bytes(b"\0")
        (spa / "pdfjs" / "x.bcmap").write_bytes(b"\0")
        (spa / "favicon.ico").write_bytes(b"\0")
        return spa

    @pytest.fixture
    def spa_client(
        self, spa_root: Path, clean_env: pytest.MonkeyPatch
    ) -> Iterator[TestClient]:
        from fastapi import FastAPI  # noqa: PLC0415
        from starlette.testclient import TestClient  # noqa: PLC0415

        from texlate.server.staticfiles import mount_spa  # noqa: PLC0415

        clean_env.setenv("TEXLATE_SPA_DIR", str(spa_root))
        app = FastAPI()
        assert mount_spa(app) is True
        with TestClient(app) as c:
            yield c

    def test_spa_dir_and_mount_gates(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from fastapi import FastAPI  # noqa: PLC0415

        import texlate.server.staticfiles as sf  # noqa: PLC0415

        empty = tmp_path / "empty"
        empty.mkdir()
        clean_env.setenv("TEXLATE_SPA_DIR", str(empty))
        got = sf.spa_dir()
        assert got != empty  # 无 index.html → 回落（包内或 None）
        assert got is None or (got / "index.html").is_file()
        (empty / "index.html").write_text("x", encoding="utf-8")
        assert sf.spa_dir() == empty
        monkeypatch.setattr(sf, "spa_dir", lambda: None)
        assert sf.mount_spa(FastAPI()) is False

    def test_cache_matrix(self, spa_client: TestClient) -> None:
        for path, expected in (
            ("/", "no-cache"),
            ("/index.html", "no-cache"),
            ("/sub/", "no-cache"),  # 子目录 index 同策
            ("/sub/index.html", "no-cache"),
            ("/assets/app-A1B2.js", "public, max-age=31536000, immutable"),
            ("/assets/deep/w-B2.woff2", "public, max-age=31536000, immutable"),
        ):
            r = spa_client.get(path)
            assert r.status_code == HTTPStatus.OK, path
            assert r.headers["Cache-Control"] == expected, path

    def test_stable_names_and_traversal(self, spa_client: TestClient) -> None:
        """稳定名资源不贴 ``Cache-Control``；穿越形请求全 4xx。"""
        for path in ("/pdfjs/x.bcmap", "/favicon.ico"):
            r = spa_client.get(path)
            assert r.status_code == HTTPStatus.OK, path
            assert "Cache-Control" not in r.headers, path
        for path in (
            "/../../pyproject.toml",
            "/%2e%2e/pyproject.toml",
            "/assets/../../settings.json",
            "/....//pyproject.toml",
        ):
            r = spa_client.get(path)
            assert r.status_code in (HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND), path

    def test_symlinked_spa_dir_headers(
        self, tmp_path: Path, spa_root: Path, clean_env: pytest.MonkeyPatch
    ) -> None:
        """``TEXLATE_SPA_DIR`` 经软链指向产物：realpath 基准下缓存头仍对。"""
        from fastapi import FastAPI  # noqa: PLC0415
        from starlette.testclient import TestClient  # noqa: PLC0415

        from texlate.server.staticfiles import mount_spa  # noqa: PLC0415

        link = tmp_path / "spa_link"
        link.symlink_to(spa_root)
        clean_env.setenv("TEXLATE_SPA_DIR", str(link))
        app = FastAPI()
        assert mount_spa(app) is True
        with TestClient(app) as c:
            r = c.get("/assets/app-A1B2.js")
            assert "immutable" in r.headers.get("Cache-Control", "")
            r2 = c.get("/")
            assert r2.headers["Cache-Control"] == "no-cache"


# ---------------------------------------------------------------- __main__


class TestMainEntry:
    """``__main__._port`` 闸 + ``main`` 参数透传。"""

    def test_port_matrix(self) -> None:
        import texlate.server.__main__ as m  # noqa: PLC0415

        for raw, expected in (
            ("1", 1),
            ("80", 80),
            ("65535", 65535),
            (" 80 ", 80),  # int() 空白容忍
            ("+80", 80),
            ("8_0", 80),  # int() 下划线分隔符
            ("８０", 80),  # 全角数字 int() 照收
        ):
            assert m._port(raw) == expected, raw  # noqa: SLF001
        for raw in ("0", "65536", "-1", "8.0", "", "abc", "0x50", "1e5", " "):
            with pytest.raises(argparse.ArgumentTypeError, match=r"."):
                m._port(raw)  # noqa: SLF001
        # 任意字符串：ArgumentTypeError 或 1-65535 内 int
        rng = fuzz_rng(3)
        alphabet = "0123456789+-. _ex８９"
        for _ in range(200):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randrange(8)))
            try:
                p = m._port(s)  # noqa: SLF001
            except argparse.ArgumentTypeError:
                continue
            assert 1 <= p <= 65535, s  # noqa: PLR2004

    def test_main_unknown_arg_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys  # noqa: PLC0415

        import texlate.server.__main__ as m  # noqa: PLC0415

        monkeypatch.setattr(sys, "argv", ["texlate.server", "--bogus"])
        with pytest.raises(SystemExit) as ei:
            m.main()
        assert ei.value.code == 2  # noqa: PLR2004 -- argparse usage 退出码


# ---------------------------------------------------------------- cmap 资源


class TestCmapResource:
    """``compile/cmaps/Adobe-GB1-UCS2`` 注入共享资源的完整性闸。"""

    def test_resource_wellformed(self, tmp_path: Path) -> None:
        from pypdf import PdfWriter  # noqa: PLC0415

        from texlate.compile import cjkmap  # noqa: PLC0415
        from texlate.compile.cjkmap import embed_cjk_mappings  # noqa: PLC0415

        path = cjkmap._GB1_UCS2_CMAP  # noqa: SLF001
        assert path.is_file()
        blob = path.read_bytes()
        assert blob.startswith(b"%!PS-Adobe-3.0 Resource-CMap")
        assert b"%%BeginResource: CMap (Adobe-GB1-UCS2)" in blob
        assert b"begincmap" in blob
        assert b"endcmap" in blob
        assert b"beginbfchar" in blob or b"beginbfrange" in blob
        assert len(blob) > 200_000  # noqa: PLR2004 -- ~221KB 全量 GB1 映射
        # 无 CID 字体的 PDF → 0 处注入（不瞎挂 cmap）
        w = PdfWriter()
        w.add_blank_page(width=100, height=100)
        pdf = tmp_path / "blank.pdf"
        with pdf.open("wb") as fh:
            w.write(fh)
        w.close()
        assert embed_cjk_mappings(pdf) == 0
