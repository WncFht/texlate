"""cli.py 对抗输入 fuzz——任何输入只许干净退出（exit 0/1/2 + 简明 stderr），永不 traceback。

核心不变量（clean-exit oracle）：``result.exception is None or
isinstance(result.exception, SystemExit)``——CliRunner 对 ``typer.Exit``/用法错
返回 ``SystemExit``；出现真实异常类即 traceback 逃逸。再加 ``"Traceback" not in
result.output`` 兜底。

全离线：arXiv 取源面一律 ``--offline`` + ``cli.Fetcher`` 换 tripwire（任何
head/get 调用即 fail——证明 id 前置校验拦住、网络零接触）；``run --server``
瘦客户端走 ``httpx.MockTransport``；``run`` 本地管线 stub
``mock_pipeline_run`` 避开真引擎；``tools install-tectonic`` 打桩
``install_tectonic`` 防真下载。

攻击面：畸形 arXiv id（新旧式/unicode/``..``/超长/空/NUL/随机汤）、Path
参数（NUL/ENAMETOOLONG/``..``/文件当目录/不存在）、``TEXLATE_*`` env 对抗值、
选项冲突/缺参/坏枚举、全子命令 ``--help``、瘦客户端未校验 id 提交、share
pack ``tasks/`` 越狱。曾钉缺陷（NUL Path 转换/ENAMETOOLONG 穿透探针/
export 父链 OSError/TRANSLATOR typo 静默忽略/doctor InvalidURL）已修复，
全数转回归断言。
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import httpx
import pytest
from _fuzzkit import fuzz_rng
from conftest import FakeFetcher, make_targz, mk_task_dir
from typer.testing import CliRunner, Result

from texlate import cli
from texlate.cli import app
from texlate.compile import toolchain
from texlate.xlat.glossary import LOCAL_GLOSSARY_NAME

if TYPE_CHECKING:
    from collections.abc import Callable

_RUNNER = CliRunner()
#: 随机汤发生器固定种子——失败可复现。
_SEED = 0xC11F
#: 超 NAME_MAX 的单路径段——触发 ENAMETOOLONG（``Path.is_dir`` 只吞
#: ENOENT/ENOTDIR 一族，ENAMETOOLONG/EACCES 会再抛）。
_LONG_COMP = "a" * 300
#: POSIX NAME_MAX——单路径段字节数上限，超出即 ENAMETOOLONG。
_NAME_MAX = 255

_MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph of English text long enough to produce a translation chunk.\n"
    "\\end{document}\n"
)

_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="b">t</dc:identifier><dc:title>t</dc:title><dc:language>en</dc:language>
  </metadata>
  <manifest><item id="c0" href="c0.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c0"/></spine>
</package>
"""

_XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
    "<body><p>Hello world paragraph for export.</p></body></html>"
)


def _clean(result: Result) -> None:
    """干净退出 oracle：无真实异常逃逸、输出无 Traceback 字样。"""
    exc = result.exception
    assert exc is None or isinstance(exc, SystemExit)
    assert "Traceback" not in result.output


def _epub_blob() -> bytes:
    """最小合法 EPUB zip（mimetype + container + OPF + 一章）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER_XML)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/c0.xhtml", _XHTML)
    return buf.getvalue()


class _TripwireFetcher:
    """取源层绊线：任何 head/get 调用即 fail——证明校验/离线闸在网络前生效。"""

    def __init__(self) -> None:
        self.called = False

    def head_src(self, *_args: object, **_kw: object) -> object:
        self.called = True
        pytest.fail("offline/invalid-id 路径触网: head_src")

    def get_src(self, *_args: object, **_kw: object) -> object:
        self.called = True
        pytest.fail("offline/invalid-id 路径触网: get_src")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> _TripwireFetcher:
    """``cli.Fetcher`` 换 tripwire CM——``_acquire`` 的 ``with Fetcher()`` 兼容。"""

    tw = _TripwireFetcher()

    class _CM:
        def __enter__(self) -> _TripwireFetcher:
            return tw

        def __exit__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr(cli, "Fetcher", _CM)
    return tw


@pytest.fixture
def pipeline_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run`` 本地管线 stub——不触真引擎，只验证 CLI 侧分流/退出码。"""

    monkeypatch.setattr(
        cli, "mock_pipeline_run", lambda *_args, **_kw: {"status": "clean"}
    )


def _src_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(_MAIN_TEX, encoding="utf-8")
    return src


#: ``mk_task_dir``（conftest 公共件）的本文件产物集——share pack 只强制
#: dual.json，zh-src.zip 是 unpack golden 的断言行（test_cli.py 同款
#: 调用落 zh.pdf，仅这张表不同）。
_TASK_FILES: dict[str, str | bytes] = {
    "dual.json": "{}",
    "zh-src.zip": b"fake-src",
}


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[str]:
    """``httpx.Client`` 换 ``MockTransport`` 背板——返回请求路径流水供断言。"""
    calls: list[str] = []

    def _h(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return handler(request)

    real = httpx.Client

    def _factory(*a: object, **kw: object) -> httpx.Client:
        kw["transport"] = httpx.MockTransport(_h)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "Client", _factory)
    return calls


# ---------------------------------------------------------------- arXiv id fuzz


class TestArxivIdFuzz:
    """``fetch``/``run`` 的 id 参数：非法形态 → ``bad_id``/``bad_version``，
    合法形态离线无缓存 → ``offline_no_cache``——全 exit 1、零网络、零 traceback。"""

    _IDS: ClassVar[list[str]] = [
        # 空/空白/控制字符
        "",
        "   ",
        "\t\n",
        "a\x00b",
        "2001.00001\x00v2",
        # 遍历/注入形
        "x/../../y",
        "../..",
        "..",
        "2001.00001/../2002.00002",
        "2001.00001/extra",
        "a b",
        "a%20b",
        "%2e%2e/x",
        "@",
        ":",
        # 新式 id 边界
        "2001.00001",
        "2001.00001v3",
        "2001.00001v0",
        "2001.00001v-1",
        "2001.00001vabc",
        "2001.00001v9999",
        "2001.00001v",
        "2001.00001.V2",
        "99999.99999",
        "2001.000001",
        "2001.1",
        # 旧式 id
        "hep-th/9901001",
        "math.GT/0309136",
        "hep-th/",
        "/9901001",
        "hep-th/990100",
        # URL/prefix 形态
        "https://arxiv.org/abs/2001.00001",
        "http://arxiv.org/pdf/2001.00001v2.pdf",
        "arxiv.org/abs/2001.00001",
        "ftp://arxiv.org/abs/2001.00001",
        "arXiv:2001.00001",
        "arxiv:",
        "http://arxiv.org/abs/",
        "2001.00001?x=1",
        "2001.00001#frag",
        # unicode / 超长
        "论文.测试",
        "üñíçödé",
        "ｆｕｌｌｗｉｄｔｈ",
        "9" * 300,
        "a" * 1000,
        "é" * 200,
    ]

    @pytest.mark.parametrize("arxiv_id", _IDS)
    def test_fetch_id_shapes_offline(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
        arxiv_id: str,
    ) -> None:
        result = _RUNNER.invoke(
            app, ["fetch", arxiv_id, "--offline", "--cache", str(tmp_path)]
        )
        _clean(result)
        assert result.exit_code == 1
        body = json.loads(result.stdout)
        assert body["status"] == "error"
        assert re.match(r"^(bad_id|bad_version|offline_no_cache)", body["detail"])

    @pytest.mark.parametrize(
        "arxiv_id",
        # '..'/'../..' 在 cwd 解析成真目录 → 走 dir-source 臂；超 NAME_MAX 单段
        # （'é'*200 = 400B UTF-8）让 run 的 is_dir 前置检查 ENAMETOOLONG
        # traceback——D6 同根因已由 TestEnametoolong 钉，run 侧剔除
        [
            i
            for i in _IDS
            if i not in ("..", "../..")
            and all(len(os.fsencode(seg)) < _NAME_MAX for seg in i.split("/"))
        ],
    )
    def test_run_id_shapes_offline(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
        arxiv_id: str,
    ) -> None:
        result = _RUNNER.invoke(
            app, ["run", arxiv_id, "--offline", "--cache", str(tmp_path)]
        )
        _clean(result)
        # 空/空白被 run 自己的 source 闸拒（exit 2）；其余走取源拒收（exit 1）
        if not arxiv_id.strip():
            assert result.exit_code == 2  # noqa: PLR2004 -- 空源 usage 错
        else:
            assert result.exit_code == 1
            body = json.loads(result.stdout)
            assert re.match(r"^(bad_id|bad_version|offline_no_cache)", body["detail"])

    def test_random_id_soup(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
    ) -> None:
        """种子随机汤：id 字符域内任意拼接 → 干净拒收，从不触网不 traceback。"""
        rng = fuzz_rng(_SEED)
        alphabet = "0123456789.vV/abcxyz-_.:?#\t\x00éü字"
        for _ in range(250):
            arxiv_id = "".join(rng.choice(alphabet) for _ in range(rng.randrange(40)))
            # '-' 开头的串会被当选项 → ``--`` 分隔符保证落进 positional
            result = _RUNNER.invoke(
                app,
                ["fetch", "--offline", "--cache", str(tmp_path), "--", arxiv_id],
            )
            _clean(result)
            assert result.exit_code == 1
            body = json.loads(result.stdout)
            assert re.match(r"^(bad_id|bad_version|offline_no_cache)", body["detail"])

    def test_valid_id_offline_no_cache(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
    ) -> None:
        """合法 id 离线空缓存 → ``offline_no_cache`` exit 1（不降级联网）。"""
        result = _RUNNER.invoke(
            app, ["fetch", "2001.00001", "--offline", "--cache", str(tmp_path)]
        )
        _clean(result)
        assert result.exit_code == 1
        assert "offline_no_cache" in json.loads(result.stdout)["detail"]

    @pytest.mark.parametrize("version", ["0", "-1", "abc", "1.5"])
    def test_version_flag_rejects(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
        version: str,
    ) -> None:
        result = _RUNNER.invoke(
            app,
            [
                "fetch",
                "2001.00001",
                "--offline",
                "--version",
                version,
                "--cache",
                str(tmp_path),
            ],
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- click IntRange/类型拒绝

    def test_version_flag_huge(
        self,
        tmp_path: Path,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
    ) -> None:
        """``--version`` 巨大整数：通过 min=1 → 钉版离线无缓存 → exit 1 干净。"""
        result = _RUNNER.invoke(
            app,
            [
                "fetch",
                "2001.00001",
                "--offline",
                "--version",
                "99999999999",
                "--cache",
                str(tmp_path),
            ],
        )
        _clean(result)
        assert result.exit_code == 1


# ---------------------------------------------------------------- NUL / ENAMETOOLONG Path 参数


class TestNulPathParam:
    """NUL 字节进任何 Path 型参数 → 干净 usage 拒收（exit 2）。

    回归钉：typer ``TyperPath.convert`` 的 ``os.stat`` 只捕 ``OSError``——
    ``stat: embedded null character`` 是 ``ValueError``，曾全谱 traceback；
    现由 cli ``_CliPath`` 参数型在 ``os.stat`` 前置拒控制字符。
    """

    _ARGV: ClassVar[list[list[str]]] = [
        ["parse", "a\x00b.tex"],
        ["parse", "{TEX}", "-o", "a\x00b"],
        ["export", "a\x00b.epub", "--mock"],
        ["export", "{EPUB}", "-o", "a\x00b", "--mock"],
        ["export", "{EPUB}", "--glossary", "a\x00b", "--mock"],
        ["share", "unpack", "a\x00b.zip"],
        ["share", "unpack", "{TEX}", "-o", "a\x00b"],
        ["share", "pack", "t_x", "-o", "a\x00b"],
        ["share", "pack", "t_x", "--data-dir", "a\x00b"],
        ["run", "x", "--work-dir", "a\x00b"],
        ["run", "x", "--cache", "a\x00b", "--offline"],
        ["run", "x", "--server", "http://s", "-o", "a\x00b"],
        ["fetch", "x", "--cache", "a\x00b", "--offline"],
        ["web", "--data-dir", "a\x00b"],
    ]

    @pytest.mark.parametrize("argv", _ARGV)
    def test_nul_path_param(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        argv: list[str],
    ) -> None:
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        argv = [a.replace("{TEX}", str(tex)).replace("{EPUB}", str(epub)) for a in argv]
        result = _RUNNER.invoke(app, argv)
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- 期望 usage 拒收

    @pytest.mark.parametrize(
        "argv",
        [
            # str 参数 Path.is_dir 吞 ValueError → bad_id
            ["run", "a\x00b", "--offline", "--cache", "{TMP}"],
            # str 参数同上 → 非 t_ 前缀干净拒
            ["share", "pack", "a\x00b", "--data-dir", "{TMP}"],
            # str 参数 → bad_id
            ["fetch", "a\x00b", "--offline", "--cache", "{TMP}"],
        ],
    )
    def test_nul_str_param_clean(self, tmp_path: Path, argv: list[str]) -> None:
        """对照组：``str`` 型参数遇 NUL 已干净拒收——缺陷只在 Path 型转换层。"""
        argv = [a.replace("{TMP}", str(tmp_path)) for a in argv]
        result = _RUNNER.invoke(app, argv)
        _clean(result)
        assert result.exit_code == 1


class TestEnametoolong:
    """超 NAME_MAX 段/权限拒绝 → ``OSError`` 不穿透 ``is_dir``/glob 探针。

    回归钉：``Path.is_dir()`` 只吞 ENOENT/ENOTDIR 一族——ENAMETOOLONG、
    EACCES 再抛曾逃逸成 traceback；现由 cli ``_is_dir``/``_is_file`` 宽判
    + ``_acquire`` OSError 收口归一干净 exit 1/2。
    """

    _ARGV: ClassVar[list[list[str]]] = [
        ["run", _LONG_COMP, "--offline"],  # cli.py:385 _resolve_source is_dir
        ["run", _LONG_COMP, "--server", "http://s"],  # cli.py:417 瘦客户端 is_dir
        ["share", "pack", _LONG_COMP],  # cli.py:844 _share_task_dir is_dir
        [
            "fetch",
            "2001.00001",
            "--offline",
            "--cache",
            _LONG_COMP,
        ],  # cache glob is_dir
        ["run", "2001.00001", "--offline", "--cache", _LONG_COMP],  # 同上
    ]

    @pytest.mark.parametrize("argv", _ARGV)
    def test_enametoolong_path(
        self,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
        argv: list[str],
    ) -> None:
        result = _RUNNER.invoke(app, argv)
        _clean(result)
        assert result.exit_code in (1, 2)

    def test_locked_parent_dir(self, tmp_path: Path) -> None:
        """``EACCES`` 同族：父目录 000 时 ``stat`` 再抛 → 干净拒收。"""
        if os.geteuid() == 0:
            pytest.skip("root 下 chmod 0 不产生 EACCES")
        locked = tmp_path / "locked"
        locked.mkdir()
        (locked / "sub").mkdir()
        locked.chmod(0)
        try:
            result = _RUNNER.invoke(app, ["run", str(locked / "sub"), "--offline"])
        finally:
            locked.chmod(0o755)
        _clean(result)
        assert result.exit_code in (1, 2)


# ---------------------------------------------------------------- run 参数面


class TestRunValidation:
    """``run`` 选项校验：非有限秒数/空源/引擎白名单/``--server`` 专属选项脱离。"""

    @pytest.mark.parametrize("val", ["nan", "inf", "-inf", "NaN", "1e999"])
    def test_timeout_nonfinite(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
        val: str,
    ) -> None:
        """``--timeout`` 非有限值 → exit 2（typer min=0.0 拦不住 nan——显式闸）。"""
        result = _RUNNER.invoke(app, ["run", str(_src_dir(tmp_path)), "--timeout", val])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize("val", ["nan", "inf", "-inf"])
    def test_wait_nonfinite(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        """``--wait nan`` 曾让 deadline 永不触发 = 无界轮询——显式闸 exit 2。"""
        _patch_httpx(monkeypatch, lambda _r: httpx.Response(404, json={}))
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--server", "http://s", "--wait", val]
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize("val", ["0", "-0.0"])
    def test_timeout_zero_boundary(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
        val: str,
    ) -> None:
        """0/-0.0 是有限值——放行进管线（mock → exit 0）。"""
        result = _RUNNER.invoke(app, ["run", str(_src_dir(tmp_path)), "--timeout", val])
        _clean(result)
        assert result.exit_code == 0

    @pytest.mark.parametrize("source", ["", "   ", "\t\n"])
    def test_empty_source(self, source: str) -> None:
        result = _RUNNER.invoke(app, ["run", source, "--offline"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize("engine", ["pdftex", "", "AUTO", "XeLaTeX", "a\x00b"])
    def test_engine_whitelist(self, tmp_path: Path, engine: str) -> None:
        result = _RUNNER.invoke(
            app, ["run", str(_src_dir(tmp_path)), "--engine", engine]
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize(
        "opt",
        [
            ["--model", "m"],
            ["--api-key", "k"],
            ["--base-url", "u"],
            ["--out", "o"],
            ["--wait", "5"],
        ],
    )
    def test_server_only_opts(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
        opt: list[str],
    ) -> None:
        """``--model/--api-key/--base-url/--out/--wait`` 脱离 ``--server`` → exit 2。"""
        result = _RUNNER.invoke(app, ["run", str(_src_dir(tmp_path)), *opt])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_work_dir_is_file(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
    ) -> None:
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app, ["run", str(_src_dir(tmp_path)), "--work-dir", str(blocker)]
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_work_dir_resolved_nonempty(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
    ) -> None:
        """``--work-dir p/sub/..`` 内核解析 = 已存在非空 → 拒绝 exit 2（不 rmtree）。"""
        target = tmp_path / "wd"
        (target / "sub").mkdir(parents=True)
        (target / "f").write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app,
            ["run", str(_src_dir(tmp_path)), "--work-dir", str(target / "sub" / "..")],
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_work_dir_under_file(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
    ) -> None:
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app,
            ["run", str(_src_dir(tmp_path)), "--work-dir", str(blocker / "x")],
        )
        _clean(result)
        assert result.exit_code == 1  # OSError 归一 exit 1

    def test_file_as_source(self, tmp_path: Path) -> None:
        """已存在文件当 source：非目录 → 按 arXiv id 走 → bad_id exit 1。"""
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        result = _RUNNER.invoke(app, ["run", str(tex), "--offline"])
        _clean(result)
        assert result.exit_code == 1

    def test_dir_source_golden(
        self,
        tmp_path: Path,
        pipeline_stub: None,  # noqa: ARG002 -- fixture 副作用（管线打桩）
    ) -> None:
        """本地工程目录 + stub 管线 → exit 0（CLI 分流 golden path）。"""
        result = _RUNNER.invoke(app, ["run", str(_src_dir(tmp_path))])
        _clean(result)
        assert result.exit_code == 0

    def test_dash_dash_separator(self) -> None:
        """``--`` 分隔符后 ``-weird`` 落 positional → bad_id exit 1 非用法错。"""
        result = _RUNNER.invoke(app, ["fetch", "--", "-weird", "--offline"])
        _clean(result)
        assert result.exit_code in (1, 2)


# ---------------------------------------------------------------- run --server 瘦客户端


class TestThinClient:
    """瘦客户端对抗面：id 未校验提交 / 恶意 server 响应 / 畸形 server URL。"""

    _TASK = "t_thinfuzz"

    @pytest.fixture(autouse=True)
    def _cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认 ``--out`` 落 ``Path.cwd()``——钉进 tmp 防仓库根目录残渣。"""
        monkeypatch.chdir(tmp_path)

    def _handler_terminal(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("/translate"):
            return httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
        if p == f"/api/task/{self._TASK}":
            return httpx.Response(
                200,
                json={
                    "status": "done",
                    "stage": "compile",
                    "progress": 100,
                    "counters": {},
                },
            )
        if p == f"/api/files/{self._TASK}":
            return httpx.Response(200, json={"artifacts": {}})
        return httpx.Response(404)

    @pytest.mark.parametrize(
        "source",
        [
            "x/../../y",  # httpx 规范化 → /api/y/translate——逃出 arxiv 命名空间
            "2001.00001/extra",  # → /api/arxiv/2001.00001/extra/translate 畸形段
            "a b",  # 空格入 path
            "%2e%2e/x",  # 编码点段
            "x/../y",
            "not-an-id",
        ],
    )
    def test_unvalidated_id_submission(
        self, monkeypatch: pytest.MonkeyPatch, source: str
    ) -> None:
        """回归钉（8a3d822 已修）：``valid_id`` 闸在构造 URL 前拒非法 id。

        旧缺陷：``..`` 借 httpx dot-segment 归一化逃出 ``/api/arxiv/``
        命名空间落 ``/api/y/translate``。现行：本地 exit 2 零请求。
        """
        calls = _patch_httpx(monkeypatch, self._handler_terminal)
        result = _RUNNER.invoke(app, ["run", source, "--server", "http://s"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004
        assert not calls, f"非法 id 不得发出请求: {calls!r}"

    def test_valid_id_baseline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """合法 id：``POST /api/arxiv/2001.00001v2/translate`` + done → exit 0。"""
        calls = _patch_httpx(monkeypatch, self._handler_terminal)
        result = _RUNNER.invoke(app, ["run", "2001.00001v2", "--server", "http://s"])
        _clean(result)
        assert result.exit_code == 0
        assert calls[0] == "POST /api/arxiv/2001.00001v2/translate"

    @pytest.mark.parametrize("server", ["::::", "", "not a url", "http://"])
    def test_malformed_server_url(
        self, monkeypatch: pytest.MonkeyPatch, server: str
    ) -> None:
        """``--server`` 畸形 URL → InvalidURL/构造错归一 exit 2，不 traceback。

        MockTransport 会放行无 scheme/host 的畸形 URL（真实 transport 在发包
        前就 raise UnsupportedProtocol/ConnectError），故 handler 内补同样的闸。
        """

        def handler(req: httpx.Request) -> httpx.Response:
            if not req.url.scheme or not req.url.host:
                msg = "missing scheme/host"
                raise httpx.UnsupportedProtocol(msg)
            return self._handler_terminal(req)

        _patch_httpx(monkeypatch, handler)
        result = _RUNNER.invoke(app, ["run", "2001.00001", "--server", server])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_server_plus_local_dir(self, tmp_path: Path) -> None:
        """本地目录喂 ``--server`` → exit 2 显式拒。"""
        result = _RUNNER.invoke(
            app, ["run", str(_src_dir(tmp_path)), "--server", "http://s"]
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_non_json_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """提交返回 200 + 非 JSON body → JSONDecodeError 归一 exit 2。"""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/translate"):
                return httpx.Response(200, content=b"<html>nope")
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        result = _RUNNER.invoke(app, ["run", "2001.00001", "--server", "http://s"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_snapshot_non_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照返回 JSON 数组 → 「快照非法」exit 1 干净。"""

        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(200, json=[1, 2])
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--server", "http://s", "--wait", "1"]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_wait_zero_no_hang(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``--wait 0`` + 非终态快照 → 立即超时 exit 1（无界轮询不成立）。"""

        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "queued",
                        "stage": "x",
                        "progress": 1,
                        "counters": {},
                    },
                )
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--server", "http://s", "--wait", "0"]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_artifact_traversal_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """恶意 server 产物表：``..``/绝对 URL 成员名 → 跳过不落地，exit 0。"""

        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "done",
                        "stage": "x",
                        "progress": 100,
                        "counters": {},
                    },
                )
            if p == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "zh.pdf": {"url": "/api/files/../..", "sha256": "x"},
                            "dual.json": {"url": "/etc/passwd", "sha256": "x"},
                        }
                    },
                )
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        out = tmp_path / "dl"
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--server", "http://s", "--out", str(out)]
        )
        _clean(result)
        assert result.exit_code == 0
        # 全部产物被跳过/下载失败 → out 为空（或无正名件落地）
        assert not out.exists() or not list(out.iterdir())

    def test_artifact_bad_sha_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物 sha256 与声明不符 → ``.part`` 不落正名，exit 0。"""

        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "done",
                        "stage": "x",
                        "progress": 100,
                        "counters": {},
                    },
                )
            if p == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "zh.pdf": {
                                "url": f"/api/files/{self._TASK}/zh.pdf",
                                "sha256": "0" * 64,
                            }
                        }
                    },
                )
            if p == f"/api/files/{self._TASK}/zh.pdf":
                return httpx.Response(200, content=b"%PDF-real")
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        out = tmp_path / "dl"
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--server", "http://s", "--out", str(out)]
        )
        _clean(result)
        assert result.exit_code == 0
        assert not (out / "zh.pdf").exists()

    def test_attach_409(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """409 duplicate_active → attach 复用 task_id → 终态 done exit 0。"""

        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(409, json={"task_id": self._TASK})
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "done",
                        "stage": "x",
                        "progress": 100,
                        "counters": {},
                    },
                )
            if p == f"/api/files/{self._TASK}":
                return httpx.Response(200, json={"artifacts": {}})
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        result = _RUNNER.invoke(app, ["run", "2001.00001", "--server", "http://s"])
        _clean(result)
        assert result.exit_code == 0


# ---------------------------------------------------------------- parse


class TestParse:
    """``parse`` 路径/输出参数边界——全部干净拒收或成功，无 traceback。"""

    def test_missing_arg(self) -> None:
        result = _RUNNER.invoke(app, ["parse"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_nonexistent(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(app, ["parse", str(tmp_path / "nope.tex")])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- click exists=True 拒

    def test_dir_arg(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(app, ["parse", str(tmp_path)])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- dir_okay=False

    def test_out_existing_dir(self, tmp_path: Path) -> None:
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        result = _RUNNER.invoke(app, ["parse", str(tex), "-o", str(tmp_path)])
        _clean(result)
        assert result.exit_code == 1  # 目录不可写当文件 → OSError 归一

    def test_out_under_file(self, tmp_path: Path) -> None:
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app, ["parse", str(tex), "-o", str(blocker / "o.jsonl")]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_out_same_as_input(self, tmp_path: Path) -> None:
        """``-o`` 与输入同路径 → exit 2 显式拒（不覆写源文件）。"""
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        result = _RUNNER.invoke(app, ["parse", str(tex), "-o", str(tex)])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_out_dotdot_normalized(self, tmp_path: Path) -> None:
        """``-o`` 含 ``..``：内核归一化后落盘 → exit 0。"""
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        out = tmp_path / "sub" / ".." / "o.jsonl"
        result = _RUNNER.invoke(app, ["parse", str(tex), "-o", str(out)])
        _clean(result)
        assert result.exit_code == 0
        assert (tmp_path / "o.jsonl").is_file()

    def test_out_symlink_loop(self, tmp_path: Path) -> None:
        """``-o`` 是 symlink loop：resolve RuntimeError → 按不同径放行，
        ``--out 不可写`` OSError 归一 exit 1（回归钉：曾 traceback）。"""
        tex = tmp_path / "m.tex"
        tex.write_text(_MAIN_TEX, encoding="utf-8")
        loop = tmp_path / "loop"
        loop.symlink_to("loop")
        result = _RUNNER.invoke(app, ["parse", str(tex), "-o", str(loop)])
        _clean(result)
        assert result.exit_code == 1
        assert "--out 不可写" in result.stderr

    def test_binary_file(self, tmp_path: Path) -> None:
        """非 UTF-8 内容：recode 容错解析 → exit 0（warnings 允许）。"""
        blob = tmp_path / "bin.tex"
        blob.write_bytes(b"\x00\x01\x02\xff\xfe" * 100)
        result = _RUNNER.invoke(app, ["parse", str(blob)])
        _clean(result)
        assert result.exit_code == 0
        assert json.loads(result.stdout)["path"].endswith("bin.tex")


# ---------------------------------------------------------------- export


class TestExport:
    """``export`` 输入/选项边界 + ``TEXLATE_*`` 路由 env。"""

    def test_missing_arg(self) -> None:
        result = _RUNNER.invoke(app, ["export"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize("kind", ["dir", "nonexistent", "notazip"])
    def test_bad_input(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        kind: str,
    ) -> None:
        """目录/不存在/非导出 zip → ``export:`` 前缀错 exit 1。"""
        if kind == "dir":
            arg = tmp_path
        elif kind == "nonexistent":
            arg = tmp_path / "nope.epub"
        else:
            arg = tmp_path / "b.epub"
            arg.write_bytes(b"PK-notreally")
        result = _RUNNER.invoke(app, ["export", str(arg), "--mock"])
        _clean(result)
        assert result.exit_code == 1
        assert "export:" in result.stderr

    def test_glossary_dir(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(
            app, ["export", str(epub), "--glossary", str(tmp_path), "--mock"]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_glossary_missing(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(
            app,
            ["export", str(epub), "--glossary", str(tmp_path / "g.yaml"), "--mock"],
        )
        _clean(result)
        assert result.exit_code == 1

    def test_out_under_file(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        """``-o`` 落在已存在文件之下 → NotADirectoryError 归一 ``export:`` exit 1。"""
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app, ["export", str(epub), "-o", str(blocker / "x.epub"), "--mock"]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_mock_wins_over_api_key(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--mock`` + ``TEXLATE_API_KEY`` 同设 → Mock 优先（不触网关）。"""
        monkeypatch.setenv("TEXLATE_API_KEY", "sk-fuzz")
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(app, ["export", str(epub), "--mock"])
        _clean(result)
        assert result.exit_code == 0

    def test_translator_env_bogus_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_TRANSLATOR=<未知值>`` → 显式拒收（exit 2）。

        回归钉：曾被静默忽略按 auto/Mock 回落——拼错的强制指令被吞掉，
        用户以为在走网关实际拿了占位译文。
        """
        monkeypatch.setenv("TEXLATE_TRANSLATOR", "gatewy")  # 拼错形
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(app, ["export", str(epub)])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- 期望显式拒未知枚举值

    def test_translator_gateway_no_key(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_TRANSLATOR=gateway`` 无 key → exit 2 显式拒（对照组）。"""
        monkeypatch.setenv("TEXLATE_TRANSLATOR", "gateway")
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(app, ["export", str(epub)])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_epub_golden_mock(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        """最小合法 EPUB + ``--mock`` → exit 0 产 ``{stem}_bilingual.epub``。"""
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())
        result = _RUNNER.invoke(app, ["export", str(epub), "--mock"])
        _clean(result)
        assert result.exit_code == 0
        assert (tmp_path / "b_bilingual.epub").is_file()


# ---------------------------------------------------------------- share


class TestShare:
    """``share pack``/``unpack`` 参数面 + ``tasks/`` 越狱防护。"""

    def test_bare_share(self) -> None:
        result = _RUNNER.invoke(app, ["share"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- no_args_is_help

    def test_pack_non_t_non_dir(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            app, ["share", "pack", "zzz", "--data-dir", str(tmp_path)]
        )
        _clean(result)
        assert result.exit_code == 1

    def test_pack_ghost_task(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            app, ["share", "pack", "t_ghost", "--data-dir", str(tmp_path)]
        )
        _clean(result)
        assert result.exit_code == 1
        assert "任务目录不存在" in result.stderr

    def test_pack_empty_arg(self, tmp_path: Path) -> None:
        """``""`` → ``Path("")`` = cwd 已存在目录 → 找库失败 exit 1 干净。"""
        result = _RUNNER.invoke(app, ["share", "pack", "", "--data-dir", str(tmp_path)])
        _clean(result)
        assert result.exit_code == 1

    def test_pack_traversal_jailed(self, tmp_path: Path) -> None:
        """``t_x/../../victim`` 借 ``is_dir`` 解析穿仓——resolve 后须落
        ``tasks/`` 直子级，越狱形态 → exit 1（已修复，回归钉）。"""
        data = tmp_path / "data"
        mk_task_dir(data, "t_x", _TASK_FILES)
        victim = data / "victim"
        victim.mkdir(parents=True)
        (victim / "dual.json").write_text("{}", encoding="utf-8")
        (victim / "zh-src.zip").write_bytes(b"fake")
        result = _RUNNER.invoke(
            app,
            ["share", "pack", "t_x/../../victim", "--data-dir", str(data)],
        )
        _clean(result)
        assert result.exit_code == 1

    def test_pack_in_jail_dotdot(self, tmp_path: Path) -> None:
        """``t_x/../t_x`` 归一后仍在 ``tasks/`` 内 → 放行（仓内形态合法）。"""
        data = tmp_path / "data"
        mk_task_dir(data, "t_x", _TASK_FILES)
        result = _RUNNER.invoke(
            app,
            [
                "share",
                "pack",
                "t_x/../t_x",
                "--data-dir",
                str(data),
                "-o",
                str(tmp_path / "out"),
            ],
        )
        _clean(result)
        assert result.exit_code == 0

    def test_pack_unpack_roundtrip(self, tmp_path: Path) -> None:
        """pack → unpack golden：``{share_key}.share.zip`` 校验解包 exit 0。"""
        data = tmp_path / "data"
        mk_task_dir(data, "t_fuzz01", _TASK_FILES)
        out_dir = tmp_path / "packed"
        result = _RUNNER.invoke(
            app,
            ["share", "pack", "t_fuzz01", "--data-dir", str(data), "-o", str(out_dir)],
        )
        _clean(result)
        assert result.exit_code == 0
        bundles = list(out_dir.glob("*.share.zip"))
        assert len(bundles) == 1
        dest = tmp_path / "unpacked"
        result = _RUNNER.invoke(
            app, ["share", "unpack", str(bundles[0]), "-o", str(dest)]
        )
        _clean(result)
        assert result.exit_code == 0
        assert (dest / "dual.json").is_file()

    def test_unpack_nonexistent(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            app, ["share", "unpack", str(tmp_path / "no.share.zip")]
        )
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- click exists=True

    def test_unpack_dir_arg(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(app, ["share", "unpack", str(tmp_path)])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- dir_okay=False

    def test_unpack_notazip(self, tmp_path: Path) -> None:
        blob = tmp_path / "b.share.zip"
        blob.write_bytes(b"PK-notreally")
        result = _RUNNER.invoke(app, ["share", "unpack", str(blob)])
        _clean(result)
        assert result.exit_code == 1
        assert "share unpack:" in result.stderr

    def test_unpack_out_existing_file(self, tmp_path: Path) -> None:
        """``-o`` 是已存在文件 → mkdir FileExistsError 归一 exit 1。"""
        epub = tmp_path / "b.epub"
        epub.write_bytes(_epub_blob())  # 是 zip 但非 share 包
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(app, ["share", "unpack", str(epub), "-o", str(blocker)])
        _clean(result)
        assert result.exit_code == 1

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="root 绕过权限位——chmod 0 不产生 EACCES"
    )
    def test_glossary_hash_unreadable_configured(self, tmp_path: Path) -> None:
        """配置 glossary chmod-0：read PermissionError → ShareError（曾 traceback）。"""
        g = tmp_path / "g.yaml"
        g.write_text("a: b\n", encoding="utf-8")
        g.chmod(0)
        try:
            with pytest.raises(cli.ShareError, match="glossary"):
                cli._share_glossary_hash(  # noqa: SLF001 -- 白盒钉 hash 组分
                    tmp_path, {"glossary": str(g)}, {}
                )
        finally:
            g.chmod(0o644)

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="root 绕过权限位——chmod 0 不产生 EACCES"
    )
    def test_glossary_hash_unreadable_local_skipped(self, tmp_path: Path) -> None:
        """local 层不可读 → 按缺席计（hash 落 ``""`` 无表层桶位）。"""
        base = tmp_path / "base"
        base.mkdir()
        g = base / LOCAL_GLOSSARY_NAME
        g.write_text("a: b\n", encoding="utf-8")
        g.chmod(0)
        try:
            got = cli._share_glossary_hash(tmp_path, {}, {})  # noqa: SLF001 -- 同上
            assert got == ""
        finally:
            g.chmod(0o644)


# ---------------------------------------------------------------- web / tools


class TestWeb:
    """``web`` 参数面——只测起服前的校验闸（不真起 uvicorn）。"""

    @pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "1.5"])
    def test_port_range(self, port: str) -> None:
        result = _RUNNER.invoke(app, ["web", "--port", port])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_data_dir_is_file(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
    ) -> None:
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(app, ["web", "--data-dir", str(blocker)])
        _clean(result)
        assert result.exit_code == 1


class TestTools:
    """``tools install-tectonic`` env 开关面——``install_tectonic`` 打桩防真下载。"""

    def test_bare_tools(self) -> None:
        result = _RUNNER.invoke(app, ["tools"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    @pytest.mark.parametrize("val", ["banana", "0", "no", "false"])
    def test_no_download_nontrue_allows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        val: str,
    ) -> None:
        """``TEXLATE_NO_DOWNLOAD=<非真值>`` → 仍允许下载（仅 1/true/yes/on 关）。"""
        monkeypatch.setenv("TEXLATE_NO_DOWNLOAD", val)
        called: list[bool] = []
        monkeypatch.setattr(toolchain, "resolve_tool", lambda _n: None)
        monkeypatch.setattr(toolchain, "find_managed", lambda: Path("/nope"))
        monkeypatch.setattr(
            toolchain,
            "install_tectonic",
            lambda: called.append(True) or Path("/fake/t"),
        )
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        _clean(result)
        assert result.exit_code == 0
        assert called, "非真值 NO_DOWNLOAD 应放行下载"

    @pytest.mark.parametrize("val", ["1", "true", "YES", " on "])
    def test_no_download_true_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        val: str,
    ) -> None:
        monkeypatch.setenv("TEXLATE_NO_DOWNLOAD", val)
        called: list[bool] = []
        monkeypatch.setattr(toolchain, "resolve_tool", lambda _n: None)
        monkeypatch.setattr(toolchain, "find_managed", lambda: Path("/nope"))
        monkeypatch.setattr(
            toolchain,
            "install_tectonic",
            lambda: called.append(True) or Path("/fake/t"),
        )
        result = _RUNNER.invoke(app, ["tools", "install-tectonic"])
        _clean(result)
        assert result.exit_code == 1
        assert not called


# ---------------------------------------------------------------- doctor / env


class TestDoctorEnv:
    """``doctor`` 与 ``TEXLATE_*`` env 对抗值——doctor 契约：只报告绝不炸。"""

    def test_baseline_clean(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
        result = _RUNNER.invoke(app, ["doctor"])
        _clean(result)
        assert result.exit_code in (0, 1)  # fail 项存在与否随机器

    def test_data_dir_file(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        blocker = tmp_path / "f"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setenv("TEXLATE_DATA_DIR", str(blocker))
        result = _RUNNER.invoke(app, ["doctor"])
        _clean(result)
        assert result.exit_code == 1

    @pytest.mark.parametrize("with_key", [True, False])
    def test_malformed_base_url(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
        *,
        with_key: bool,
    ) -> None:
        """``TEXLATE_BASE_URL='::::'`` → ``httpx.get`` InvalidURL 归一 fail 项。

        有/无 key 都触发：``env_base_url`` 非空即进请求路径——回归钉：
        InvalidURL 继承 ``Exception`` 非 ``HTTPError``，曾逃逸 except 成
        整体 traceback；现网关项降级 fail，doctor 不炸。
        """
        monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("TEXLATE_BASE_URL", "::::")
        if with_key:
            monkeypatch.setenv("TEXLATE_API_KEY", "sk-fuzz")
        result = _RUNNER.invoke(app, ["doctor"])
        _clean(result)
        assert result.exit_code in (0, 1)


class TestEnvFlags:
    """``TEXLATE_*`` env 语义钉：非真值旗标按 false 处理（不炸不歧义）。"""

    def test_offline_env_nontrue_goes_online(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``TEXLATE_OFFLINE=banana`` → 不在真值集 → 走在线取源（FakeFetcher 边界）。"""
        monkeypatch.setenv("TEXLATE_OFFLINE", "banana")
        body = make_targz({"main.tex": _MAIN_TEX})
        fake = FakeFetcher(body)

        class _CM:
            def __enter__(self) -> FakeFetcher:
                return fake

            def __exit__(self, *_args: object) -> bool:
                return False

        monkeypatch.setattr(cli, "Fetcher", _CM)
        result = _RUNNER.invoke(
            app, ["fetch", "2001.00001", "--cache", str(tmp_path / "c")]
        )
        _clean(result)
        assert result.exit_code == 0
        assert json.loads(result.stdout)["status"] in ("ok", "hit")

    @pytest.mark.parametrize("val", ["1", "true", "YES", " on "])
    def test_offline_env_true(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
        val: str,
    ) -> None:
        """``TEXLATE_OFFLINE=<真值>`` → 离线闸生效：空缓存 exit 1 零网络。"""
        monkeypatch.setenv("TEXLATE_OFFLINE", val)
        result = _RUNNER.invoke(app, ["fetch", "2001.00001", "--cache", str(tmp_path)])
        _clean(result)
        assert result.exit_code == 1
        assert "offline_no_cache" in json.loads(result.stdout)["detail"]

    def test_env_fuzz_on_version(
        self,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用（env 清洗）
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """行为 env 全谱塞对抗值 → ``version`` 仍 exit 0（env 不应影响无干命令）。"""
        for k, v in {
            "TEXLATE_OFFLINE": "banana",
            "TEXLATE_NO_DOWNLOAD": "\x01\xff",
            "TEXLATE_TRANSLATOR": "",
            "TEXLATE_MODEL": "m" * 500,
            "TEXLATE_BASE_URL": "::::",
            "TEXLATE_API_KEY": "",
            "TEXLATE_DATA_DIR": str(Path("/nonexistent-dir-fuzz")),
        }.items():
            monkeypatch.setenv(k, v)
        result = _RUNNER.invoke(app, ["version"])
        _clean(result)
        assert result.exit_code == 0
        assert result.stdout.startswith("texlate ")


# ---------------------------------------------------------------- --help 全谱 / 顶层


class TestHelpSurface:
    """``--help`` 与裸命令——全谱 exit 0/2 干净，无 traceback。"""

    _CMDS: ClassVar[list[list[str]]] = [
        [],
        ["fetch"],
        ["parse"],
        ["run"],
        ["web"],
        ["export"],
        ["version"],
        ["doctor"],
        ["share"],
        ["share", "pack"],
        ["share", "unpack"],
        ["tools"],
        ["tools", "install-tectonic"],
    ]

    @pytest.mark.parametrize("cmd", _CMDS)
    def test_help_everywhere(self, cmd: list[str]) -> None:
        result = _RUNNER.invoke(app, [*cmd, "--help"])
        _clean(result)
        assert result.exit_code == 0
        assert "Usage" in result.stdout

    def test_bare_root(self) -> None:
        result = _RUNNER.invoke(app, [])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004 -- no_args_is_help → 用法面
        assert "Usage" in result.stdout

    def test_unknown_command(self) -> None:
        result = _RUNNER.invoke(app, ["nosuchcmd"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004

    def test_extra_arg(
        self,
        no_network: _TripwireFetcher,  # noqa: ARG002 -- fixture 副作用（断网绊线）
    ) -> None:
        result = _RUNNER.invoke(app, ["fetch", "a", "b", "--offline"])
        _clean(result)
        assert result.exit_code == 2  # noqa: PLR2004
