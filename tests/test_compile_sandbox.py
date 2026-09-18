"""批量编译 OS 级兜底测试：env 白名单 / shell-escape 旗标 / Linux bwrap 包裹。

argv/env 断言走 monkeypatch ``run_process`` 捕获（不起真引擎）；``\\write18``
与实编译用例要真 xelatex/tectonic/bwrap，缺件 skip。
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import texlate.compile.engine as eng_mod
import texlate.compile.proc as proc_mod
import texlate.compile.sandbox as sb
from texlate.compile.engine import TectonicEngine, XelatexEngine
from texlate.compile.sandbox import child_env, find_tool, run_process, sandbox_wrap

if sys.platform != "win32":
    import resource

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    FakeRun = Callable[
        [list[str], Path, dict[str, str], float, int],
        tuple[int | None, str, float, bool],
    ]

_SECRETS = (
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "SSH_AUTH_SOCK",
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
    "TEXLATE_FAKE_KEY",
)


def _fake_run(calls: list[dict[str, Any]]) -> FakeRun:
    """捕获 ``(cmd, env)`` 的假 run_process——直接 rc=0 不干活。"""

    def fake(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        del cwd, timeout, out_cap, should_cancel
        calls.append({"cmd": list(cmd), "env": dict(env)})
        return 0, "", 0.1, False

    return fake


def _bind_sources(cmd: list[str]) -> set[str]:
    """抽出 bwrap argv 里全部 bind 系旗标的源路径。"""
    flags = {"--bind", "--bind-try", "--ro-bind", "--ro-bind-try", "--dev-bind"}
    return {cmd[i + 1] for i, t in enumerate(cmd[:-1]) if t in flags}


@pytest.fixture(autouse=True)
def _clear_probe_caches() -> Iterator[None]:
    """每个用例后清掉 ``_bwrap_capable``/``_kpathsea_dirs`` 的 lru_cache。

    形态用例会 patch ``find_tool``/``run_process``——探测结果若缓存住会
    污染后续真编译用例的挂载面（如 TEXMFSYSVAR 丢失 → fmt 找不到）。
    """
    yield
    sb._bwrap_capable.cache_clear()  # noqa: SLF001
    sb._kpathsea_dirs.cache_clear()  # noqa: SLF001


# ---------------------------------------------------------------- env 白名单
def test_child_env_strips_realistic_secret_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实形态的 secret 名（AWS_/SSH_/TOKEN/*_KEY）全被白名单剥掉。"""
    for name in _SECRETS:
        monkeypatch.setenv(name, "leak")
    env = child_env()
    for name in _SECRETS:
        assert name not in env
    assert env["shell_escape"] == "f"
    assert env["openin_any"] == "p"
    assert env["openout_any"] == "p"
    assert env["TECTONIC_UNTRUSTED_MODE"] == "1"


def test_compile_subprocess_env_has_no_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """穿透到 run_process 的 env 也无 secret（引擎层端到端口径）。"""
    for name in _SECRETS:
        monkeypatch.setenv(name, "leak")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    # 沙箱内探针（bwrap capable/kpse）走 sb 绑定——与引擎侧调用分开 intercept
    monkeypatch.setattr(sb, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=1, sandbox=True
    )
    env = calls[-1]["env"]
    for name in _SECRETS:
        assert name not in env
    cmd = calls[-1]["cmd"]
    assert "-no-shell-escape" in cmd


# ---------------------------------------------------------------- bwrap argv 形态
@pytest.mark.skipif(sys.platform != "linux", reason="bwrap 兜底仅 linux")
def test_bwrap_wraps_xelatex_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """xelatex sandbox=True：bwrap 包裹 + 断网 + $HOME 本体不挂。"""
    monkeypatch.setattr(sb, "_bwrap_capable", lambda: True)
    monkeypatch.setattr(sb, "find_tool", lambda n: f"/fake/{n}")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    monkeypatch.setattr(sb, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    res = XelatexEngine(binary="/fake/xelatex").compile(
        tmp_path, "main.tex", passes=1, sandbox=True
    )
    cmd: list[str] = calls[-1]["cmd"]
    assert res.sandbox_mode == "bwrap"
    assert cmd[0] == "/fake/bwrap"
    for flag in (
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--cap-drop",
        "--tmpfs",
        "--dir",
    ):
        assert flag in cmd
    srcs = _bind_sources(cmd)
    # $HOME 本体不可挂（deny-$HOME 语义）；工程/输出硬挂 rw。
    assert str(Path.home()) not in srcs
    assert str(tmp_path) in srcs
    sep = cmd.index("--")
    assert cmd[sep + 1] == "/fake/xelatex"
    assert "-no-shell-escape" in cmd


@pytest.mark.skipif(sys.platform != "linux", reason="bwrap 兜底仅 linux")
def test_bwrap_wraps_tectonic_keeps_net(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tectonic 冷拉 bundle 走进程内 HTTPS——包裹保留网络、仍有 --untrusted。"""
    monkeypatch.setattr(sb, "_bwrap_capable", lambda: True)
    monkeypatch.setattr(sb, "find_tool", lambda n: f"/fake/{n}")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    monkeypatch.setattr(sb, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    res = TectonicEngine(binary="/fake/tectonic", bundle="").compile(
        tmp_path, "main.tex", sandbox=True
    )
    cmd: list[str] = calls[-1]["cmd"]
    assert res.sandbox_mode == "bwrap"
    assert cmd[0] == "/fake/bwrap"
    assert "--unshare-net" not in cmd
    assert "--unshare-pid" in cmd
    assert "--untrusted" in cmd
    sep = cmd.index("--")
    assert cmd[sep + 1] == "/fake/tectonic"


@pytest.mark.skipif(sys.platform != "linux", reason="bwrap 兜底仅 linux")
def test_bwrap_home_secret_dirs_unbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """$HOME 下只挂白名单子路径——~/.ssh、~/.aws、~/.gnupg 不得出现在挂面。"""
    monkeypatch.setattr(sb, "_bwrap_capable", lambda: True)
    monkeypatch.setattr(sb, "find_tool", lambda n: f"/fake/{n}")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    monkeypatch.setattr(sb, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    XelatexEngine(binary="/fake/xelatex").compile(
        tmp_path, "main.tex", passes=1, sandbox=True
    )
    srcs = _bind_sources(calls[-1]["cmd"])
    home = Path.home()
    allowed_top = ("texmf", ".cache", ".fonts", ".local", ".texlate")
    for p in srcs:
        pp = Path(p)
        if not pp.is_relative_to(home):
            continue
        top = pp.relative_to(home).parts[0]
        assert top in allowed_top or top.startswith(".texlive"), p
    for secret_dir in (".ssh", ".aws", ".gnupg"):
        assert str(home / secret_dir) not in srcs


# ---------------------------------------------------------------- 模式回落
def test_sandbox_false_passthrough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=1, sandbox=False
    )
    assert res.sandbox_mode == "off"
    assert calls[-1]["cmd"][0] == "/bin/true"


@pytest.mark.skipif(sys.platform != "linux", reason="bwrap 兜底仅 linux")
def test_bwrap_incapable_falls_back_to_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bwrap 缺席/内核禁用 → sandbox=True 退回 env-only，不挂编译。"""
    monkeypatch.setattr(sb, "_bwrap_capable", lambda: False)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(eng_mod, "run_process", _fake_run(calls))
    (tmp_path / "main.tex").write_text("x\n")
    res = XelatexEngine(binary="/bin/true").compile(
        tmp_path, "main.tex", passes=1, sandbox=True
    )
    assert res.sandbox_mode == "env"
    assert calls[-1]["cmd"][0] == "/bin/true"


# ---------------------------------------------------------------- 真引擎端到端
requires_xelatex = pytest.mark.skipif(
    find_tool("xelatex") is None, reason="xelatex 缺席"
)


@pytest.mark.integration
@requires_xelatex
def test_write18_disabled_under_sandbox(tmp_path: Path) -> None:
    """\\immediate\\write18 mini tex：sandbox 下不执行命令（文件不得落盘）。"""
    work = tmp_path / "work"
    work.mkdir()
    target = tmp_path / "PWNED_WRITE18"
    (work / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\n"
        f"\\immediate\\write18{{touch {target}}}\n"
        "\\end{document}\n"
    )
    try:
        res = XelatexEngine().compile(
            work, "main.tex", passes=1, timeout=90, sandbox=True
        )
        assert not target.exists()
        assert res.sandbox_mode in {"bwrap", "env", "sandbox-exec"}
    finally:
        target.unlink(missing_ok=True)


@pytest.mark.integration
@requires_xelatex
def test_minimal_doc_compiles_under_sandbox(tmp_path: Path) -> None:
    """沙箱包裹不破坏正常编译（挂载面完备性回归——fmt/字体/缓存都在）。"""
    work = tmp_path / "work"
    work.mkdir()
    (work / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}hello $x^2$\\end{document}\n"
    )
    res = XelatexEngine().compile(work, "main.tex", passes=1, timeout=120, sandbox=True)
    assert res.has_pdf, res.stdout_tail[-500:]


@pytest.mark.integration
@requires_xelatex
def test_write18_ran_but_contained_by_bwrap(tmp_path: Path) -> None:
    """-shell-escape flag 穿透（fixloop minted 同款）时 bwrap 仍兜住写面。

    ``shell_escape=f`` env 阀会被 CLI flag last-wins 压过（实证）——逃逸真的
    发生：工作目录内写入落盘（允许的写域），但宿主 ``/tmp``（沙箱内是私有
    tmpfs）与 ``$HOME``（影子化）都写不出去。
    """
    if not sb._bwrap_capable():  # noqa: SLF001
        pytest.skip("bwrap 不可用")
    work = tmp_path / "work"
    work.mkdir()
    inside = work / "inside_proof.txt"
    outside = tmp_path / "PWNED_OUTSIDE"
    home_target = Path.home() / "PWNED_HOME_TEXLATE_TEST"
    (work / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\n"
        "\\immediate\\write18{touch inside_proof.txt}\n"
        f"\\immediate\\write18{{touch {outside}}}\n"
        f"\\immediate\\write18{{touch {home_target}}}\n"
        "\\end{document}\n"
    )
    try:
        res = XelatexEngine().compile(
            work,
            "main.tex",
            passes=1,
            timeout=90,
            sandbox=True,
            flags=["-shell-escape"],
        )
        assert "-shell-escape" in res.flags_applied  # flag 确实放行
        assert res.sandbox_mode == "bwrap"
        assert inside.exists()  # write18 真跑了（否则断言全 vacuous）
        assert not outside.exists()
        assert not home_target.exists()
    finally:
        outside.unlink(missing_ok=True)
        home_target.unlink(missing_ok=True)


def test_tectonic_real_compile_sandboxed(tmp_path: Path) -> None:
    """tectonic 实跑：binary 在系统前缀外时按文件挂入 + 留网拉 bundle。"""
    eng = TectonicEngine()
    if eng.detect() is None:
        pytest.skip("无 tectonic")
    work = tmp_path / "work"
    work.mkdir()
    (work / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}hi tectonic\\end{document}\n"
    )
    res = eng.compile(work, "main.tex", timeout=240, sandbox=True)
    assert res.rc is not None
    assert not res.timed_out
    if sys.platform == "linux" and sb._bwrap_capable():  # noqa: SLF001
        assert res.sandbox_mode == "bwrap"


# ---------------------------------------------------------------- 审计修复面
def test_sandbox_wrap_darwin_deny_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allow_net=False → profile 追加 ``(deny network*)``——与 bwrap
    ``--unshare-net`` 同义（xelatex 侧约定：断网压 shell-escape 穿透的
    curl 外联面）；默认 True 不加。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda p: True if str(p) == "/usr/bin/sandbox-exec" else real_exists(p),
    )
    cmd = ["xelatex", "main.tex"]
    wrapped = sandbox_wrap(cmd, root=tmp_path, out=tmp_path, allow_net=False)
    assert wrapped[0] == "/usr/bin/sandbox-exec"
    assert "(deny network*)" in wrapped[2]
    wrapped_on = sandbox_wrap(cmd, root=tmp_path, out=tmp_path)
    assert "(deny network*)" not in wrapped_on[2]


def test_run_process_keyboardinterrupt_kills_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """communicate 抛 KeyboardInterrupt → killpg 整组再传播——不杀会把
    编译进程连同 mktex*/dvips 子孙一起孤儿化（sleep 30 探针实证幸存）。"""
    killed: list[tuple[int, int]] = []

    class FakeProc:
        pid = 0xFA17
        returncode: int | None = None

        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def communicate(self, timeout: float | None = None) -> tuple[bytes, None]:
            del timeout
            raise KeyboardInterrupt

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.returncode = -9
            return -9

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(sb.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(sb.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        run_process(["sleep", "30"], cwd=tmp_path, env={}, timeout=5)
    assert killed == [(0xFA17, signal.SIGKILL)]


def test_run_process_timeout_reap_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超时后二次 communicate 有界（30s）——setsid/双 fork 逃逸孙进程仍握
    stdout 写端时不再无限等（旧码裸 communicate 会挂死整格）。"""
    timeouts: list[float | None] = []

    class FakeProc:
        pid = 0xFA18
        returncode = -9

        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def communicate(self, timeout: float | None = None) -> tuple[bytes, None]:
            timeouts.append(timeout)
            raise subprocess.TimeoutExpired(["sleep", "30"], timeout)

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return -9

        def kill(self) -> None:
            pass

    monkeypatch.setattr(sb.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(sb.os, "killpg", lambda _pid, _sig: None)
    rc, _out, _sec, to = run_process(["sleep", "30"], cwd=tmp_path, env={}, timeout=5)
    assert to is True
    assert timeouts == [5, 30]
    assert rc == -9  # noqa: PLR2004 - SIGKILL


# ---------------------------------------------------------------- rlimits
requires_posix = pytest.mark.skipif(sys.platform == "win32", reason="rlimits 仅 POSIX")


@requires_posix
def test_cap_rlimit_lowers_only() -> None:
    """_cap_rlimit 只降不升、hard 保持——宿主 soft 已低于 cap 时不动。"""
    what = resource.RLIMIT_NOFILE
    soft, hard = resource.getrlimit(what)
    if soft == resource.RLIM_INFINITY or soft <= 2:  # noqa: PLR2004
        pytest.skip("宿主 soft 无下降空间")
    try:
        sb._cap_rlimit(what, soft - 1)  # noqa: SLF001
        assert resource.getrlimit(what) == (soft - 1, hard)
        sb._cap_rlimit(what, soft + 100)  # noqa: SLF001
        assert resource.getrlimit(what)[0] == soft - 1
    finally:
        resource.setrlimit(what, (soft, hard))


@requires_posix
def test_run_process_rlimit_as_kills_hog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RLIMIT_AS 实证：512MB 帽下分配 2GB → MemoryError，失控进程吃不光宿主。"""
    monkeypatch.setattr(proc_mod, "_RLIMIT_AS_BYTES", 512 * 1024**2)
    rc, out, _sec, to = run_process(
        [sys.executable, "-c", "b = bytearray(2 * 1024**3); print(len(b))"],
        cwd=tmp_path,
        env=child_env(),
        timeout=30,
    )
    assert to is False
    assert rc not in (None, 0)
    assert "MemoryError" in out


@requires_posix
def test_run_process_rlimit_cpu_sigxcpu(tmp_path: Path) -> None:
    """RLIMIT_CPU 实证：_cap_rlimit 装 2s CPU 帽的自旋子进程被 SIGXCPU 收。

    run_process 的 cap 公式恒 ≥2×墙钟（纯兜底、可验证路径不存在）——直接
    用同一 ``preexec_fn`` 机制装小帽，验证的是机制本身而非数值。
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "while True: pass"],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        # PLW1509: 与 sandbox.py 同机制——回调只碰 resource.setrlimit。
        preexec_fn=lambda: sb._cap_rlimit(resource.RLIMIT_CPU, 2),  # noqa: PLW1509, SLF001
    )
    proc.wait(timeout=30)
    assert proc.returncode == -signal.SIGXCPU


@requires_posix
def test_run_process_rlimit_nofile_emfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RLIMIT_NOFILE 实证：cap=24 时保活 open 撞 EMFILE。"""
    monkeypatch.setattr(proc_mod, "_RLIMIT_NOFILE", 24)
    rc, out, _sec, to = run_process(
        [
            sys.executable,
            "-c",
            (
                "import os; print(len([os.open('/dev/null', os.O_RDONLY) "
                "for _ in range(200)]))"
            ),
        ],
        cwd=tmp_path,
        env=child_env(),
        timeout=30,
    )
    assert to is False
    assert rc not in (None, 0)
    assert "Too many open files" in out


# ------------------------------------------------------------- 有界排干环
@requires_posix
def test_run_process_exits_on_child_death_not_eof(tmp_path: Path) -> None:
    """孙进程握写端不挡收割：父死即收——旧 ``communicate`` 等 EOF 会烧满
    timeout（loop2 xelatex↔xdvipdfmx 死锁对/setsid 逃逸孙实证签名）。"""
    rc, out, sec, to = run_process(
        ["sh", "-c", "echo done; sleep 30 &"],
        cwd=tmp_path,
        env=child_env(),
        timeout=20,
    )
    assert to is False  # 等 EOF 形必然 timeout——此断言即回归签
    assert sec < 15  # noqa: PLR2004 - 实测亚秒级，留足慢机余量
    assert rc == 0
    assert "done" in out


@requires_posix
def test_run_process_timeout_kills_and_salvages(tmp_path: Path) -> None:
    """真超时臂：killpg 收树 + 已读输出经异常带出（echo 先于 sleep 落管）。"""
    rc, out, _sec, to = run_process(
        ["sh", "-c", "echo hi; sleep 60"],
        cwd=tmp_path,
        env=child_env(),
        timeout=2,
    )
    assert to is True
    assert rc == -signal.SIGKILL
    assert "hi" in out
