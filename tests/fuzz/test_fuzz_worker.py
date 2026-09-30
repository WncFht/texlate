"""worker.py 边界性质 fuzz——内部接缝的对抗输入（不跑真管线）。

覆盖面：store 腐化行 → 段函数（DBStateBridge.load / _flush_translate /
_build_dual / _share_apply / _share_lookup）；share 对账 zh 位矩阵；
cancel/teardown 中途失败级联；verdict/审计载荷持久化；SSE 扇出背压；
上传 zip 成员名对抗。

钉样的确认缺陷已清零（W1-W7 全转正）：``_zip_kind`` 成员读异常同
``_zip_member_payload`` 归一（加密成员退 upload_tex）、``_stats``
created_at 坏格按 0 秒容错（done 不再缺）、``DBStateBridge.load``
attempts/warnings 坏格按 0/[] 容错（腐化行 resume 不永 fault）、
``_build_dual`` 非 str 译文 coerce ""（BLOB 不挡 dual.json）、
``unpack_zip`` 成员写体 OSError → ``reject_io:`` 告警跳过
（NAME_MAX/EDQUOT 不拖死整单）。

绿面（正确行为钉样）：成员名 confinement/拒绝告警、share 对账 outcome
枚举与不落库拒绝、伪造 mark 摘除、SSE 溢出 _RESYNC、verdict 载荷
round-trip、同线程/跨线程 _on_loop。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sqlite3
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from texlate.server.store import Store

import pytest
from _drivekit import drive
from _fuzzkit import fuzz_rng
from _workerkit import _insert_chunk, mk_ctx

from texlate.arxiv.unpack import UnpackError
from texlate.server.events import _RESYNC, _SUB_QUEUE_MAX, EventBus
from texlate.server.worker import (
    DBStateBridge,
    PipelineWorker,
    Secrets,
    SegmentCache,
    TaskCtx,
    _md_member,
    _scrub_deep,
    _share_pool,
    _share_row,
    _ShareRejectError,
    chunk_error_code,
    sniff_upload,
    unpack_zip,
)
from texlate.share import share_key
from texlate.xlat.state import ChunkRecord


def _sql(store: Store, stmt: str, *args: object) -> None:
    """直写腐化入口：SQLite 动态类型允许 TEXT 列塞 BLOB / INTEGER 列塞 TEXT。"""
    store.conn.execute(stmt, args)
    store.conn.commit()


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _zip_flagged_encrypted() -> bytes:
    """``mimetype`` 成员 flag bit0 置位（伪装加密）——``zf.read`` 抛 RuntimeError。"""
    data = bytearray(
        _zip_bytes([("mimetype", b"application/epub+zip"), ("a.opf", b"<x/>")])
    )
    for magic, off in ((b"PK\x01\x02", 8), (b"PK\x03\x04", 6)):
        i = 0
        while True:
            i = data.find(magic, i)
            if i < 0:
                break
            data[i + off] |= 0x01
            i += 4
    return bytes(data)


def _zip_nul_member() -> bytes:
    """手搓 central-dir 文件名嵌 NUL 的 zip（``writestr`` 自己会截断，须 raw）。"""
    data = bytearray(_zip_bytes([("ok.tex", b"x"), ("evilname.tex", b"bad")]))
    i = data.find(b"PK\x01\x02")
    i = data.find(b"PK\x01\x02", i + 4)  # 第二个 central entry
    assert i > 0
    fn_off = i + 46
    assert data[fn_off : fn_off + 8] == b"evilname"
    data[fn_off + 4] = 0  # central 名 evil\x00ame.tex
    j = data.find(b"PK\x03\x04")
    j = data.find(b"PK\x03\x04", j + 4)
    data[j + 26 + 4 + 2] = 0  # local 名 ev\x00lname.tex（不同截断点 → 必撞名检）
    return bytes(data)


# ---------------------------------------------------------------- 上传 zip


class TestUnpackZipAdversarial:
    """成员名/容量对抗：逃逸面只许 ``UnpackError``，落盘件必须 confine 在 dest。"""

    _NAMES: ClassVar[list[str]] = [
        "",  # 空名 → parts 空 → rel_s="." → dir-clash 拒
        ".",
        "..",
        "../escape.tex",
        "a/../../b.tex",
        "/abs.tex",
        "C:\\win.tex",
        "\\\\unc\\x.tex",
        "a\\b\\c.tex",  # 反斜杠非分隔符（posix 语义）——照常落
        "sub/./ok.tex",
        "sub/../up.tex",
        "ok.tex",
        "deep/" + "/".join(["d"] * 30) + "/x.tex",
        "unicodé-中.tex",
    ]

    def test_name_matrix_no_escape_and_confined(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        # 整包级拒绝合法——但绝不允许 UnpackError 以外的异常类型逃逸
        with contextlib.suppress(UnpackError):
            unpack_zip(_zip_bytes([(n, b"x") for n in self._NAMES]), dest)
        root = dest.resolve()
        # 扫 tmp_path 而非 dest——``..`` 逃逸件落在 dest 之外（tmp_path 下），
        # 只扫 dest 永远看不到；tmp_path 是本测试独占根，dest 是唯一合法落点
        for f in tmp_path.rglob("*"):
            assert f.resolve().is_relative_to(root), f"越界落盘: {f}"

    def test_fuzz_names_confined(self, tmp_path: Path) -> None:
        rng = fuzz_rng(41)
        soup = ["../", "a", "b.tex", "C:", "\\\\", "/", ".", "..", "中", "x" * 200]
        # 限总长 ≤240B：单段超 NAME_MAX(255B) 的逃逸面由 W7 钉样另测
        seen: set[Path] = set()
        for case in range(200):
            names = [
                n
                for n in (
                    "".join(rng.choice(soup) for _ in range(rng.randint(1, 5)))
                    for _ in range(rng.randint(1, 6))
                )
                if 0 < len(n.encode()) <= 240  # noqa: PLR2004
            ]
            dest = tmp_path / f"z{case}"
            with contextlib.suppress(UnpackError):
                unpack_zip(_zip_bytes([(n, b"x") for n in names]), dest)
            root = dest.resolve()
            # 扫 tmp_path 全树而非 dest——``../x``/``a/../../x`` 逃逸件落 dest
            # 之外（tmp_path 任意深度），dest.rglob 永远看不到；seen 快照跳过
            # 历轮合法落件，本轮新增件必须 confine 在本轮 dest
            for f in tmp_path.rglob("*"):
                if f in seen:
                    continue
                assert f.resolve().is_relative_to(root), f"逃逸: {names} → {f}"
                seen.add(f)

    def test_member_name_too_long_member_warns_not_raises(self, tmp_path: Path) -> None:
        dest = tmp_path / "out"
        warnings = unpack_zip(
            _zip_bytes([("ok.tex", b"x"), ("a" * 300 + ".tex", b"bad")]), dest
        )
        assert (dest / "ok.tex").is_file(), "正常成员不应被坏成员拖死"
        assert any("reject" in w for w in warnings), "坏成员应记 reject 告警"

    def test_nul_member_clean_unpack_error(self, tmp_path: Path) -> None:
        """central-dir 名嵌 NUL → ``ZipInfo`` 读时截断 → 与 local 名不符 → 成员拒。"""
        with pytest.raises(UnpackError, match="bad member"):
            unpack_zip(_zip_nul_member(), tmp_path / "out")

    def test_encrypted_member_unpack_error(self, tmp_path: Path) -> None:
        with pytest.raises(UnpackError, match="bad member"):
            unpack_zip(_zip_flagged_encrypted(), tmp_path / "out")


class TestSniffUpload:
    """魔数路由：PK 容器细分不得把成员级异常漏出边界。"""

    def test_corrupt_pk_falls_to_upload_tex(self) -> None:
        assert sniff_upload(b"PK\x03\x04" + b"\x00" * 20, "x.zip") == "upload_tex"

    def test_garbage_and_text(self) -> None:
        assert sniff_upload(b"\x00\xff\xfe random", "x.bin") == "unknown"
        assert sniff_upload(b"\\documentclass{article}", "x.tex") == "upload_tex"

    def test_encrypted_member_no_escape(self) -> None:
        """加密成员 zip 应退 ``upload_tex``（成员级错由解包处报），不得逃逸。"""
        assert sniff_upload(_zip_flagged_encrypted(), "x.epub") == "upload_tex"


# ---------------------------------------------------------------- scrub


class TestScrubDeep:
    """``_scrub_deep`` 的 secret 抹除面——事件载荷落盘前最后一道闸。"""

    _KEY = "sk-live-abcdef123456"

    def test_str_list_dict_values_scrubbed(self) -> None:
        out = _scrub_deep(
            {"a": f"x {self._KEY}", "l": [self._KEY, "ok"], "n": {"k": self._KEY}},
            self._KEY,
        )
        assert self._KEY not in json.dumps(out)

    def test_tuple_and_dict_key_scrubbed(self) -> None:
        out = _scrub_deep(
            {"k": (f"prefix {self._KEY}", "y"), f"nested-{self._KEY}": 1},
            self._KEY,
        )
        assert self._KEY not in json.dumps(out)


# ---------------------------------------------------------------- share 对账


class TestSharePoolRow:
    """``_share_pool``/``_share_row`` 对账矩阵：outcome 限枚举、update JSON-able。"""

    _OUTCOMES: ClassVar[set[str]] = {
        "ok",
        "dropped",
        "missed",
        "resumed_ok",
        "resumed",
    }

    def test_matrix(self) -> None:
        rng = fuzz_rng(7)
        soup: list[Any] = [
            "a",
            "main.tex",
            "",
            "..",
            "/",
            "中文段落内容",
            "\x00",
            "x" * 400,
            None,
            5,
            b"\x00\xff",
            [1],
            {"k": 1},
        ]
        statuses: list[Any] = [
            "pending",
            "ok",
            "fallback_orig",
            "failed",
            "weird",
            None,
            5,
        ]
        for _ in range(4000):
            row = {
                "status": rng.choice(statuses),
                "src_file": rng.choice(soup),
                "src_text": rng.choice(soup),
                "chunk_id": rng.choice(["c1", "c2", 5, None]),
            }
            pool = _share_pool(
                [
                    {
                        "src_file": rng.choice(soup),
                        "en": rng.choice(soup),
                        "zh": rng.choice(soup),
                    }
                    for _ in range(rng.randint(0, 3))
                ]
            )
            outcome, upd = _share_row(row, pool)
            assert outcome in self._OUTCOMES, f"outcome 越枚举: {outcome!r} row={row!r}"
            if upd is not None:
                json.dumps(upd)  # update 载荷必须 JSON-able
                assert upd["status"] in ("ok", "fallback_orig")
            if row["status"] != "pending":
                assert upd is None, "非 pending 行不得再判"
                expected = "resumed_ok" if row["status"] == "ok" else "resumed"
                assert outcome == expected

    def test_pending_hit_validate_gate(self) -> None:
        """命中条目过 ``validate_pair`` 闸：占位符失配 → dropped+fallback_orig。"""
        src = "Text with [[PH_1]] placeholder inside."
        pool = _share_pool([{"src_file": "m.tex", "en": src, "zh": "译文缺占位符"}])
        outcome, upd = _share_row(
            {
                "status": "pending",
                "src_file": "m.tex",
                "src_text": src,
                "chunk_id": "c",
            },
            pool,
        )
        assert outcome == "dropped"
        assert upd is not None
        assert upd["status"] == "fallback_orig"
        assert upd["error_code"] == "validate"
        assert "share_validate" in str(upd["warnings"])


class TestShareApply:
    """``_share_apply`` 边界：拒绝路径不写库（无半更新）。"""

    def _put_dual(self, ctx: TaskCtx, doc: object) -> None:
        (ctx.root / "share").mkdir(parents=True, exist_ok=True)
        (ctx.root / "share" / "dual.json").write_text(
            doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_zero_local_chunks_rejects_without_writes(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        self._put_dual(ctx, {"chunks": [{"src_file": "m", "en": "x", "zh": "译"}]})
        with pytest.raises(_ShareRejectError):
            worker.run_stage(ctx, "share_apply")
        assert not store.has_chunks(ctx.task_id)

    @pytest.mark.parametrize(
        "payload",
        [
            "[1,2]",
            '"x"',
            "5",
            "null",
            '{"chunks": "x"}',
            '{"chunks": {"a": 1}}',
            '{"chunks": null}',
            "not-json{{{",
        ],
    )
    def test_doc_shape_rejects(self, tmp_path: Path, payload: str) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        self._put_dual(ctx, payload)
        with pytest.raises(_ShareRejectError):
            worker.run_stage(ctx, "share_apply")

    def test_nonstr_src_file_coerced_and_matched(self, tmp_path: Path) -> None:
        """src_file 直写成 int → str() 归一 → 与 share 条目 "7" 正常命中（非 TypeError）。"""
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        _sql(store, "UPDATE chunks SET src_file=7 WHERE task_id=?", ctx.task_id)
        self._put_dual(
            ctx, {"chunks": [{"src_file": "7", "en": "hello world", "zh": "译"}]}
        )
        out = worker.run_stage(ctx, "share_apply")
        assert out["matched"] == 1
        assert store.all_chunks(ctx.task_id)[0]["status"] == "ok"

    def test_nonstr_src_file_miss_clean_reject(self, tmp_path: Path) -> None:
        """非 str src_file 且 share 无对应键 → miss → 零命中干净拒。"""
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        _sql(store, "UPDATE chunks SET src_file=7 WHERE task_id=?", ctx.task_id)
        self._put_dual(
            ctx, {"chunks": [{"src_file": "m.tex", "en": "hello world", "zh": "译"}]}
        )
        with pytest.raises(_ShareRejectError):
            worker.run_stage(ctx, "share_apply")
        assert store.all_chunks(ctx.task_id)[0]["status"] == "pending"

    def test_resumed_ok_counts_as_matched(self, tmp_path: Path) -> None:
        """上轮已落库 ok 行 → ``resumed_ok`` 计 matched——重跑不误判零命中。"""
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, status="ok")
        store.update_chunk(ctx.task_id, "c1", {"translation": "旧译文"})
        store.conn.commit()
        self._put_dual(ctx, {"chunks": []})
        out = worker.run_stage(ctx, "share_apply")
        assert out["matched"] == 1


class TestShareLookupMarks:
    """``_share_lookup`` 伪造/残缺 mark 对抗面。"""

    _KEY_PARTS: ClassVar[dict[str, str]] = {
        "arxiv_id": "2401.00001",
        "version": "v1",
        "model": "m",
        "prompt_ver": "p",
        "target_lang": "zh-CN",
        "glossary_hash": "",
        "pipeline_ver": "pv",
    }

    def _mk_marked(
        self,
        tmp_path: Path,
        marked: object,
        *,
        dual: bool,
        reuse_hit: str | None = None,
        with_chunks: bool = True,
    ) -> tuple[TaskCtx, PipelineWorker, Store]:
        ctx, worker, store = mk_ctx(tmp_path)
        if with_chunks:
            _insert_chunk(store, ctx.task_id)
        worker.share_pack_manifest = lambda _c, _r: dict(self._KEY_PARTS)  # type: ignore[method-assign]
        opts: dict[str, object] = {}
        if marked is not None:
            opts["share"] = marked
        if reuse_hit is not None:
            opts["reuse_hit"] = reuse_hit
        store.update_fields(ctx.task_id, options_json=json.dumps(opts))
        ctx.row["options_json"] = json.dumps(opts)
        if dual:
            (ctx.root / "share").mkdir(parents=True)
            (ctx.root / "share" / "dual.json").write_text(
                json.dumps({"chunks": []}), encoding="utf-8"
            )
        return ctx, worker, store

    @pytest.mark.parametrize(
        "marked",
        ["forged-str", 5, ["x"], {"share_key": "deadbeef"}, {"nope": 1}],
    )
    def test_forged_mark_unmarked_and_miss(
        self, tmp_path: Path, marked: object
    ) -> None:
        ctx, worker, store = self._mk_marked(tmp_path, marked, dual=True)
        assert worker.run_stage(ctx, "share_lookup") is False
        opts = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert "share" not in opts, "伪造 share 载荷必须摘除"
        assert not (ctx.root / "share").exists(), "解包现场必须清"

    def test_right_key_no_dual_unmarks(self, tmp_path: Path) -> None:
        key = share_key(**self._KEY_PARTS)  # type: ignore[arg-type]
        ctx, worker, store = self._mk_marked(tmp_path, {"share_key": key}, dual=False)
        assert worker.run_stage(ctx, "share_lookup") is False
        opts = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert "share" not in opts

    def test_valid_mark_restores_hit_flag(self, tmp_path: Path) -> None:
        """mark 完整 + dual.json 在场 + reuse_hit 被抹 → 补回 share: 来历并命中。"""
        key = share_key(**self._KEY_PARTS)  # type: ignore[arg-type]
        ctx, worker, store = self._mk_marked(tmp_path, {"share_key": key}, dual=True)
        assert worker.run_stage(ctx, "share_lookup") is True
        opts = json.loads(str(store.get(ctx.task_id)["options_json"]))
        assert str(opts["reuse_hit"]).startswith("share:")

    def test_dedup_hit_without_mark_skips_lookup(self, tmp_path: Path) -> None:
        """``options.reuse_hit``（dedup 来历）+ 无 share 载荷 → 不查索引直返。"""
        ctx, worker, _store = self._mk_marked(
            tmp_path, None, dual=False, reuse_hit="taskid-abc"
        )
        assert worker.run_stage(ctx, "share_lookup") is False

    def test_fresh_prefer_skips(self, tmp_path: Path) -> None:
        ctx, worker, store = self._mk_marked(tmp_path, None, dual=False)
        opts = {"prefer": "fresh"}
        store.update_fields(ctx.task_id, options_json=json.dumps(opts))
        ctx.row["options_json"] = json.dumps(opts)
        assert worker.run_stage(ctx, "share_lookup") is False

    def test_nul_url_row_degrades_to_miss(self, tmp_path: Path) -> None:
        """index 行 url 含 ``\\x00`` → 扁平检查拒、按 miss 回退——钉住与
        app.py share_pack 同口径的扁平名面（``stat()`` 对 NUL 抛
        ValueError，此面若改 stat 探测即开口）。"""
        ctx, worker, _store = self._mk_marked(tmp_path, None, dual=False)
        key = share_key(**self._KEY_PARTS)  # type: ignore[arg-type]
        out_dir = tmp_path / "share"
        out_dir.mkdir(parents=True)
        (out_dir / "index.jsonl").write_text(
            json.dumps({"share_key": key, "url": "evil\x00name.share.zip"}) + "\n",
            encoding="utf-8",
        )
        assert worker.run_stage(ctx, "share_lookup") is False


# ---------------------------------------------------------------- store 腐化行 → 段函数


class TestDBStateBridgeLoad:
    """``load`` 的 chunks 行容错面——腐化格不得让 resume 永 fault。"""

    def _load(self, store: Store, task_id: str) -> tuple[set, dict]:
        return DBStateBridge(store, task_id).load()

    def test_clean_rows_roundtrip(self, tmp_path: Path) -> None:
        ctx, _w, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, status="ok")
        store.update_chunk(
            ctx.task_id,
            "c1",
            {"translation": "译文", "attempts": 2, "warnings": '["w1"]'},
        )
        store.conn.commit()
        completed, recs = self._load(store, ctx.task_id)
        assert completed == {"c1"}
        assert recs["c1"].translation == "译文"
        assert recs["c1"].warnings == ["w1"]

    def test_pending_and_unknown_status_skipped(self, tmp_path: Path) -> None:
        ctx, _w, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, "c1")  # pending
        _insert_chunk(store, ctx.task_id, "c2", seq=1)
        _sql(
            store,
            "UPDATE chunks SET status='weird' WHERE chunk_id='c2'",
        )
        completed, recs = self._load(store, ctx.task_id)
        assert not completed
        assert not recs

    @pytest.mark.parametrize(
        "warnings",
        ["123", '"x"', "{}", "[1,2]"],  # 合法 JSON 非 list——容忍载入不崩
    )
    def test_warnings_nonlist_tolerated(self, tmp_path: Path, warnings: str) -> None:
        ctx, _w, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, status="ok")
        _sql(
            store,
            "UPDATE chunks SET warnings=? WHERE task_id=?",
            warnings,
            ctx.task_id,
        )
        completed, recs = self._load(store, ctx.task_id)
        assert completed == {"c1"}
        assert "c1" in recs

    @pytest.mark.parametrize("corrupt", ["{bad json", "X'00FF'"])
    def test_corrupt_warnings_tolerated(self, tmp_path: Path, corrupt: str) -> None:
        ctx, _w, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, status="ok")
        if corrupt.startswith("X'"):
            _sql(
                store,
                f"UPDATE chunks SET warnings={corrupt} WHERE task_id=?",  # noqa: S608
                ctx.task_id,
            )
        else:
            _sql(
                store,
                "UPDATE chunks SET warnings=? WHERE task_id=?",
                corrupt,
                ctx.task_id,
            )
        completed, _recs = self._load(store, ctx.task_id)
        assert completed == {"c1"}

    def test_corrupt_attempts_tolerated(self, tmp_path: Path) -> None:
        ctx, _w, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id, status="ok")
        _sql(store, "UPDATE chunks SET attempts='abc' WHERE task_id=?", ctx.task_id)
        completed, _recs = self._load(store, ctx.task_id)
        assert completed == {"c1"}


class TestBuildDualCorrupt:
    """``_build_dual`` 对腐化 chunks/files 行的容错面。"""

    def test_blob_translation_coerced(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        _insert_chunk(store, ctx.task_id, status="ok")
        _sql(
            store,
            "UPDATE chunks SET translation=X'00FF' WHERE task_id=?",
            ctx.task_id,
        )
        worker._build_dual(ctx)  # noqa: SLF001
        doc = json.loads((ctx.root / "dual.json").read_text(encoding="utf-8"))
        assert doc["chunks"], "BLOB 译文不得阻止 dual.json 落盘"

    def test_clean_dual_roundtrip(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        _insert_chunk(store, ctx.task_id, status="ok")
        store.update_chunk(ctx.task_id, "c1", {"translation": "译文🎉"})
        store.conn.commit()
        worker._build_dual(ctx)  # noqa: SLF001
        doc = json.loads((ctx.root / "dual.json").read_text(encoding="utf-8"))
        assert doc["chunks"][0]["zh"] == "译文🎉"
        assert store.file_record(ctx.task_id, "dual_json") is not None


# ---------------------------------------------------------------- flush/teardown 级联


class _FakeClient:
    """duck-type aclose 记录器。"""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _segcache(store: Store) -> SegmentCache:
    return SegmentCache(store, prefix="t", model="m", target_lang="zh-CN")


class TestFlushTranslate:
    """``_flush_translate`` 事务语义 + 失败顺序。"""

    def _state_with(self, store: Store, task_id: str) -> DBStateBridge:
        state = DBStateBridge(store, task_id)
        state.buffer.append(
            ChunkRecord(
                chunk_id="c1",
                source="hello world",
                translation="译文",
                status="ok",
                attempts=1,
            )
        )
        return state

    def test_happy_path_writes_rows_and_event(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        state = self._state_with(store, ctx.task_id)
        sse: list[dict[str, Any]] = [{"seq": 0, "status": "ok"}]
        worker._flush_translate(ctx, state, _segcache(store), {}, sse)  # noqa: SLF001
        row = store.all_chunks(ctx.task_id)[0]
        assert row["status"] == "ok"
        assert row["translation"] == "译文"
        assert row["attempts"] == 1
        assert sse == []
        types = [e["type"] for e in store.events_since(ctx.task_id, 0)]
        assert "chunk" in types

    def test_empty_early_return(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        state = DBStateBridge(store, ctx.task_id)
        worker._flush_translate(ctx, state, _segcache(store), {}, [])  # noqa: SLF001
        assert store.events_since(ctx.task_id, 0) == []

    def test_flush_failure_retains_buffer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        state = self._state_with(store, ctx.task_id)

        def boom(*_a: object, **_kw: object) -> None:
            raise sqlite3.OperationalError("database is locked")  # noqa: TRY003, EM101

        monkeypatch.setattr(store, "flush_chunk_batch", boom)
        with pytest.raises(sqlite3.OperationalError):
            worker._flush_translate(  # noqa: SLF001
                ctx, state, _segcache(store), {}, [{"seq": 0, "status": "ok"}]
            )
        assert len(state.buffer) == 1, "flush 失败不得丢缓冲记录"

    def test_publish_failure_keeps_committed_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """publish 在 commit 之后——事件丢失但 DB 已落（commit-first 设计钉样）。"""
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        state = self._state_with(store, ctx.task_id)

        def boom(*_a: object, **_kw: object) -> int:
            msg = "bus dead"
            raise RuntimeError(msg)

        monkeypatch.setattr(worker.bus, "publish", boom)
        with pytest.raises(RuntimeError):
            worker._flush_translate(ctx, state, _segcache(store), {}, [])  # noqa: SLF001
        assert store.all_chunks(ctx.task_id)[0]["status"] == "ok"


class TestTeardownTranslateCascade:
    """``_teardown_translate`` 中途失败级联——收尾项不得互相拖死。"""

    def _drive(  # noqa: PLR0913, PLR0917
        self,
        worker: PipelineWorker,
        ctx: TaskCtx,
        state: DBStateBridge,
        cache: SegmentCache,
        clients: list[object],
        pre_rows: dict[str, tuple[str, str]],
    ) -> None:
        asyncio.run(
            worker.run_stage(  # run_stage 直驱
                ctx,
                "teardown_translate",
                run_task=None,
                state=state,
                cache=cache,
                status_map={},
                sse_items=[],
                usage={"calls": 0},
                clients=clients,  # type: ignore[arg-type]
                pre_rows=pre_rows,
            )
        )

    def test_empty_teardown_noop(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        self._drive(
            worker, ctx, DBStateBridge(store, ctx.task_id), _segcache(store), [], {}
        )

    def test_flush_failure_still_invalidates_and_closes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        ctx.zh_dir.mkdir(parents=True)
        sent = ctx.zh_dir / ".splice-done"
        sent.write_text("", encoding="utf-8")
        # 编造与现状不同的 pre_rows——若 invalidate 真跑，必摘哨兵
        pre_rows = {"c1": ("ok", "旧译文")}
        state = DBStateBridge(store, ctx.task_id)
        state.buffer.append(
            ChunkRecord(chunk_id="c1", source="s", translation="t", status="ok")
        )
        client = _FakeClient()

        def boom(*_a: object, **_kw: object) -> None:
            raise sqlite3.OperationalError("disk I/O error")  # noqa: TRY003, EM101

        monkeypatch.setattr(store, "flush_chunk_batch", boom)
        with contextlib.suppress(sqlite3.OperationalError):
            self._drive(worker, ctx, state, _segcache(store), [client], pre_rows)
        assert client.closed, "flush 失败不得跳过 client aclose"
        assert not sent.is_file(), "flush 失败不得跳过 splice 哨兵失效判定"

    def test_flush_failure_does_not_mask_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        _insert_chunk(store, ctx.task_id)
        state = DBStateBridge(store, ctx.task_id)
        state.buffer.append(
            ChunkRecord(chunk_id="c1", source="s", translation="t", status="ok")
        )

        def boom(*_a: object, **_kw: object) -> None:
            raise sqlite3.OperationalError("locked")  # noqa: EM101

        monkeypatch.setattr(store, "flush_chunk_batch", boom)

        async def drive() -> None:
            try:
                raise KeyError("original-auth-fail")  # noqa: EM101
            finally:
                await worker.run_stage(  # run_stage 直驱
                    ctx,
                    "teardown_translate",
                    run_task=None,
                    state=state,
                    cache=_segcache(store),
                    status_map={},
                    sse_items=[],
                    usage={"calls": 0},
                    clients=[],
                    pre_rows={},
                )

        with pytest.raises(KeyError, match="original-auth-fail"):
            asyncio.run(drive())


# ---------------------------------------------------------------- _stats / 终态一致性


class TestTerminalDoneEvent:
    """终态行必须配 ``done`` 事件——``stream()`` 订阅者靠它收尾。"""

    def _event_types(self, store: Store, task_id: str) -> list[str]:
        return [e["type"] for e in store.events_since(task_id, 0)]

    def test_fail_publishes_done(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        worker._fail(ctx, "internal", "boom", retryable=False, stage="translating")  # noqa: SLF001
        assert store.get(ctx.task_id)["status"] == "fault"
        assert "done" in self._event_types(store, ctx.task_id)

    def test_corrupt_created_at_still_publishes_done(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.row["created_at"] = "abc"  # update_fields 无字段白名单可直写
        worker._fail(ctx, "internal", "boom", retryable=False, stage="translating")  # noqa: SLF001
        assert store.get(ctx.task_id)["status"] == "fault"
        assert "done" in self._event_types(store, ctx.task_id)

    def test_corrupt_created_at_reject_still_done(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.row["created_at"] = {"x": 1}  # float(dict) → TypeError
        worker._reject(ctx, "share_verify", "m", reject_at="share")  # noqa: SLF001
        assert store.get(ctx.task_id)["status"] == "partial"
        assert "done" in self._event_types(store, ctx.task_id)


# ---------------------------------------------------------------- verdict/载荷持久化


class TestVerdictPersistence:
    """终态载荷（fixloop/l2/share 摘要）经 error_json 的 round-trip 面。"""

    def test_huge_nonascii_fixloop_roundtrip(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        big = {
            "verdict": "reject:r42",
            "trace": [
                {"round": i, "cat": "font", "detail": f"理由{i} 中文 details 🎉"}
                for i in range(300)
            ],
        }
        worker._reject(  # noqa: SLF001
            ctx,
            "fixloop_reject",
            "fixloop policy reject: reject:r42",
            reject_at="fixloop",
            detail={"fixloop": big},
        )
        err = json.loads(str(store.get(ctx.task_id)["error_json"]))
        assert err["fixloop"] == big, "巨型非 ASCII detail 必须字节级 round-trip"
        assert err["reject_at"] == "fixloop"

    def test_transition_nonserializable_no_partial_write(self, tmp_path: Path) -> None:
        """error 载荷不可序列化 → transition 在 UPDATE 之前炸，行不被污染。"""
        ctx, worker, store = mk_ctx(tmp_path)  # noqa: RUF059
        store.transition(ctx.task_id, "translating", force=True)
        with pytest.raises(TypeError):
            store.transition(
                ctx.task_id, "fault", error={"code": "x", "blob": b"\x00"}, force=True
            )
        assert store.get(ctx.task_id)["status"] == "translating"

    def test_log_and_warning_scrub_secret(self, tmp_path: Path) -> None:
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.secrets = Secrets(api_key="sk-top-secret-1")
        worker._log(ctx, "line with sk-top-secret-1 inside")  # noqa: SLF001
        worker._warning(ctx, "w", "warn sk-top-secret-1 tail")  # noqa: SLF001
        for e in store.events_since(ctx.task_id, 0):
            assert "sk-top-secret-1" not in json.dumps(e["data"])

    def test_stats_shape(self, tmp_path: Path) -> None:
        ctx, worker, _store = mk_ctx(tmp_path)
        ctx.fixloop = {"verdict": "clean"}
        ctx.l2 = {
            "enabled": True,
            "errors": 2,
            "retranslated": ["a"],
            "fallback_src": [],
        }
        s = worker._stats(ctx)  # noqa: SLF001
        assert s["fixloop"] == "clean"
        assert s["l2"]["retranslated"] == 1
        assert isinstance(s["seconds"], float)


# ---------------------------------------------------------------- SSE 背压


class TestEventFanoutBackpressure:
    """worker publish 时订阅者溢出：``_RESYNC`` 哨兵断流 + 落盘事件可重放。"""

    def test_overflow_cuts_stalled_subscriber(self, tmp_path: Path) -> None:
        ctx, _worker, store = mk_ctx(tmp_path)
        bus = EventBus(store)
        q = bus.subscribe(ctx.task_id)
        for i in range(_SUB_QUEUE_MAX + 5):
            bus.publish(ctx.task_id, "log", {"line": f"l{i}"})
        # 积压 → 订阅被摘除 + 哨兵压尾
        assert ctx.task_id not in bus._subs or q not in bus._subs[ctx.task_id]  # noqa: SLF001
        tail = q.get_nowait()
        assert tail is _RESYNC
        # 落盘面完好——重放补齐
        evs = store.events_since(ctx.task_id, 0)
        assert len(evs) >= _SUB_QUEUE_MAX
        assert evs[-1]["type"] == "log"

    def test_flush_publish_under_full_queue_no_raise(self, tmp_path: Path) -> None:
        """``_flush_translate`` 的 chunk 事件扇出到满队列不炸。"""
        ctx, worker, store = mk_ctx(tmp_path)
        bus = worker.bus
        q = bus.subscribe(ctx.task_id)
        for i in range(_SUB_QUEUE_MAX):  # 灌满
            bus.publish(ctx.task_id, "log", {"line": str(i)})
        _insert_chunk(store, ctx.task_id)
        state = DBStateBridge(store, ctx.task_id)
        state.buffer.append(
            ChunkRecord(chunk_id="c1", source="s", translation="t", status="ok")
        )
        worker._flush_translate(  # noqa: SLF001
            ctx, state, _segcache(store), {}, [{"seq": 0, "status": "ok"}]
        )
        assert store.all_chunks(ctx.task_id)[0]["status"] == "ok"
        assert q.get_nowait() is _RESYNC


# ---------------------------------------------------------------- _on_loop / misc


class TestOnLoop:
    """``_on_loop`` 线程纪律：loop 线程直调、worker 线程回弹。"""

    def test_same_thread_direct(self, tmp_path: Path) -> None:
        _ctx, worker, _store = mk_ctx(tmp_path)
        # _loop 未钉 → 直调
        assert worker._on_loop(lambda: 42) == 42  # noqa: SLF001, PLR2004

    def test_cross_thread_bounce(self, tmp_path: Path) -> None:
        _ctx, worker, _store = mk_ctx(tmp_path)
        ran_on: list[int] = []

        async def bounce() -> int:
            await asyncio.to_thread(
                worker._on_loop,  # noqa: SLF001
                lambda: ran_on.append(threading.get_ident()),
            )
            return threading.get_ident()

        loop_tid = drive(worker, bounce())
        assert ran_on == [loop_tid], "worker 线程调用必须回弹 loop 线程"


class TestChunkErrorCode:
    """``chunk_error_code`` 域内矩阵——归因序（error_kind → skipped → fault）。"""

    def test_matrix(self) -> None:
        rng = fuzz_rng(3)
        kinds = ["", "auth", "provider", "crash", "validate", "weird"]
        for _ in range(500):
            rec = ChunkRecord(
                chunk_id="c",
                source="s",
                translation="t",
                status=rng.choice(["ok", "partial", "skipped", "fault", "weird"]),
                skipped=rng.choice([True, False]),
                skip_reason=rng.choice(
                    ["", "placeholder mismatch", "validate: x", "其他"]
                ),
                error_kind=rng.choice(kinds),
            )
            code = chunk_error_code(rec)
            assert code in (
                None,
                "provider_auth",
                "provider_error",
                "internal",
                "placeholder_mismatch",
                "validate",
            ), f"code 越集: {code!r}"
            if rec.error_kind in ("auth", "provider", "crash"):
                assert code is not None  # error_kind 归因最优先


class TestMdMember:
    """``_md_member`` zip 成员名净化——段级 ``..``/绝对/驱动器/NUL 不得出现。"""

    def test_fuzz_names_safe(self) -> None:
        rng = fuzz_rng(11)
        seen: set[str] = set()
        soup = [
            "../",
            "a",
            "b.tex",
            "C:",
            "\\\\",
            "/",
            ".",
            "..",
            "中文",
            "\x00",
            "x" * 300,
            "a/b/c",
            ".TEX",
            "  ",
            "..\\",
            "a/../b.tex",
        ]
        members: set[str] = set()
        for _ in range(4000):
            sf = "".join(rng.choice(soup) for _ in range(rng.randint(0, 6)))
            m = _md_member(sf, seen)
            parts = PurePosixPath(m).parts
            assert all(pt != ".." for pt in parts), f"逃逸段: {m!r}"
            assert not m.startswith("/")
            assert "\x00" not in m
            assert "\\" not in m
            assert ":" not in m
            members.add(m)
        assert len(members) > 100, "样本面太窄"  # noqa: PLR2004


# ---------------------------------------------------------------- store 直写面


class TestStoreDirectCorruption:
    """直写腐化的残余面（update_fields 无字段白名单——段函数须自身容错）。"""

    def test_options_corrupt_json_tolerated(self, tmp_path: Path) -> None:
        ctx, _worker, store = mk_ctx(tmp_path)
        store.update_fields(ctx.task_id, options_json="{bad")
        ctx.row["options_json"] = "{bad"
        assert ctx.options() == {}
        ctx.row["options_json"] = "[1,2]"  # 非 dict JSON
        assert ctx.options() == {}
