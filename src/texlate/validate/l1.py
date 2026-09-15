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
  prebuilt）随包作 data；首次 ``ensure_deps()`` 跑 ``npm i --prefix``（~5s）；
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
import os
import shutil
import subprocess
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

_BATCH_TIMEOUT_S = 30.0  # 批处理 spawn 兜底超时（实测最坏 2.2MB 文件 parse 195ms）


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
        """从协议字段反序列化。"""
        return cls(
            parse_errors=int(d.get("parse_errors", 0)),
            env_mismatches=int(d.get("env_mismatches", 0)),
            unclosed_math=int(d.get("unclosed_math", 0)),
            brace_balance=int(d.get("brace_balance", 0)),
        )


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
        """从 worker JSON 行反序列化。"""
        return cls(
            id=d.get("id"),
            ok=bool(d.get("ok")),
            ok_relative=d.get("ok_relative"),
            parse_errors=list(d.get("parse_errors") or []),
            env_mismatches=list(d.get("env_mismatches") or []),
            unclosed_math=int(d.get("unclosed_math", 0)),
            brace_balance=int(d.get("brace_balance", 0)),
            placeholders=dict(d.get("placeholders") or {}),
            parse_ms=float(d.get("parse_ms", 0.0)),
            error=d.get("error"),
        )

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

    # ---------------- 可用性 ----------------

    @property
    def worker_js(self) -> Path:
        """Worker 脚本路径。"""
        return self._worker_dir / "validator.js"

    def available(self) -> bool:
        """Node + worker.js + npm 依赖三者齐备才可用，否则降级 L0。"""
        return bool(
            self._node
            and self.worker_js.is_file()
            and (self._node_path / "tree-sitter").is_dir()
        )

    def ensure_deps(self) -> bool:
        """依赖缺失时 ``npm i --prefix`` 一次性安装；成功返回 True。"""
        if (self._node_path / "tree-sitter").is_dir():
            return True
        npm = shutil.which("npm")
        if not (self.worker_js.is_file() and npm):
            return False
        try:
            subprocess.run(  # noqa: S603 - 固定 argv 无 shell
                [npm, "i", "--prefix", str(self._worker_dir)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return (self._node_path / "tree-sitter").is_dir()

    # ---------------- 传输 ----------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["NODE_PATH"] = str(self._node_path)
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
        """spawn-per-batch：一次 spawn 校验整批（37ms 摊薄 <1ms/块）。"""
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
        return [
            TsResult.from_dict(json.loads(line))
            for line in proc.stdout.splitlines()
            if line.strip()
        ]

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

    def _one(self, rec: dict[str, Any]) -> TsResult:
        """常驻通道优先，未启动退批处理单条。"""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            return self.validate_batch([rec])[0]
        self._proc.stdin.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            msg = "L1 常驻 worker 无响应（进程已退出？）"
            raise L1Error(msg)
        return TsResult.from_dict(json.loads(line))

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
