"""cst tree-sitter 层测试 —— node/deps 不在场时整体 skip（可选组件语义本身）。

开发态依赖解析：bench/ts/node_modules 有 tree-sitter + @pfoerster/tree-sitter-latex，
用 TEXLATE_TS_NODE_PATH 指过去即可，不复制不重装。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from texlate.validate.cst import CstError, TsBaseline, TsResult, TsValidator
from texlate.validate.report import aggregate

REPO = Path(__file__).resolve().parents[2]
BENCH_NM = REPO / "bench" / "ts" / "node_modules"

# 收集期只查 PATH/纯路径——可用性终判（含 worker.js）放模块 fixture，
# 收集阶段不构造校验器
need_cst = pytest.mark.skipif(
    shutil.which("node") is None or not (BENCH_NM / "tree-sitter").is_dir(),
    reason="node 或 tree-sitter 依赖不在场（可选组件；bench/ts 跑 npm ci 即恢复）",
)


@pytest.fixture(scope="module")
def v() -> TsValidator:
    val = TsValidator(node_path=BENCH_NM)
    if not val.available():
        pytest.skip("cst 依赖不可用（可选组件）")
    return val


SRC = "We propose [[MATH_1]] in \\begin{equation}\nE=mc^2\n\\end{equation}.\n"
ZH_CLEAN = "我们提出 [[MATH_1]] 于 \\begin{equation}\nE=mc^2\n\\end{equation}。\n"
ZH_BROKEN = "我们提出 于 \\begin{equation}\nE=mc^2\n\\end{equationx}。\n"  # 丢占位符 + \end 改名


@pytest.mark.integration
@need_cst
def test_batch_clean_and_broken(v: TsValidator) -> None:
    res = v.validate_batch(
        [
            {"id": "ok", "tex": ZH_CLEAN, "expect": ["MATH_1"]},
            {"id": "bad", "tex": ZH_BROKEN, "expect": ["MATH_1"]},
        ]
    )
    ok_r, bad_r = res
    assert ok_r.id == "ok"
    assert ok_r.ok
    assert bad_r.id == "bad"
    assert not bad_r.ok
    assert bad_r.env_mismatches  # \end 改名被 CST 抓到
    assert "MATH_1" in bad_r.placeholders["missing"]


@pytest.mark.integration
@need_cst
def test_baseline_relative_mode(v: TsValidator) -> None:
    """相对判定：baseline 带 ERROR 的源标记不拖累译文判定。"""
    src_with_gap = "\\inferrule{A}{B} 文本。"  # grammar 空隙命令产生 baseline ERROR
    base = v.sign(src_with_gap)
    assert base.parse_errors >= 0  # 标记可用即对
    res = v.validate(src_with_gap, baseline=base)  # 原样译文 vs 自身基线
    assert res.ok_relative is True


@pytest.mark.integration
@need_cst
def test_resident_mode() -> None:
    with TsValidator(node_path=BENCH_NM) as daemon:
        base = daemon.sign(SRC)
        res = daemon.validate(ZH_BROKEN, baseline=base, expect=["MATH_1"])
        assert res.ok_relative is False
        res2 = daemon.validate(ZH_CLEAN, baseline=base, expect=["MATH_1"])
        assert res2.ok_relative is True


@pytest.mark.integration
@need_cst
def test_sign_returns_baseline(v: TsValidator) -> None:
    base = v.sign(SRC)
    assert isinstance(base, TsBaseline)
    assert base.parse_errors == 0


def test_unavailable_degrades() -> None:
    bad = TsValidator(node="/nonexistent-node", worker_dir="/nonexistent")
    assert not bad.available()


def test_baseline_roundtrip() -> None:
    b = TsBaseline(parse_errors=1, env_mismatches=2, unclosed_math=3, brace_balance=-1)
    assert TsBaseline.from_dict(b.to_dict()) == b


# ---------------------------------------------------------------- 审计修复面


def test_available_requires_both_npm_deps(tmp_path: Path) -> None:
    """只有 ``tree-sitter`` 无 ``@pfoerster/tree-sitter-latex`` 文法时
    不得报可用——node 侧 require 会炸，应判不可用降级 rules。"""
    (tmp_path / "tree-sitter").mkdir()
    val = TsValidator(node_path=tmp_path)
    assert not val._deps_present()  # noqa: SLF001 - 依赖面判定的最小单元
    (tmp_path / "@pfoerster" / "tree-sitter-latex").mkdir(parents=True)
    assert val._deps_present()  # noqa: SLF001 - 同上


class _FakeStdin:
    """常驻 worker stdin 假桩——write 时把预设响应行喂回队列。"""

    def __init__(self, v: TsValidator, replies: list[str | None]) -> None:
        self._v = v
        self._replies = replies

    def write(self, s: str) -> int:
        for r in self._replies:
            self._v._lines.put(r)  # noqa: SLF001 - 假桩模拟泵线程回灌
        return len(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeProc:
    def __init__(self, v: TsValidator, replies: list[str | None]) -> None:
        self.stdin = _FakeStdin(v, replies)
        self._rc: int | None = None

    def poll(self) -> int | None:
        return self._rc

    def wait(self, timeout: float = 0) -> int:  # noqa: ARG002 - Popen.wait 签名对齐
        return self._rc or 0

    def kill(self) -> None:
        pass


def test_one_pairs_response_by_id() -> None:
    """常驻通道按 ``id`` 配对——上轮超时残留的迟到响应行须丢弃，
    不得当本请求结果返回。"""
    v = TsValidator()
    stale = json.dumps({"id": "prev-chunk", "ok": False})
    mine = json.dumps({"id": "cur", "ok": True})
    v._proc = _FakeProc(  # noqa: SLF001 - 注入假常驻通道
        v, [stale + "\n", mine + "\n"]
    )  # type: ignore[assignment]
    res = v._one({"id": "cur", "tex": "x"})  # noqa: SLF001 - 测的就是私有通道
    assert res.id == "cur"
    assert res.ok


def test_one_eof_sentinel_fails_fast() -> None:
    """worker 死 → 泵线程投 None 哨兵 → ``_one`` 立即 CstError 而非
    白挂整个 timeout。"""
    v = TsValidator(timeout=30.0)
    v._proc = _FakeProc(  # noqa: SLF001 - 注入假常驻通道
        v, [None]
    )  # type: ignore[assignment]
    with pytest.raises(CstError, match="EOF"):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001 - 同上
    assert v._proc is None  # noqa: SLF001 - 断言通道已关闭  # EOF 后通道已关闭，下一调用走批处理降级


def test_one_dead_proc_falls_back_to_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """poll() 非 None（上轮崩死）→ 透明降级 spawn-per-batch。"""
    v = TsValidator()
    v._proc = _FakeProc(v, [])  # noqa: SLF001 - 注入假常驻通道  # type: ignore[assignment]
    v._proc._rc = 1  # noqa: SLF001 - 模拟已退出进程
    sentinel = TsResult(id="x", ok=True)
    monkeypatch.setattr(v, "validate_batch", lambda _recs: [sentinel])
    assert v._one({"id": "x", "tex": "t"}) is sentinel  # noqa: SLF001 - 同上
    assert v._proc is None  # noqa: SLF001 - 断言已降级


# ------------------------------------------------- 子进程边界错误路径补洞
# （refactor-audit C1：fuzz 批已盖 validate_batch 三故障面，
#   本节补齐 _require_available / open / close / _one 的残余分支）


def _batch_stub(tmp_path: Path) -> TsValidator:
    """node + worker.js 在场（deps 无所谓——不到 available() 那步）。"""
    (tmp_path / "validator.js").write_text("// stub\n", encoding="utf-8")
    return TsValidator(node="/bin/true", worker_dir=tmp_path)


def test_require_available_no_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """node 三路全缺（参数/env/PATH）→ 批处理与常驻入口同抛 CstError。"""
    monkeypatch.delenv("TEXLATE_NODE", raising=False)
    monkeypatch.delenv("TEXLATE_TS_WORKER", raising=False)
    monkeypatch.delenv("TEXLATE_TS_NODE_PATH", raising=False)
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    v = TsValidator()
    assert not v.available()
    with pytest.raises(CstError, match="node 不在 PATH"):
        v.validate_batch([{"id": "a", "tex": "x"}])
    with pytest.raises(CstError, match="node 不在 PATH"):
        v.open()


def test_require_available_missing_worker(tmp_path: Path) -> None:
    """node 在但 worker.js 缺席 → 两入口抛 'worker 缺失'。"""
    v = TsValidator(node="/bin/true", worker_dir=tmp_path)
    assert not v.available()
    with pytest.raises(CstError, match="worker 缺失"):
        v.validate_batch([{"id": "a", "tex": "x"}])
    with pytest.raises(CstError, match="worker 缺失"):
        v.open()


def test_open_popen_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """常驻 worker Popen OSError → '启动失败' CstError（不泄内建异常）。"""
    v = _batch_stub(tmp_path)

    def boom(*_a: object, **_k: object) -> None:
        msg = "exec format error"
        raise OSError(msg)

    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(CstError, match="启动失败"):
        v.open()
    assert v._proc is None  # noqa: SLF001 - 启动失败不留半开通道


class _DeadStdin:
    """write 即 broken pipe 的 stdin——模拟 worker 已死管道断裂。"""

    def write(self, _s: str) -> int:
        msg = "broken pipe"
        raise OSError(msg)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _UnclosableStdin:
    """close 即炸的 stdin——close() 清理路径故障源。"""

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        msg = "close fail"
        raise OSError(msg)


class _KillableProc:
    """kill 可观察、wait 可配置超时的 proc 假桩。"""

    def __init__(self, stdin: object, *, wait_raises: bool = False) -> None:
        self.stdin = stdin
        self.killed = False
        self._wait_raises = wait_raises

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float = 0) -> int:
        if self._wait_raises:
            raise subprocess.TimeoutExpired(cmd="node", timeout=timeout)
        return 0

    def kill(self) -> None:
        self.killed = True


def test_close_kills_proc_on_teardown_failure() -> None:
    """close() 清理失败面：stdin.close OSError 与 wait 超时都走 kill 兜底。"""
    v = TsValidator()
    p_close_boom = _KillableProc(_UnclosableStdin())
    v._proc = p_close_boom  # noqa: SLF001  # type: ignore[assignment]
    v.close()
    assert p_close_boom.killed
    assert v._proc is None  # noqa: SLF001 - 关闭后通道复位

    p_wait_boom = _KillableProc(_FakeStdin(v, []), wait_raises=True)
    v._proc = p_wait_boom  # noqa: SLF001  # type: ignore[assignment]
    v.close()
    assert p_wait_boom.killed


def test_one_stdin_broken_raises() -> None:
    """常驻通道 stdin.write OSError → 'stdin 已断' CstError。"""
    v = TsValidator(timeout=5)
    v._proc = _KillableProc(_DeadStdin())  # noqa: SLF001  # type: ignore[assignment]
    with pytest.raises(CstError, match="stdin 已断"):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001


def test_one_response_timeout() -> None:
    """配对行迟迟不到 → queue.Empty 转 '响应超时' CstError（不死等）。"""
    v = TsValidator(timeout=0.05)
    v._proc = _FakeProc(v, [])  # noqa: SLF001  # type: ignore[assignment]
    with pytest.raises(CstError, match="超时"):
        v._one({"id": "x", "tex": "t"})  # noqa: SLF001


def test_batch_nonzero_exit_empty_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非零退出且 stderr 空白 → '(stderr 空)' 占位进错误消息。"""
    v = _batch_stub(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=2, stdout="", stderr="  \n"),
    )
    with pytest.raises(CstError, match="stderr 空"):
        v.validate_batch([{"id": "a", "tex": "x"}])


def test_batch_blank_lines_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stdout 夹空行/纯空白行 → 过滤不计入响应数。"""
    v = _batch_stub(tmp_path)
    out = '\n{"id":"a","ok":true}\n  \n{"id":"b","ok":false}\n\n'
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=out, stderr=""),
    )
    res = v.validate_batch([{"id": "a", "tex": "x"}, {"id": "b", "tex": "y"}])
    assert [r.id for r in res] == ["a", "b"]
    assert res[1].ok is False


# ------------------------------------------------- A2：env 白名单钉


def test_env_whitelist_strips_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_env`` 只透传 node 启动必需面——secret/业务 env 不进子进程，
    ``NODE_PATH`` 注入值盖掉透传。"""
    monkeypatch.setenv("TEXLATE_API_KEY", "sk-fake")
    monkeypatch.setenv("TEXLATE_GATEWAY_KEY", "gw-fake")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-fake")
    monkeypatch.setenv("TEXLATE_TS_NODE_PATH", "/should-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/x")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    env = TsValidator(node_path="/nonexistent/nm")._env()  # noqa: SLF001
    for leaked in (
        "TEXLATE_API_KEY",
        "TEXLATE_GATEWAY_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "TEXLATE_TS_NODE_PATH",
    ):
        assert leaked not in env
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"
    assert env["LC_ALL"] == "C.UTF-8"
    # NODE_PATH 是 str(Path) 原生形——win32 出 '\' 分隔
    assert env["NODE_PATH"] == str(Path("/nonexistent/nm"))


def test_env_whitelist_minimal_node_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空 environ 后白名单不捏造缺失键——env 可小到只剩 NODE_PATH。"""
    for k in list(os.environ):
        monkeypatch.delenv(k)
    env = TsValidator(node_path="/n")._env()  # noqa: SLF001
    assert env == {"NODE_PATH": str(Path("/n"))}  # win32 出 \n 原生形


# ------------------------------------------------- C8：TsResult.to_dict 钉


def test_result_to_dict_roundtrip() -> None:
    """``to_dict`` 是 ``from_dict`` 的对偶：全字段往返相等，
    ``verdict_ok`` 计算字段随序列化落盘。"""
    res = TsResult(
        id="c1",
        ok=False,
        ok_relative=False,
        parse_errors=[{"type": "ERROR", "row": 3, "snippet": "\\foo"}],
        env_mismatches=[
            {"kind": "name_mismatch", "begin_env": "a", "end_env": "b", "line": 1}
        ],
        unclosed_math=1,
        brace_balance=-1,
        placeholders={"missing": ["MATH_1"], "unexpected": [], "typos": []},
        parse_ms=1.5,
        error=None,
    )
    d = res.to_dict()
    assert d["id"] == "c1"
    assert d["verdict_ok"] is False
    assert TsResult.from_dict(d) == res


def test_report_cst_uses_to_dict() -> None:
    """report.to_dict 的 cst 节与 ``TsResult.to_dict`` 同形——字段表不再手抄。"""
    cst = TsResult(id="x", ok=True, parse_ms=0.5)
    rep = aggregate("c", cst=cst)
    assert rep.to_dict()["cst"] == cst.to_dict()


def test_ts_result_from_dict_inf_fields() -> None:
    """worker 输出 ``1e999``（JSON→inf float）→ int() OverflowError 归 CstError。"""
    with pytest.raises(CstError):
        TsResult.from_dict({"unclosed_math": 1e999})
    with pytest.raises(CstError):
        TsResult.from_dict({"brace_balance": float("-inf")})


def test_ts_baseline_from_dict_inf_fields() -> None:
    """baseline 反序列化同契约硬化：inf/类型违例 → CstError。"""
    with pytest.raises(CstError):
        TsBaseline.from_dict({"parse_errors": 1e999})
    with pytest.raises(CstError):
        TsBaseline.from_dict({"env_mismatches": "abc"})
    assert TsBaseline.from_dict({}) == TsBaseline()  # 正常路径不受影响
