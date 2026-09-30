"""server 旁路件审计补测：babeldoc 进程组杀/缓冲清理/错误窗、staticfiles 缓存头、
``__main__`` 参数闸、``compile/cjkmap`` cmap 装载路径（tmp 孤儿/间接引用/缺件）。

``run_babeldoc`` 进程组语义：babeldoc 会 fork multiprocessing 孙进程
（pdf_creater.py 字体子集化/clean-save）——timeout/cancel 必须 killpg
整组，否则孙进程成孤儿且占着 pty/pipe 写端把泵线程吊死。
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import time
from typing import TYPE_CHECKING

import pytest

from texlate.server import babeldoc as bd

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.testclient import TestClient

#: spawn 继承 stdout（pty slave/pipe 写端）的 sleep 孙进程后 hang——
#: 不杀组时孙进程孤儿化、泵线程读不到 EOF 卡满 wait_for(5s)。
_FAKE_GC = """\
import subprocess, sys, time
from pathlib import Path
argv = sys.argv[1:]
workdir = Path(argv[argv.index("--working-dir") + 1])
workdir.mkdir(parents=True, exist_ok=True)
gc = subprocess.Popen(["sleep", "30"])
(workdir / "gcpid").write_text(str(gc.pid))
print("translate 10/100", flush=True)
time.sleep(60)
"""


def _job(tmp_path: Path, timeout: float = 1.0) -> bd.BabeldocJob:
    return bd.BabeldocJob(
        src=tmp_path / "a.pdf",
        outdir=tmp_path / "out",
        workdir=tmp_path / "work",
        model="m",
        base_url="",
        timeout=timeout,
    )


def _write_fake_babeldoc(tmp_path: Path, body: str = _FAKE_GC) -> Path:
    """shebang + body 落 ``fake_babeldoc.py`` + 0755——可执行替身脚本。"""
    fake = tmp_path / "fake_babeldoc.py"
    fake.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def _assert_reaped(pid: int, label: str = "killpg") -> None:
    """轮询 ``os.kill(pid, 0)`` 至 ProcessLookupError——孤儿被 init 收割需一瞬。"""
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"grandchild {pid} survived {label}")


@pytest.mark.integration
class TestKillTree:
    """``_kill_tree`` + ``start_new_session``：孙进程随组灭，泵立即 EOF。"""

    @pytest.mark.skipif(sys.platform == "win32", reason="killpg/pty 是 POSIX 语义")
    def test_timeout_kills_process_group(self, tmp_path: Path) -> None:
        fake = _write_fake_babeldoc(tmp_path)
        t0 = time.monotonic()
        run = asyncio.run(bd.run_babeldoc(_job(tmp_path), binary=str(fake)))
        elapsed = time.monotonic() - t0
        assert run.status == "failed"
        assert run.error_code == "timeout"
        # 修复前：孙进程占着写端 → 泵卡满 5s wait_for → elapsed≈6s
        assert elapsed < 4.5  # noqa: PLR2004 -- 修复前阈值参照
        gcpid = tmp_path / "work" / "gcpid"
        assert gcpid.is_file()
        pid = int(gcpid.read_text(encoding="utf-8").strip())
        _assert_reaped(pid)

    def test_cancel_kills_process_group(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            pytest.skip("killpg/pty 是 POSIX 语义")
        fake = _write_fake_babeldoc(tmp_path)
        flag = {"cancel": False}

        async def go() -> None:
            async def trip() -> None:
                await asyncio.sleep(0.4)
                flag["cancel"] = True

            asyncio.get_running_loop().create_task(trip())
            with pytest.raises(asyncio.CancelledError):
                await bd.run_babeldoc(
                    _job(tmp_path, timeout=60),
                    binary=str(fake),
                    should_cancel=lambda: flag["cancel"],
                )

        asyncio.run(go())
        pid = int((tmp_path / "work" / "gcpid").read_text(encoding="utf-8").strip())
        _assert_reaped(pid, "cancel killpg")


class TestFeedBounds:
    """``_Feed.errors`` 有界——全篇报错时 O(n²) 去重不拖死 loop 线程。"""

    def test_errors_windowed(self) -> None:
        feed = bd._Feed()  # noqa: SLF001 -- 内部帧消费器直测
        for i in range(200):
            feed.feed(f"translate error: err-{i}\n".encode())
        feed.flush()
        assert len(feed.errors) == bd._MAX_ERRORS  # noqa: SLF001
        assert feed.errors[-1] == "err-199"  # keep-last：classify 取最新一条


class TestWriteConfig:
    """``write_config``：key 文件落盘即 0600（os.open mode，非 write+chmod 窗口）。"""

    def test_fresh_0600_under_permissive_umask(self, tmp_path: Path) -> None:
        job = bd.BabeldocJob(
            src=tmp_path / "a.pdf",
            outdir=tmp_path / "o",
            workdir=tmp_path / "w",
            model="m",
            base_url="",
            api_key="k-secret",
        )
        old = os.umask(0o022)
        try:
            p = bd.write_config(job)
        finally:
            os.umask(old)
        assert stat.S_IMODE(p.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
        assert 'openai-api-key = "k-secret"' in p.read_text(encoding="utf-8")


# ------------------------------------------------------------ SPA 静态服务


class TestSpaCacheHeaders:
    """``mount_spa`` 缓存策略：index no-cache / assets immutable / 稳定名默认。"""

    @pytest.fixture
    def spa_client(
        self, tmp_path: Path, clean_env: pytest.MonkeyPatch
    ) -> Iterator[TestClient]:
        from fastapi import FastAPI  # noqa: PLC0415
        from starlette.testclient import TestClient  # noqa: PLC0415

        from texlate.server.staticfiles import mount_spa  # noqa: PLC0415

        spa = tmp_path / "spa"
        (spa / "assets").mkdir(parents=True)
        (spa / "pdfjs").mkdir()
        (spa / "index.html").write_text("<html>spa</html>", encoding="utf-8")
        (spa / "assets" / "app-A1B2C3.js").write_text("x=1", encoding="utf-8")
        (spa / "pdfjs" / "x.bcmap").write_bytes(b"\x00")
        clean_env.setenv("TEXLATE_SPA_DIR", str(spa))
        app = FastAPI()
        assert mount_spa(app) is True
        with TestClient(app) as c:
            yield c

    def test_index_no_cache(self, spa_client: TestClient) -> None:
        r = spa_client.get("/")
        assert r.status_code == 200  # noqa: PLR2004
        assert r.headers["Cache-Control"] == "no-cache"

    def test_hashed_asset_immutable(self, spa_client: TestClient) -> None:
        r = spa_client.get("/assets/app-A1B2C3.js")
        assert r.status_code == 200  # noqa: PLR2004
        assert "immutable" in r.headers["Cache-Control"]

    def test_stable_name_default(self, spa_client: TestClient) -> None:
        """pdfjs bcmap 是稳定名资源——不贴 immutable（发版不吃旧缓存）。"""
        r = spa_client.get("/pdfjs/x.bcmap")
        assert r.status_code == 200  # noqa: PLR2004
        assert "Cache-Control" not in r.headers

    def test_traversal_still_404(self, spa_client: TestClient) -> None:
        r = spa_client.get("/../../pyproject.toml")
        assert r.status_code == 404  # noqa: PLR2004


# ------------------------------------------------------------ __main__ 入口


class TestMainEntry:
    """``python -m texlate.server``：端口范围闸 + 参数透传。"""

    def _run_main(
        self, monkeypatch: pytest.MonkeyPatch, argv: list[str]
    ) -> dict[str, object]:
        import uvicorn  # noqa: PLC0415

        import texlate.server.__main__ as m  # noqa: PLC0415
        import texlate.server.app as app_mod  # noqa: PLC0415

        calls: dict[str, object] = {}
        monkeypatch.setattr(app_mod, "create_app", object)
        monkeypatch.setattr(
            uvicorn,
            "run",
            lambda app, host, port: calls.update(
                {"app": app, "host": host, "port": port}
            ),
        )
        monkeypatch.setattr(sys, "argv", argv)
        m.main()
        return calls

    def test_valid_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._run_main(
            monkeypatch,
            ["texlate.server", "--host", "0.0.0.0", "--port", "9000"],  # noqa: S104
        )
        assert calls["host"] == "0.0.0.0"  # noqa: S104 -- 仅断言透传非真绑定
        assert calls["port"] == 9000  # noqa: PLR2004

    def test_port_out_of_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import texlate.server.__main__ as m  # noqa: PLC0415

        monkeypatch.setattr(sys, "argv", ["texlate.server", "--port", "70000"])
        with pytest.raises(SystemExit) as ei:
            m.main()
        assert ei.value.code == 2  # noqa: PLR2004 -- argparse error 退出码

    def test_data_dir_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("TEXLATE_DATA_DIR", raising=False)
        self._run_main(
            monkeypatch, ["texlate.server", "--data-dir", str(tmp_path / "d")]
        )
        assert os.environ["TEXLATE_DATA_DIR"] == str(tmp_path / "d")


# ------------------------------------------------------------ cjkmap cmap 装载


class TestCjkmapResource:
    """``compile/cjkmap`` cmap 装载路径：缺件/间接引用/tmp 孤儿。"""

    def _gb1_pdf(self, tmp_path: Path, *, indirect_sysinfo: bool = False) -> Path:
        from pypdf import PdfWriter  # noqa: PLC0415
        from pypdf.generic import (  # noqa: PLC0415
            ArrayObject,
            DictionaryObject,
            NameObject,
            NumberObject,
            TextStringObject,
        )

        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        page = w.pages[0]
        cid_sys = DictionaryObject(
            {
                NameObject("/Registry"): TextStringObject("Adobe"),
                NameObject("/Ordering"): TextStringObject("GB1"),
                NameObject("/Supplement"): NumberObject(5),
            }
        )
        cid_font = w._add_object(  # noqa: SLF001
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/CIDFontType0"),
                    NameObject("/BaseFont"): NameObject("/FandolSong-Regular"),
                    NameObject("/CIDSystemInfo"): (
                        w._add_object(cid_sys) if indirect_sysinfo else cid_sys  # noqa: SLF001
                    ),
                }
            )
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F5"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type0"),
                                NameObject("/Encoding"): NameObject("/Identity-H"),
                                NameObject("/DescendantFonts"): ArrayObject([cid_font]),
                            }
                        )
                    }
                )
            }
        )
        out = tmp_path / "probe.pdf"
        with out.open("wb") as fh:
            w.write(fh)
        w.close()
        return out

    def test_indirect_cidsysteminfo(self, tmp_path: Path) -> None:
        """CIDSystemInfo 间接引用（babeldoc/外部 PDF 可产）——照样注入。"""
        from texlate.compile.cjkmap import embed_cjk_mappings  # noqa: PLC0415

        pdf = self._gb1_pdf(tmp_path, indirect_sysinfo=True)
        assert embed_cjk_mappings(pdf) == 1

    def test_missing_cmap_raises_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cmap 数据件缺席 → 抛错（调用方 best-effort 壳记 log），原 pdf 不动。"""
        from texlate.compile import cjkmap  # noqa: PLC0415

        pdf = self._gb1_pdf(tmp_path)
        before = pdf.read_bytes()
        monkeypatch.setattr(
            cjkmap, "_GB1_UCS2_CMAP", tmp_path / "nope" / "Adobe-GB1-UCS2"
        )
        with pytest.raises(FileNotFoundError):
            cjkmap.embed_cjk_mappings(pdf)
        assert pdf.read_bytes() == before
        assert not list(tmp_path.glob("*.mapped.pdf"))

    def test_write_failure_no_tmp_orphan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``writer.write`` 翻车 → 半截 ``*.mapped.pdf`` 不留孤儿。"""
        from pypdf import PdfWriter  # noqa: PLC0415

        from texlate.compile import cjkmap  # noqa: PLC0415

        pdf = self._gb1_pdf(tmp_path)
        before = pdf.read_bytes()

        err = OSError("disk full")

        def boom(self: object, stream: object) -> None:  # noqa: ARG001
            raise err

        monkeypatch.setattr(PdfWriter, "write", boom)
        with pytest.raises(OSError, match="disk full"):
            cjkmap.embed_cjk_mappings(pdf)
        assert not list(tmp_path.glob("*.mapped.pdf"))
        assert pdf.read_bytes() == before
