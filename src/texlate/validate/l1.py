"""L1 tree-sitter CST 校验层 —— node 子进程 JSONL 批处理（可选组件，规格 docs/08 §2.2）。

技术路线结论（2026-09 调研）：

- 文法 = ``latex-lsp/tree-sitter-latex``（npm ``@pfoerster/tree-sitter-latex`` 0.6.0）。
- Python 侧选项评估：
    a. PyPI ``tree-sitter-latex`` wheel —— **不存在**（JSON API 404，未发布）；
    b. ``tree-sitter-languages`` 打包集 —— 收录表无 latex 文法；
    c. 文法仓库自带 ``bindings/python`` —— 未发布，sdist 安装需用户侧
       C toolchain 现场编译 parser.c/scanner.cc，破坏 uv 零编译体验 → 排除；
    d. ``web-tree-sitter`` WASM —— 仍需 JS 宿主（node/deno）或 wasmtime
       手写 glue，工程量大于收益 → 排除；
    e. **node 子进程 JSONL（docs/08 §2.2 定案）** —— chunk 级 0.7–2ms、
       常驻/批处理摊薄 <1ms/块；``shutil.which("node")`` 探测，
       无 node 优雅降级 L0。
- 分发：``validate/ts/`` 内 validator.js + package.json（两 npm 依赖均有
  prebuilt）随包作 data；node_modules 缺席时 ``npm i --prefix`` 补装（~5s）；
  开发态可用 ``TEXLATE_TS_NODE_PATH`` 指到现成 node_modules（如 bench/ts）。

判定**必须 baseline 相对模式**（``ok_relative``）：73.7% 真实主文件自带
grammar 空隙 baseline ERROR，绝对判定不可用。``sign()`` 采译前签名、
``validate()`` 传 baseline 得相对判定；位移不影响（按计数比对）。

协议（JSONL，stdin/stdout，每行一记录）::

    {"id": "...", "tex": "<源码>"}            或  {"id": "...", "path": "/abs/x.tex"}
    可选 "expect":  ["MATH_1", ...]            scanner 占位符契约（multiset）
    可选 "baseline": {"parse_errors": N, "env_mismatches": N,
                      "unclosed_math": N, "brace_balance": N}
→   每行一结果：{id, ok, ok_relative?, parse_errors[], env_mismatches[],
                 unclosed_math, brace_balance, placeholders{...}, parse_ms}

worker 双模：默认读完 stdin 批处理（spawn-per-batch，37ms 摊薄）；
``--repl`` 常驻模式逐行即时响应（逐块 spawn 50ms 不可行的替代）。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Self

__all__ = [
    "L1Error",
    "TsBaseline",
    "TsResult",
    "TsValidator",
]

log = logging.getLogger(__name__)

_BATCH_TIMEOUT_S = 30.0  # 批处理 spawn 兜底超时（实测最坏 2.2MB 文件 parse 195ms）

#: node worker 子进程 env 白名单（**非黑名单**）：``dict(os.environ)``
#: 全量继承会把 ``TEXLATE_API_KEY``/``TEXLATE_GATEWAY_KEY`` 等 secret 灌进
#: worker 环境块（``/proc/<pid>/environ``、崩溃转储、孙进程 exec 链均可见）。
#: validator.js 不消费任何业务 env——只经 ``NODE_PATH``（``_env`` 显式注入）
#: 解析 npm 依赖；白名单收敛到 node 启动必需面：PATH（execvp 裸名解析）、
#: HOME、locale、tmpdir 与 Windows MSVCRT 初始化必需的 SystemRoot/WINDIR。
_ENV_PASS_EXACT = frozenset(
    {
        "HOME",
        "PATH",
        "NODE_PATH",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "SystemRoot",
        "WINDIR",
    }
)

#: env 白名单前缀面（locale 家族）。
_ENV_PASS_PREFIX = ("LC_",)


class L1Error(RuntimeError):
    """L1 层不可用/协议错误的统一异常。"""


@dataclass(frozen=True, slots=True)
class TsBaseline:
    """译前源文件签名（相对判定基线）。"""

    parse_errors: int = 0
    env_mismatches: int = 0
    unclosed_math: int = 0
    brace_balance: int = 0

    def to_dict(self) -> dict[str, int]:
        """序列化为协议字段。"""
        return {
            "parse_errors": self.parse_errors,
            "env_mismatches": self.env_mismatches,
            "unclosed_math": self.unclosed_math,
            "brace_balance": self.brace_balance,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TsBaseline:
        """从协议字段反序列化；schema 违例 → ``L1Error``（同 TsResult 契约）。"""
        try:
            return cls(
                parse_errors=int(d.get("parse_errors", 0)),
                env_mismatches=int(d.get("env_mismatches", 0)),
                unclosed_math=int(d.get("unclosed_math", 0)),
                brace_balance=int(d.get("brace_balance", 0)),
            )
        except (TypeError, ValueError, AttributeError, OverflowError) as e:
            msg = f"L1 baseline schema 违例: {e}"
            raise L1Error(msg) from e


@dataclass(slots=True)
class TsResult:
    """L1 单块校验结果（worker JSON 行的 python 形态）。

    ``ok`` 为绝对判定；带 baseline 时 ``ok_relative`` 为生产判定。
    ``parse_errors``/``env_mismatches`` 保留 node 级定位明细（dict 列表）。
    """

    id: str | None = None
    ok: bool = False
    ok_relative: bool | None = None
    parse_errors: list[dict[str, Any]] = field(default_factory=list)
    env_mismatches: list[dict[str, Any]] = field(default_factory=list)
    unclosed_math: int = 0
    brace_balance: int = 0
    placeholders: dict[str, Any] = field(default_factory=dict)
    parse_ms: float = 0.0
    error: str | None = None

    @property
    def verdict_ok(self) -> bool:
        """生产判定：有 baseline 用相对判定，否则用绝对判定。"""
        return self.ok_relative if self.ok_relative is not None else self.ok

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TsResult:
        """从 worker JSON 行反序列化；schema 违例 → ``L1Error``。

        worker 输出违协议即协议错误，统一归 ``L1Error``
        （``_one``/``validate_batch`` 只另兜 ``JSONDecodeError``），不让
        ``TypeError``/``ValueError``/``AttributeError`` 泄出通道契约。
        三段值域显式校验（静默收编会把违例推迟到消费侧炸成下游异常）：

        - ``ok_relative`` 只允许 ``bool | None``——真值串（``"no"``）经
          ``verdict_ok`` 透进聚合判定会 fail-open，不可 ``bool()`` 强转；
        - ``parse_errors``/``env_mismatches`` 逐项须为 dict——
          ``report.feedback()`` 按 ``e.get(...)`` 消费；
        - ``placeholders`` 的 ``missing``/``unexpected``/``typos`` 三键
          须为 list 且 ``typos`` 项为 dict（``expected``/``found`` 计数
          int 键不涉——worker 协议原样放行）。
        """
        try:
            res = cls(
                id=d.get("id"),
                ok=bool(d.get("ok")),
                ok_relative=d.get("ok_relative"),
                parse_errors=list(d.get("parse_errors") or []),
                env_mismatches=list(d.get("env_mismatches") or []),
                unclosed_math=int(d.get("unclosed_math") or 0),
                brace_balance=int(d.get("brace_balance") or 0),
                placeholders=dict(d.get("placeholders") or {}),
                parse_ms=float(d.get("parse_ms") or 0.0),
                error=d.get("error"),
            )
        except (TypeError, ValueError, AttributeError, OverflowError) as e:
            msg = f"L1 worker 响应 schema 违例: {e}"
            raise L1Error(msg) from e
        if res.ok_relative is not None and not isinstance(res.ok_relative, bool):
            msg = (
                f"L1 worker 响应 schema 违例: ok_relative 非 bool: {res.ok_relative!r}"
            )
            raise L1Error(msg)
        for fname, items in (
            ("parse_errors", res.parse_errors),
            ("env_mismatches", res.env_mismatches),
        ):
            if not all(isinstance(x, dict) for x in items):
                msg = f"L1 worker 响应 schema 违例: {fname} 项非 dict"
                raise L1Error(msg)
        ph = res.placeholders
        for key in ("missing", "unexpected", "typos"):
            if key in ph and not isinstance(ph[key], list):
                msg = f"L1 worker 响应 schema 违例: placeholders.{key} 非 list"
                raise L1Error(msg)
        if not all(isinstance(t, dict) for t in ph.get("typos", [])):
            msg = "L1 worker 响应 schema 违例: placeholders.typos 项非 dict"
            raise L1Error(msg)
        return res

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict——``from_dict`` 的对偶（``report.to_dict`` 经此落盘）。

        键集 = ``from_dict`` 消费的协议键全集 + 计算字段 ``verdict_ok``
        （生产判定结果随盘可读，消费侧不必重算 baseline 归并）；
        ``from_dict`` 忽略 ``verdict_ok``，往返无损。
        """
        return {
            "id": self.id,
            "ok": self.ok,
            "ok_relative": self.ok_relative,
            "verdict_ok": self.verdict_ok,
            "parse_errors": self.parse_errors,
            "env_mismatches": self.env_mismatches,
            "unclosed_math": self.unclosed_math,
            "brace_balance": self.brace_balance,
            "placeholders": self.placeholders,
            "parse_ms": self.parse_ms,
            "error": self.error,
        }

    def baseline_signature(self) -> TsBaseline:
        """把本结果当签名用（对 src 跑 validate 后取签名即 baseline）。"""
        return TsBaseline(
            parse_errors=len(self.parse_errors),
            env_mismatches=len(self.env_mismatches),
            unclosed_math=self.unclosed_math,
            brace_balance=self.brace_balance,
        )


def _default_worker_dir() -> Path:
    """包内 ``validate/ts/`` 目录（validator.js + package.json 作 data 分发）。"""
    return Path(str(resources.files("texlate.validate") / "ts"))


class TsValidator:
    """L1 校验器客户端：node 子进程 JSONL 批处理/常驻。

    用法::

        v = TsValidator()
        if v.available():
            base = v.sign(src_tex)                    # 译前签名
            res = v.validate(zh_tex, baseline=base,   # 译后相对判定
                             expect=["MATH_1", ...])
    常驻模式（逐块低开销）::

        with TsValidator() as v:
            res = v.validate(zh, baseline=base)
    """

    def __init__(
        self,
        *,
        node: str | None = None,
        worker_dir: str | Path | None = None,
        node_path: str | Path | None = None,
        timeout: float = _BATCH_TIMEOUT_S,
    ) -> None:
        """解析 node/worker/依赖三方位置；env 覆盖优先于参数默认值。"""
        env_worker = os.environ.get("TEXLATE_TS_WORKER")
        env_node_path = os.environ.get("TEXLATE_TS_NODE_PATH")
        self._node = node or os.environ.get("TEXLATE_NODE") or shutil.which("node")
        self._worker_dir = (
            Path(worker_dir or env_worker)
            if (worker_dir or env_worker)
            else _default_worker_dir()
        )
        self._node_path = (
            Path(node_path or env_node_path)
            if (node_path or env_node_path)
            else self._worker_dir / "node_modules"
        )
        self._timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()

    # ---------------- 可用性 ----------------

    @property
    def worker_js(self) -> Path:
        """Worker 脚本路径。"""
        return self._worker_dir / "validator.js"

    def _deps_present(self) -> bool:
        """两枚 npm 依赖都在场——只查 ``tree-sitter`` 会在文法缺失时误判可用。"""
        return (self._node_path / "tree-sitter").is_dir() and (
            self._node_path / "@pfoerster" / "tree-sitter-latex"
        ).is_dir()

    def available(self) -> bool:
        """Node + worker.js + npm 依赖三者齐备才可用，否则降级 L0。"""
        return bool(self._node and self.worker_js.is_file() and self._deps_present())

    # ---------------- 传输 ----------------

    def _env(self) -> dict[str, str]:
        """Node worker 最小 env：白名单透传 + ``NODE_PATH`` 注入。

        全量 ``os.environ`` 继承会把 secret 写进 worker 环境块——
        validator.js 只经 ``NODE_PATH`` 解析依赖，其余一律不继承
        （白名单表见 ``_ENV_PASS_*``）。
        """
        env = {
            k: v
            for k, v in os.environ.items()
            if k in _ENV_PASS_EXACT or k.startswith(_ENV_PASS_PREFIX)
        }
        env["NODE_PATH"] = str(self._node_path)  # 显式注入盖掉透传值
        return env

    def _require_available(self) -> str:
        if not self._node:
            msg = "node 不在 PATH（L1 不可用，调用方应降级 L0）"
            raise L1Error(msg)
        if not self.worker_js.is_file():
            msg = f"worker 缺失: {self.worker_js}"
            raise L1Error(msg)
        return self._node

    def validate_batch(self, records: list[dict[str, Any]]) -> list[TsResult]:
        """spawn-per-batch：一次 spawn 校验整批（37ms 摊薄 <1ms/块）。

        worker 非零退出或行数与请求数不符 → ``L1Error``（带 stderr 尾巴）——
        空 stdout 若放任返回 ``[]``，调用方 ``[0]`` 取值会泄出 IndexError。
        """
        node = self._require_available()
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        try:
            proc = subprocess.run(  # noqa: S603 - 固定 argv 无 shell
                [node, str(self.worker_js)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                env=self._env(),
            )
        except (OSError, subprocess.SubprocessError) as e:
            msg = f"L1 worker spawn 失败: {e}"
            raise L1Error(msg) from e
        if proc.returncode != 0:
            msg = (
                f"L1 worker 退出码 {proc.returncode}: "
                f"{proc.stderr.strip()[-300:] or '(stderr 空)'}"
            )
            raise L1Error(msg)
        try:
            results = [
                TsResult.from_dict(json.loads(line))
                for line in proc.stdout.splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError as e:
            msg = f"L1 worker 输出非 JSON: {e}"
            raise L1Error(msg) from e
        if len(results) != len(records):
            msg = f"L1 worker 响应数 {len(results)} != 请求数 {len(records)}"
            raise L1Error(msg)
        return results

    # ---------------- 常驻模式（--repl 行协议） ----------------

    def open(self) -> None:
        """启动常驻 worker（逐行 JSONL 即时响应，摊薄后 <1ms/块）。"""
        if self._proc is not None:
            return
        node = self._require_available()
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - 固定 argv 无 shell
                [node, str(self.worker_js), "--repl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                env=self._env(),
            )
        except OSError as e:
            msg = f"L1 常驻 worker 启动失败: {e}"
            raise L1Error(msg) from e
        # 泵线程把 stdout 行喂进队列——``_one`` 不能直接 ``readline()``，
        # 那是无超时阻塞调用，worker 挂起会把整个 pipeline 永久卡死。
        threading.Thread(
            target=self._pump, args=(self._proc, self._lines), daemon=True
        ).start()

    @staticmethod
    def _pump(proc: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
        """把 worker stdout 逐行搬进 ``lines`` 队列；EOF/进程死即线程退。

        退出前投 ``None`` 哨兵唤醒 ``_one`` 等待者——无哨兵时 worker
        崩死会让等待方白挂整个 timeout。
        """
        assert proc.stdout is not None  # noqa: S101 -- Popen 时已声明 PIPE
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    def close(self) -> None:
        """关闭常驻 worker。"""
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.stdin.close()  # type: ignore[union-attr]
                proc.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                proc.kill()

    def __enter__(self) -> Self:
        """启动常驻 worker 进上下文。"""
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        """关闭常驻 worker 出上下文。"""
        self.close()

    # ---------------- 业务 ----------------

    def _drain_lines(self) -> None:
        """清空响应队列里的滞留行（上次超时后迟到的响应会毒害下一请求）。

        残余竞态：迟到行恰好落在 drain 与 write 之间——``_one`` 靠
        ``id`` 配对丢弃这类迟到响应兜底。
        """
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    def _one(self, rec: dict[str, Any]) -> TsResult:
        """常驻通道优先，未启动/进程死退批处理单条。"""
        if self._proc is None or self._proc.stdin is None:
            return self.validate_batch([rec])[0]
        if self._proc.poll() is not None:
            # worker 已退出（上轮 EOF/崩死）——透明降级批处理重起进程
            self.close()
            return self.validate_batch([rec])[0]
        self._drain_lines()
        try:
            self._proc.stdin.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except OSError as e:
            msg = "L1 常驻 worker stdin 已断（进程已退出？）"
            raise L1Error(msg) from e
        want_id = rec.get("id")
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                line = self._lines.get(timeout=max(deadline - time.monotonic(), 0.01))
            except queue.Empty as e:
                self._drain_lines()
                msg = f"L1 常驻 worker 响应超时（{self._timeout}s，进程已退出？）"
                raise L1Error(msg) from e
            if line is None:
                self.close()
                msg = "L1 常驻 worker EOF（进程已退出，响应通道关闭）"
                raise L1Error(msg)
            try:
                res = TsResult.from_dict(json.loads(line))
            except json.JSONDecodeError as e:
                msg = f"L1 常驻 worker 输出非 JSON: {line[:200]!r}"
                raise L1Error(msg) from e
            if res.id == want_id:
                return res
            # 迟到/错序响应（上轮超时残留）——丢弃继续等本请求的配对行

    def sign(self, tex: str, *, doc_id: str | None = None) -> TsBaseline:
        """对译前源文本取签名（相对判定基线）。"""
        res = self._one({"id": doc_id or "baseline", "tex": tex})
        if res.error:
            msg = f"L1 sign 失败: {res.error}"
            raise L1Error(msg)
        return res.baseline_signature()

    def validate(
        self,
        tex: str,
        *,
        baseline: TsBaseline | None = None,
        expect: list[str] | None = None,
        doc_id: str | None = None,
    ) -> TsResult:
        """对译文做单块校验；给 baseline 得 ``ok_relative`` 生产判定。"""
        rec: dict[str, Any] = {"id": doc_id or "chunk", "tex": tex}
        if expect is not None:
            rec["expect"] = expect
        if baseline is not None:
            rec["baseline"] = baseline.to_dict()
        return self._one(rec)
