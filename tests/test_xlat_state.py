"""state：原子落盘 / state.json schema / 续跑 round-trip / 缓存键与隔离。"""

import json
import logging
import stat
from pathlib import Path

import pytest

from texlate.xlat import state as st

_PRIVATE_MODE = 0o600


class TestAtomicJson:
    def test_mode_600_and_content(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        st.atomic_json(p, {"a": 1})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == _PRIVATE_MODE

    def test_no_leftover_tmp(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        st.atomic_json(p, {"a": 1})
        st.atomic_json(p, {"a": 2})  # 覆盖写也不留 tmp
        leftovers = [f.name for f in tmp_path.iterdir() if ".tmp" in f.name]
        assert leftovers == []

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "x.json"
        st.atomic_json(p, [1])
        assert p.exists()


class TestStateStore:
    def test_schema_and_resume_roundtrip(self, tmp_path: Path) -> None:
        store = st.StateStore(tmp_path, model="m", pipeline_version="v1")
        store.start(2)
        store.record(
            st.ChunkRecord(
                chunk_id="c1",
                source="src1",
                translation="译文1",
                kind="para",
                batched=True,
                batch_id="batch_0000",
                attempts=1,
            )
        )
        store.record(
            st.ChunkRecord(
                chunk_id="c2",
                source="src2",
                translation="src2",
                status="skipped",
                skipped=True,
                skip_reason="boom",
            ),
            error={"error": "boom"},
        )
        store.finish()

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["version"] == st.STATE_VERSION
        assert data["meta"]["model"] == "m"
        assert data["meta"]["total_chunks"] == 2  # noqa: PLR2004 -- schema 断言
        assert data["meta"]["finished_at"]
        assert data["completed"] == ["c1", "c2"]
        assert len(data["results"]) == 2  # noqa: PLR2004 -- schema 断言
        assert data["errors_report"][0]["chunk_id"] == "c2"
        assert (tmp_path / "errors_report.json").exists()

        # 续跑：新实例同目录 → completed/results 回来
        store2 = st.StateStore(tmp_path)
        completed, recs = store2.load()
        assert completed == {"c1", "c2"}
        assert recs["c1"].translation == "译文1"
        assert recs["c1"].batched
        assert recs["c2"].skipped
        assert recs["c2"].skip_reason == "boom"

    def test_corrupt_state_restarts(self, tmp_path: Path) -> None:
        p = tmp_path / "state.json"
        p.write_text("{not json", encoding="utf-8")
        completed, recs = st.StateStore(tmp_path).load()
        assert completed == set()
        assert recs == {}
        # 与 load_cache 同口径：损坏文件改名隔离留诊断现场
        assert not p.exists()
        quarantined = list(tmp_path.glob("state-invalid-*.json"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text(encoding="utf-8") == "{not json"

    def test_version_mismatch_warns_and_proceeds(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """version ≠ STATE_VERSION → warn 记档、按当前格式尽力解析（非损坏不隔离）。"""
        store = st.StateStore(tmp_path)
        store.start(1)
        store.record(st.ChunkRecord(chunk_id="c1", source="s", translation="t"))
        store.finish()
        p = tmp_path / "state.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["version"] = "9.9"
        p.write_text(json.dumps(data), encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="texlate.xlat.state"):
            completed, recs = st.StateStore(tmp_path).load()
        assert completed == {"c1"}
        assert recs["c1"].translation == "t"
        assert p.exists()  # 版本差不隔离
        assert any("9.9" in r.message for r in caplog.records)

    def test_malformed_state_quarantined(self, tmp_path: Path) -> None:
        """JSON 合法但顶层非 dict（手改/串文件）——曾 ``data.get`` 炸 AttributeError。"""
        p = tmp_path / "state.json"
        p.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        completed, recs = st.StateStore(tmp_path).load()
        assert completed == set()
        assert recs == {}
        assert not p.exists()
        assert len(list(tmp_path.glob("state-invalid-*.json"))) == 1

    def test_deep_state_quarantined(self, tmp_path: Path) -> None:
        """超深嵌套 JSON → RecursionError（非 JSONDecodeError）同样走隔离。"""
        p = tmp_path / "state.json"
        p.write_text("[" * 50000 + "]" * 50000, encoding="utf-8")
        completed, recs = st.StateStore(tmp_path).load()
        assert completed == set()
        assert recs == {}
        assert not p.exists()
        assert len(list(tmp_path.glob("state-invalid-*.json"))) == 1

    def test_save_maps(self, tmp_path: Path) -> None:
        store = st.StateStore(tmp_path)
        store.save_maps(
            chunks_map={"c1": "src"},
            placeholders_map={"c1": ["[[MATH_1]]"]},
            term_dict={"attention": "注意力"},
        )
        assert (tmp_path / "chunks_map.json").exists()
        assert (tmp_path / "placeholders_map.json").exists()
        assert (tmp_path / "term_dict.json").exists()

    def test_save_every_batches_flush(self, tmp_path: Path) -> None:
        store = st.StateStore(tmp_path, save_every=2)
        store.start(2)
        store.record(st.ChunkRecord(chunk_id="c1", source="s", translation="t"))
        # 未到 save_every——state.json 里是 start() 时的空 completed
        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["completed"] == []
        store.record(st.ChunkRecord(chunk_id="c2", source="s", translation="t"))
        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["completed"] == ["c1", "c2"]


class TestCache:
    def test_keys_deterministic_and_distinct(self) -> None:
        k1 = st.segment_key("src", "para")
        assert st.segment_key("src", "para") == k1
        assert st.segment_key("src", "caption") != k1
        assert st.segment_key("src2", "para") != k1
        assert st.segment_key("src", "para", invalidation_tags=["accent"]) != k1
        assert st.segment_key("src", "para", masked_snapshot="x") != k1

    def test_file_cache_key_16hex(self) -> None:
        k = st.file_cache_key(prompt_version="v1", base_url="b", model="m", lang="zh")
        assert len(k) == 16  # noqa: PLR2004 -- 键长契约
        assert all(c in "0123456789abcdef" for c in k)
        k2 = st.file_cache_key(prompt_version="v2", base_url="b", model="m", lang="zh")
        assert k2 != k

    def test_cache_roundtrip(self, tmp_path: Path) -> None:
        store = st.StateStore(tmp_path)
        store.save_cache("k", {"seg1": "译1"})
        assert store.load_cache("k") == {"seg1": "译1"}
        assert store.cache_path("k").name == "cache-k.json"

    def test_corrupt_cache_quarantined(self, tmp_path: Path) -> None:
        bad = tmp_path / "cache-x.json"
        bad.write_text("{broken", encoding="utf-8")
        store = st.StateStore(tmp_path)
        assert store.load_cache("x") == {}
        assert not bad.exists()
        quarantined = list(tmp_path.glob("cache-x-invalid-*.json"))
        assert len(quarantined) == 1

    def test_deep_cache_quarantined(self, tmp_path: Path) -> None:
        """超深嵌套 JSON → RecursionError 逃出 except → 曾 load_cache 硬炸。"""
        bad = tmp_path / "cache-x.json"
        bad.write_text("[" * 50000 + "]" * 50000, encoding="utf-8")
        store = st.StateStore(tmp_path)
        assert store.load_cache("x") == {}
        assert not bad.exists()
        assert len(list(tmp_path.glob("cache-x-invalid-*.json"))) == 1

    def test_cache_filters_non_str(self, tmp_path: Path) -> None:
        f = tmp_path / "cache-y.json"
        f.write_text(
            json.dumps({"a": "b", "bad": 1, "also_bad": {"x": 1}}),
            encoding="utf-8",
        )
        store = st.StateStore(tmp_path)
        assert store.load_cache("y") == {"a": "b"}

    def test_cache_missing_returns_empty(self, tmp_path: Path) -> None:
        assert st.load_cache(tmp_path / "nope.json") == {}
