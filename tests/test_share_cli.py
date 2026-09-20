"""share 子命令 CLI 接线：pack 字段来源/报错面 + unpack 校验 + round-trip。

库层格式/校验语义由 ``test_share.py`` 钉——这里打 CLI 侧契约：任务目录/
任务 id 分流、texlate.db 只读定位、key_parts 派生（含 cache_key 交叉
验证）、``-o`` 目录/文件两形、退出码（1 操作失败 / 2 参数错）。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from texlate.arxiv.fetch import normalize_arxiv_id
from texlate.cli import app
from texlate.pipecore import front_matter_of
from texlate.server.store import DDL
from texlate.server.worker import PIPELINE_VERSION, cache_key_for
from texlate.share import MANIFEST_NAME, pack_share, share_key
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from click.testing import Result

_RUNNER = CliRunner()
#: rich help 把 ``--out`` 按高亮 span 切段（``-``+``-out`` 各自带 ANSI）——
#: 断言旗标名前先剥转义序列，否则字面 ``--out`` 不连续
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TASK_ID = "t_0123456789ab"
_ZH_TEX = "\\documentclass{article}\\begin{document}正文\\end{document}"
_FAKE_KEY = "f" * 64


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离本机状态：TEXLATE_DATA_DIR / cache_scope。"""
    monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "env-data"))
    monkeypatch.delenv("TEXLATE_CACHE_SCOPE", raising=False)


def _mk_task(  # noqa: PLR0913 -- 任务行字段面即参数面
    data: Path,
    *,
    task_id: str = _TASK_ID,
    arxiv_id: str | None = "0707.0110v1",
    status: str = "done",
    model: str = "deepseek-chat",
    lang: str = "zh-CN",
    cfg: dict[str, object] | None = None,
    opts: dict[str, object] | None = None,
    key: str | None = None,
    artifacts: bool = True,
) -> Path:
    """合成 ``<data>/tasks/<id>`` 产物三件套 + ``texlate.db`` 任务行。"""
    tdir = data / "tasks" / task_id
    tdir.mkdir(parents=True)
    if artifacts:
        (tdir / "dual.json").write_text(
            json.dumps({"version": 1, "documents": {}, "chunks": []}),
            encoding="utf-8",
        )
        (tdir / "zh.pdf").write_bytes(b"%PDF-1.4 fake pdf")
        with zipfile.ZipFile(tdir / "zh-src.zip", "w") as zf:
            zf.writestr("main.tex", _ZH_TEX)
    # done 任务经 parse 写回 options.front_matter 显式集——fixture 模拟
    # 该不变量（缺省解析 {abstract,title}），cache_key 同料进 fm 成分
    eff_opts = dict(opts or {})
    fm = front_matter_of(eff_opts)
    eff_opts["front_matter"] = {k: k in fm for k in ("abstract", "title", "author")}
    if key is None and arxiv_id:
        base, _ver = normalize_arxiv_id(arxiv_id)
        # 请求未钉版形态（cache_key_for 进键用请求时 version=None）
        key = cache_key_for(
            arxiv_id=base,
            version=None,
            model=model,
            target_lang=lang,
            front_matter=fm,
        )
    conn = sqlite3.connect(str(data / "texlate.db"))
    try:
        conn.executescript(DDL)
        conn.execute(
            "INSERT INTO tasks (id, kind, status, arxiv_id, source_name,"
            " target_lang, model, config_json, options_json, cache_key,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                "arxiv",
                status,
                arxiv_id,
                arxiv_id or "",
                lang,
                model,
                json.dumps(cfg or {}),
                json.dumps(eff_opts),
                key,
                0.0,
                0.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return tdir


def _pack(tdir: Path, *extra: str) -> Result:
    return _RUNNER.invoke(app, ["share", "pack", str(tdir), *extra])


class TestSharePack:
    def test_roundtrip(self, tmp_path: Path) -> None:
        """pack 产物 → unpack 回读：key_parts/产物/落盘全对。"""
        tdir = _mk_task(tmp_path / "data")
        out_dir = tmp_path / "out"
        res = _pack(tdir, "-o", str(out_dir))
        assert res.exit_code == 0, res.output
        report = json.loads(res.stdout)
        kp = report["key_parts"]
        assert kp == {
            "arxiv_id": "0707.0110",
            "version": "v1",
            "model": "deepseek-chat",
            "prompt_ver": PROMPT_VERSION,
            "target_lang": "zh-CN",
            "glossary_hash": "",
            "front_matter": "abstract,title",
            "pipeline_ver": PIPELINE_VERSION,
        }
        assert report["share_key"] == share_key(**kp)
        bundle = out_dir / f"{report['share_key']}.share.zip"
        assert bundle.is_file()

        dest = tmp_path / "un"
        res2 = _RUNNER.invoke(app, ["share", "unpack", str(bundle), "-o", str(dest)])
        assert res2.exit_code == 0, res2.output
        mf = json.loads(res2.stdout)
        assert mf["share_key"] == report["share_key"]
        assert mf["key_parts"] == kp
        assert set(mf["artifacts"]) == {"zh-src.zip", "zh.pdf", "dual.json"}
        for name in mf["artifacts"]:
            assert (dest / name).is_file()

    def test_pack_by_task_id_with_data_dir(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        _mk_task(data, task_id="t_aabbccddee11")
        res = _RUNNER.invoke(
            app,
            [
                "share",
                "pack",
                "t_aabbccddee11",
                "--data-dir",
                str(data),
                "-o",
                str(tmp_path / "o"),
            ],
        )
        assert res.exit_code == 0, res.output
        assert json.loads(res.stdout)["task_id"] == "t_aabbccddee11"

    def test_pack_by_task_id_via_env(self, tmp_path: Path) -> None:
        """任务 id + TEXLATE_DATA_DIR 环境定位（autouse 已设）。"""
        _mk_task(Path(os.environ["TEXLATE_DATA_DIR"]), task_id="t_fedcba987654")
        res = _RUNNER.invoke(
            app, ["share", "pack", "t_fedcba987654", "-o", str(tmp_path / "o")]
        )
        assert res.exit_code == 0, res.output

    def test_pack_out_file_path(self, tmp_path: Path) -> None:
        """``-o`` 文件形路径按给定名落盘（不走 {key}.share.zip 约定名）。"""
        tdir = _mk_task(tmp_path / "data")
        target = tmp_path / "custom.texl-share"
        res = _pack(tdir, "-o", str(target))
        assert res.exit_code == 0, res.output
        assert target.is_file()
        assert json.loads(res.stdout)["path"] == str(target)

    def test_pack_contributor(self, tmp_path: Path) -> None:
        tdir = _mk_task(tmp_path / "data")
        out_dir = tmp_path / "out"
        res = _pack(tdir, "-o", str(out_dir), "--contributor", "alice-01")
        assert res.exit_code == 0, res.output
        bundle = out_dir / f"{json.loads(res.stdout)['share_key']}.share.zip"
        with zipfile.ZipFile(bundle) as zf:
            doc = json.loads(zf.read(MANIFEST_NAME))
        assert doc["contributor"] == "alice-01"

    def test_pack_pinned_form_cache_key_ok(self, tmp_path: Path) -> None:
        """stored cache_key 是钉版请求形态（version=v1 进键）也通过交叉验证。"""
        key = cache_key_for(
            arxiv_id="0707.0110",
            version=1,
            model="deepseek-chat",
            target_lang="zh-CN",
            # fixture options 带显式 fm dict（parse 写回形）——进键同料
            front_matter=front_matter_of({}),
        )
        tdir = _mk_task(tmp_path / "data", key=key)
        res = _pack(tdir, "-o", str(tmp_path / "o"))
        assert res.exit_code == 0, res.output

    def test_pack_partial_status_ok(self, tmp_path: Path) -> None:
        tdir = _mk_task(tmp_path / "data", status="partial")
        assert _pack(tdir, "-o", str(tmp_path / "o")).exit_code == 0

    def test_pack_rejects_unknown_arg(self) -> None:
        res = _RUNNER.invoke(app, ["share", "pack", "not-a-dir-nor-id"])
        assert res.exit_code == 1
        assert "既不是已存在目录也不像任务 id" in res.stderr

    def test_pack_rejects_missing_task_dir(self, tmp_path: Path) -> None:
        res = _RUNNER.invoke(
            app,
            ["share", "pack", "t_deadbeef0000", "--data-dir", str(tmp_path)],
        )
        assert res.exit_code == 1
        assert "任务目录不存在" in res.stderr

    def test_pack_rejects_no_db(self, tmp_path: Path) -> None:
        """产物齐全但四周/数据根都没有 texlate.db → 显式报错不编字段。"""
        tdir = tmp_path / "tasks" / _TASK_ID
        tdir.mkdir(parents=True)
        (tdir / "dual.json").write_text("{}", encoding="utf-8")
        (tdir / "zh.pdf").write_bytes(b"%PDF-1.4")
        with zipfile.ZipFile(tdir / "zh-src.zip", "w") as zf:
            zf.writestr("main.tex", _ZH_TEX)
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "定位不到 texlate.db" in res.stderr

    def test_pack_rejects_missing_row(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        tdir = data / "tasks" / _TASK_ID
        tdir.mkdir(parents=True)
        conn = sqlite3.connect(str(data / "texlate.db"))
        try:
            conn.executescript(DDL)
            conn.commit()
        finally:
            conn.close()
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "任务行不在库中" in res.stderr

    def test_pack_rejects_bad_status(self, tmp_path: Path) -> None:
        tdir = _mk_task(tmp_path / "data", status="queued")
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "不可打包" in res.stderr

    def test_pack_rejects_no_arxiv_id(self, tmp_path: Path) -> None:
        tdir = _mk_task(tmp_path / "data", arxiv_id=None, key="")
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "无 arxiv_id" in res.stderr

    def test_pack_rejects_cache_key_mismatch(self, tmp_path: Path) -> None:
        """stored cache_key 与当前管线重算不符 → 拒绝错标 share key。"""
        tdir = _mk_task(tmp_path / "data", key=_FAKE_KEY)
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "重算不符" in res.stderr

    def test_pack_per_key_scope_warns_not_blocks(self, tmp_path: Path) -> None:
        """per_key 分桶下无法重算（含凭证指纹）→ 告警放行。"""
        tdir = _mk_task(tmp_path / "data", key=_FAKE_KEY)
        res = _RUNNER.invoke(
            app,
            ["share", "pack", str(tdir), "-o", str(tmp_path / "o")],
            env={"TEXLATE_CACHE_SCOPE": "per_key"},
        )
        assert res.exit_code == 0, res.output
        assert "per_key" in res.stderr

    def test_pack_missing_artifact_rejected(self, tmp_path: Path) -> None:
        """必需产物缺席 → 拒绝（zh-src.zip 是必需件）。"""
        tdir = _mk_task(tmp_path / "data")
        (tdir / "zh-src.zip").unlink()
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "zh-src.zip" in res.stderr

    def test_pack_partial_no_zh_pdf(self, tmp_path: Path) -> None:
        """partial 任务无 zh.pdf → 打包成功，manifest/包内均无该成员，
        unpack 侧正常消费。"""
        tdir = _mk_task(tmp_path / "data", status="partial")
        (tdir / "zh.pdf").unlink()
        out_dir = tmp_path / "out"
        res = _pack(tdir, "-o", str(out_dir))
        assert res.exit_code == 0, res.output
        assert "zh.pdf 不在场" in res.stderr
        report = json.loads(res.stdout)
        bundle = out_dir / f"{report['share_key']}.share.zip"
        with zipfile.ZipFile(bundle) as zf:
            doc = json.loads(zf.read(MANIFEST_NAME))
            assert set(doc["artifacts"]) == {"zh-src.zip", "dual.json"}
            assert "zh.pdf" not in zf.namelist()

        dest = tmp_path / "un"
        res2 = _RUNNER.invoke(app, ["share", "unpack", str(bundle), "-o", str(dest)])
        assert res2.exit_code == 0, res2.output
        mf = json.loads(res2.stdout)
        assert set(mf["artifacts"]) == {"zh-src.zip", "dual.json"}
        assert (dest / "dual.json").is_file()
        assert not (dest / "zh.pdf").exists()

    def test_pack_glossary_local_hashes(self, tmp_path: Path) -> None:
        """``base/glossary.local.yaml`` 在场 → glossary_hash 非空进键。"""
        tdir = _mk_task(tmp_path / "data")
        (tdir / "base").mkdir()
        (tdir / "base" / "glossary.local.yaml").write_text(
            "term: 译名\n", encoding="utf-8"
        )
        res = _pack(tdir, "-o", str(tmp_path / "o"))
        assert res.exit_code == 0, res.output
        assert json.loads(res.stdout)["key_parts"]["glossary_hash"] != ""

    def test_pack_glossary_config_missing_file_rejected(self, tmp_path: Path) -> None:
        """配置了 glossary 路径但文件已死 → 报错（不错标 ""）。"""
        tdir = _mk_task(
            tmp_path / "data", cfg={"glossary": str(tmp_path / "gone.yaml")}
        )
        res = _pack(tdir)
        assert res.exit_code == 1
        assert "glossary" in res.stderr


class TestShareUnpack:
    def _bundle(self, tmp_path: Path) -> Path:
        work = tmp_path / "w"
        work.mkdir()
        (work / "dual.json").write_text("{}", encoding="utf-8")
        (work / "zh.pdf").write_bytes(b"%PDF-1.4")
        with zipfile.ZipFile(work / "zh-src.zip", "w") as zf:
            zf.writestr("main.tex", _ZH_TEX)
        return pack_share(
            work,
            {
                "arxiv_id": "1706.03762",
                "version": "v5",
                "model": "m",
                "prompt_ver": PROMPT_VERSION,
                "target_lang": "zh-CN",
                "glossary_hash": "",
                "pipeline_ver": PIPELINE_VERSION,
            },
            out_dir=tmp_path,
        )

    def test_unpack_summary(self, tmp_path: Path) -> None:
        bundle = self._bundle(tmp_path)
        res = _RUNNER.invoke(
            app, ["share", "unpack", str(bundle), "-o", str(tmp_path / "d")]
        )
        assert res.exit_code == 0, res.output
        mf = json.loads(res.stdout)
        assert mf["format"] == "texlate-share/1"
        assert mf["key_parts"]["arxiv_id"] == "1706.03762"
        assert mf["contributor"].startswith("c-")

    def test_unpack_default_dest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无 ``-o`` → ``cwd/{包名去 .share.zip}``。"""
        bundle = self._bundle(tmp_path)
        monkeypatch.chdir(tmp_path)
        res = _RUNNER.invoke(app, ["share", "unpack", str(bundle)])
        assert res.exit_code == 0, res.output
        dest = tmp_path / bundle.name.removesuffix(".share.zip")
        assert (dest / "dual.json").is_file()

    def test_unpack_unsafe_bundle_name_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """包名剥出 ``..``/``.`` 等越界 stem → 回退 ``share-unpacked``，不外溢。"""
        bundle = self._bundle(tmp_path)
        evil = tmp_path / "...share.zip"  # removesuffix(".share.zip") → ".."
        bundle.rename(evil)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        res = _RUNNER.invoke(app, ["share", "unpack", str(evil)])
        assert res.exit_code == 0, res.output
        assert (cwd / "share-unpacked" / "dual.json").is_file()
        assert not (tmp_path / "dual.json").exists()  # 未写到父目录

    def test_unpack_rejects_non_zip(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.share.zip"
        bad.write_bytes(b"not a zip")
        res = _RUNNER.invoke(app, ["share", "unpack", str(bad)])
        assert res.exit_code == 1
        assert "not a readable" in res.stderr

    def test_unpack_rejects_no_manifest(self, tmp_path: Path) -> None:
        bad = tmp_path / "empty.share.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("dual.json", "{}")
        res = _RUNNER.invoke(app, ["share", "unpack", str(bad)])
        assert res.exit_code == 1
        assert "manifest.json" in res.stderr

    def test_unpack_rejects_tampered(self, tmp_path: Path) -> None:
        """manifest 被改（key_parts 与 share_key 不自洽）→ exit 1。"""
        bundle = self._bundle(tmp_path)
        with zipfile.ZipFile(bundle) as zf:
            doc = json.loads(zf.read(MANIFEST_NAME))
            payloads = {n: zf.read(n) for n in zf.namelist() if n != MANIFEST_NAME}
        parts = doc["key_parts"]
        assert isinstance(parts, dict)
        parts["model"] = "other-model"
        evil = tmp_path / "evil.share.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(doc))
            for n, blob in payloads.items():
                zf.writestr(n, blob)
        res = _RUNNER.invoke(app, ["share", "unpack", str(evil)])
        assert res.exit_code == 1
        assert "share_key" in res.stderr


class TestShareHelp:
    def test_share_help(self) -> None:
        res = _RUNNER.invoke(app, ["share", "--help"])
        assert res.exit_code == 0
        assert "pack" in res.output
        assert "unpack" in res.output

    def test_pack_help(self) -> None:
        res = _RUNNER.invoke(app, ["share", "pack", "--help"])
        assert res.exit_code == 0
        plain = _ANSI_RE.sub("", res.output)
        assert "--out" in plain
        assert "--data-dir" in plain

    def test_unpack_help(self) -> None:
        res = _RUNNER.invoke(app, ["share", "unpack", "--help"])
        assert res.exit_code == 0
        plain = _ANSI_RE.sub("", res.output)
        assert "--out" in plain
