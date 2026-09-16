"""BabelDOC sidecar spawn 契约（docs/research/latex/pdf-path.md §三/§五）。

无 LaTeX 源论文的 PDF 降级翻译通路：把 ``babeldoc`` CLI 包成
「提交 → 进度 → 产物 → fallback 判定」壳。进程边界 = AGPL 边界——
babeldoc 不进产品 venv/import，只 spawn CLI。关键约定：

- ``--working-dir`` 必传 → ``translate_tracking.json`` 落盘
  （``<workdir>/<src-stem>/``，translation_config.py:287-298 内层
  追加 stem）——静默 fallback（出错保原文的假成功）唯一可靠检测面。
- **不传 ``--max-pages-per-part``**：split 模式 ``part_{i}/`` 工
  作目录在 finally 里被 rmtree（high_level.py:669-671），part 级
  tracking 随之销毁 → 宁可整文档单跑。
- ``--no-send-temperature`` 默认：请求体不带 temperature，绕开
  网关 400（pdf-path.md §1.1 冒烟坑①）。
- api_key 写 ``-c`` TOML（configargparse ``[babeldoc]`` 节，
  main.py:36-41），不进 argv → ``ps`` 不可见；文件 0600 落 workdir。
- babeldoc 的 rich Progress 与 ``RichHandler`` 日志都写 **stdout**
  （main.py:809 ``Progress()`` 无 console 参 + ``basicConfig(
  handlers=[RichHandler()])`` 默认 stdout）——只接 stderr 会丢全部
  进度帧与 ``Total tokens:`` 统计行。故 spawn 把 stdout+stderr
  合并进同一 pty（不可用则 stdout→stderr PIPE 合并），喂给
  同一 ``_Feed``；pty  tty 语义让 rich Live 产增量帧，刮
  ``translate`` 行 ``N/100``。
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

log = logging.getLogger(__name__)

try:
    import pty
except ImportError:  # Windows：无 pty → 退化纯管道模式
    pty = None  # type: ignore[assignment]

#: 整单默认超时（``TEXLATE_BABELDOC_TIMEOUT`` 秒覆盖）
DEFAULT_TIMEOUT_S = 3600.0

#: stderr pump 读块 / poll 周期
_PUMP_CHUNK = 65536
_POLL_S = 0.5

#: tracking 统计采样上限（error_samples 只留前几条供 triage）
_MAX_ERROR_SAMPLES = 3

#: CJK 兜底 sanity 阈值：zh 目标 mono PDF 抽文本 CJK 占比低于此 → degraded
#: （层级③单段异常吞没不进 tracking，唯一旁证是产物文本本身）
_CJK_MIN_RATIO = 0.10

#: target_lang → ``--lang-out``；zh-TW 让字体族选 TW（embedding_assets_metadata
#: get_font_family 按 CN/TW/HK 子串分），未知值原样透传
_LANG_OUT = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "en": "en"}

#: babeldoc stderr 信号面
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|[()][0-2A-B]|[=>#][0-9]?|\][^\x1b\x07]*(?:\x07|\x1b\\))"
)
#: rich ``translate`` 总行（desc 恰为 "translate"，total=100 → N/100 即总进度）；
#: 首列精确小写「translate」，Stage 行是 Title Case 不误伤
_OVERALL_RE = re.compile(r"^translate\b.*?(\d+(?:\.\d+)?)\s*/\s*100")
#: tqdm 兜底形（``use_rich_pbar=False`` 的调用方才产）：``NN%|``
_TQDM_RE = re.compile(r"^(\d{1,3})\s*%\|")
#: stage 行：``Stage Name (i/n) ━━━ cur/total`` 或 tqdm ``Stage (c/t): NN%|``
_STAGE_ROW_RE = re.compile(r"^([^\s(][^()]*?)\s*\(\d+\s*/\s*\d+\)")
#: 尾部统计行（main.py:772-784 logger.info）
_STAT_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("total_tokens", re.compile(r"Total tokens:\s*(\d+)")),
    ("prompt_tokens", re.compile(r"Prompt tokens:\s*(\d+)")),
    ("completion_tokens", re.compile(r"Completion tokens:\s*(\d+)")),
    ("cache_hit_prompt_tokens", re.compile(r"Cache hit prompt tokens:\s*(\d+)")),
    ("peak_memory_mb", re.compile(r"Peak memory usage:\s*([\d.]+)\s*MB")),
)
#: 翻译段汇总行（il_translator_llm_only.py:256）
_COMPLETED_RE = re.compile(
    r"Translation completed\.\s*Total:\s*(\d+),"
    r"\s*Successful:\s*(\d+),\s*Fallback:\s*(\d+)"
)
_SCANNED_RE = re.compile(r"ScannedPDFError|Scanned PDF detected", re.IGNORECASE)
_ERROR_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"translate error:\s*(.+)", re.IGNORECASE),
    re.compile(r"progress_monitor handle translate_error:\s*(.+)", re.IGNORECASE),
    re.compile(r"Error in part \d+:\s*(.+)", re.IGNORECASE),
    re.compile(r"Error:\s*(.+)"),
)
_RATE_RE = re.compile(r"RateLimitError|too many requests|\b429\b", re.IGNORECASE)
_AUTH_RE = re.compile(
    r"AuthenticationError|Incorrect API key|invalid api key|\b401\b", re.IGNORECASE
)


def lang_out_for(target_lang: str) -> str:
    """产品 ``target_lang`` → babeldoc ``--lang-out``（未知 → ``zh-CN``）。"""
    return _LANG_OUT.get(target_lang, "zh-CN")


def default_timeout() -> float:
    """``TEXLATE_BABELDOC_TIMEOUT`` 秒；非法/缺省 → ``DEFAULT_TIMEOUT_S``。"""
    try:
        v = float(os.environ.get("TEXLATE_BABELDOC_TIMEOUT", "") or 0)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return v if v > 0 else DEFAULT_TIMEOUT_S


@dataclass(slots=True)
class BabeldocJob:
    """一单 ``babeldoc`` CLI 调用的全部入参。"""

    src: Path
    outdir: Path
    workdir: Path
    model: str
    base_url: str
    api_key: str = ""
    lang_in: str = "en"
    lang_out: str = "zh-CN"
    qps: int = 4
    pages: str | None = None
    dual: bool = True
    mono: bool = True
    alternating: bool = True
    send_temperature: bool = False
    custom_system_prompt: str | None = None
    glossary_csv: Path | None = None
    timeout: float = DEFAULT_TIMEOUT_S


@dataclass(slots=True)
class BabeldocRun:
    """spawn 结果：退出码 + 产物路径 + fallback 判定 + 统计。"""

    rc: int
    seconds: float
    status: str  # "ok" | "degraded" | "failed"
    error_code: str | None = None
    error: str = ""
    retryable: bool = True
    outputs: dict[str, Path] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    stderr_tail: str = ""


def write_config(job: BabeldocJob) -> Path:
    """``[babeldoc] openai-api-key`` TOML（0600）——key 不进 argv/ps。

    空 key 落 ``"texlate"`` 占位：CLI 层 ``parser.error`` 要求非空
    （main.py:499-500）；默认本地网关不校验，真 provider 空 key 会
    在上游 401 如实报错。
    """
    cfg = job.workdir / "babeldoc.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        f"[babeldoc]\nopenai-api-key = {json.dumps(job.api_key or 'texlate')}\n",
        encoding="utf-8",
    )
    cfg.chmod(0o600)
    return cfg


def _openai_sdk_root(base_url: str) -> str:
    """产品裸服务根 → openai SDK ``base_url``（``{root}/v1``）。

    babeldoc 把 ``--openai-base-url`` 直接喂 ``openai.OpenAI(base_url=…)``，
    SDK 在其上拼 ``chat/completions``——缺版本段会打 ``/chat/completions``
    被网关 404；与 ``ChatClient`` 的 ``{root}/v1/chat/completions`` 约定对齐。
    """
    v = base_url.strip().rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        v = v.removesuffix(suffix)
    return f"{v}/v1"


def build_argv(job: BabeldocJob, binary: str) -> list[str]:
    """Spawn argv。``--max-pages-per-part`` 有意缺席——见模块 docstring。"""
    argv = [
        binary,
        "--files",
        str(job.src),
        "--output",
        str(job.outdir),
        "--working-dir",
        str(job.workdir),
        "--lang-in",
        job.lang_in,
        "--lang-out",
        job.lang_out,
        "--openai",
        "--openai-model",
        job.model,
        "--qps",
        str(job.qps),
        "--watermark-output-mode",
        "no_watermark",
        "-c",
        str(job.workdir / "babeldoc.toml"),
    ]
    if job.base_url:
        argv += ["--openai-base-url", _openai_sdk_root(job.base_url)]
    if not job.send_temperature:
        argv.append("--no-send-temperature")
    if not job.dual:
        argv.append("--no-dual")
    if not job.mono:
        argv.append("--no-mono")
    if job.alternating:
        argv.append("--use-alternating-pages-dual")
    if job.pages:
        argv += ["--pages", job.pages]
    if job.custom_system_prompt:
        argv += ["--custom-system-prompt", job.custom_system_prompt]
    if job.glossary_csv is not None:
        argv += ["--glossary-files", str(job.glossary_csv)]
    return argv


def write_glossary_csv(path: Path, terms: list[tuple[str, str]]) -> Path | None:
    """主链术语对 → babeldoc ``source,target`` CSV（DictReader 要表头）。

    空表不落盘返回 None——``--glossary-files`` 不指则不传。
    """
    if not terms:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "tgt_lng"])
        w.writerows((en, zh, "") for en, zh in terms)
    return path


def tracking_paths(workdir: Path, stem: str) -> list[Path]:
    """``translate_tracking.json`` 候选位。

    主 ``<workdir>/<stem>/`` + ``part_*/`` 兜底（理论上被我们关掉的
    split 路径防御性兜住）。
    """
    base = workdir / stem
    out: list[Path] = []
    main = base / "translate_tracking.json"
    if main.is_file():
        out.append(main)
    out.extend(sorted(base.glob("part_*/translate_tracking.json")))
    return out


def _count_trackers(data: dict[str, Any], samples: list[str]) -> tuple[int, int, int]:
    """单份 tracking JSON → ``(total, errors, fallbacks)``；错误样本就地追加。"""
    total = errors = fallbacks = 0
    for section in ("page", "cross_page", "cross_column"):
        for page in data.get(section) or []:
            for para in page.get("paragraph") or []:
                for t in para.get("llm_translate_trackers") or []:
                    total += 1
                    if t.get("has_error"):
                        errors += 1
                        msg = str(t.get("error_message") or "").strip()
                        if msg and len(samples) < _MAX_ERROR_SAMPLES:
                            samples.append(msg[:200])
                    if t.get("fallback_to_translate"):
                        fallbacks += 1
    return total, errors, fallbacks


def assess_tracking(workdir: Path, stem: str) -> dict[str, Any]:
    """Tracking JSON → ``{total, errors, fallbacks, error_samples, found}``。

    schema（il_translator.py:167-188,318-326）：
    ``{page|cross_page|cross_column: [{paragraph: [{llm_translate_trackers:
    [{has_error,error_message,fallback_to_translate,...}]}]}]}``。
    """
    total = errors = fallbacks = 0
    samples: list[str] = []
    paths = tracking_paths(workdir, stem)
    for tp in paths:
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("babeldoc tracking json 不可读: %s", tp)
            continue
        if not isinstance(data, dict):
            continue
        t, e, f = _count_trackers(data, samples)
        total += t
        errors += e
        fallbacks += f
    return {
        "total": total,
        "errors": errors,
        "fallbacks": fallbacks,
        "error_samples": samples,
        "tracking_found": bool(paths),
    }


def cjk_ratio(pdf_path: Path, *, max_pages: int = 8) -> float | None:
    """Mono PDF 前 N 页 CJK/(CJK+拉丁 alpha) 占比——静默吞段的产物面兜底。

    缺库/坏文件 → ``None``（sanity 信号永不炸主链）。
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载

        cjk = alpha = 0
        for page in PdfReader(str(pdf_path)).pages[:max_pages]:
            for ch in page.extract_text() or "":
                if "㐀" <= ch <= "䶿" or "一" <= ch <= "鿿":
                    cjk += 1
                elif ch.isalpha():
                    alpha += 1
    except Exception:  # noqa: BLE001 -- sanity 信号失败不升级
        return None
    total = cjk + alpha
    return cjk / total if total else 0.0


class _Feed:
    r"""stderr 字节流 → 进度/统计/错误/日志尾。

    帧边界 = ``\r``/``\n``：rich Live 每帧 = ANSI 光标控制 + 重绘表
    （\r 分隔），tqdm/日志行走 \n。剥 ANSI 后逐条归类；回调在
    消费线程（worker 的 loop 线程）触发。``on_log`` 只收真实日志
    行——进度帧（rich 表重绘/tqdm 行）走 ``on_progress``，不进
    日志流（否则每帧重绘都是一条 SSE log，噪声淹没有效行）。
    """

    def __init__(
        self,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.on_progress = on_progress
        self.on_log = on_log
        self.stats: dict[str, Any] = {}
        self.errors: list[str] = []
        self.scanned = False
        self.stage = ""
        self.progress = -1.0
        self._carry = b""
        self._tail: list[str] = []

    def feed(self, data: bytes) -> None:
        """吞新字节，切帧派发。"""
        *recs, self._carry = re.split(rb"[\r\n]+", self._carry + data)
        for raw in recs:
            self._record(raw)

    def flush(self) -> None:
        """EOF：收尾帧。"""
        if self._carry:
            self._record(self._carry)
            self._carry = b""

    @property
    def tail(self) -> str:
        """末 40 条剥码文本行（拼尾/错误信息用）。"""
        return "\n".join(self._tail)

    def _record(self, raw: bytes) -> None:
        text = _ANSI_RE.sub("", raw.decode("utf-8", "replace")).strip()
        if not text:
            return
        self._tail.append(text)
        del self._tail[:-40]
        if _SCANNED_RE.search(text):
            self.scanned = True
        self._collect(text)
        if not self._progress(text) and self.on_log is not None:
            self.on_log(text)

    def _collect(self, text: str) -> None:
        """完成行/统计行/错误行采集（不消费——错误行仍是有效日志行）。"""
        m = _COMPLETED_RE.search(text)
        if m:
            self.stats["translate_total"] = int(m.group(1))
            self.stats["translate_ok"] = int(m.group(2))
            self.stats["translate_fallback"] = int(m.group(3))
            return
        for key, rx in _STAT_RES:
            m = rx.search(text)
            if m:
                v = m.group(1)
                self.stats[key] = float(v) if "." in v else int(v)
                return
        for rx in _ERROR_RES:
            m = rx.search(text)
            if m:
                msg = m.group(1).strip()
                if msg and msg not in self.errors:
                    self.errors.append(msg[:300])

    def _progress(self, text: str) -> bool:
        """进度帧判定：``translate N/100`` / tqdm ``NN%|`` / stage 表行。"""
        om = _OVERALL_RE.match(text) or _TQDM_RE.match(text)
        sm = _STAGE_ROW_RE.match(text)
        if sm is not None and om is None:
            name = sm.group(1).strip()
            if name.lower() != "translate":
                self.stage = name
        if om is not None:
            pct = float(om.group(1))
            if pct != self.progress:
                self.progress = pct
                if self.on_progress is not None:
                    self.on_progress(pct, self.stage)
        return om is not None or sm is not None


def _pump_fd(fd: int, buf: bytearray, lock: threading.Lock) -> None:
    """Pty master → buf（阻塞读到 EOF；EIO = 对侧已关，当 EOF）。"""
    try:
        while True:
            try:
                chunk = os.read(fd, _PUMP_CHUNK)
            except OSError:
                break
            if not chunk:
                break
            with lock:
                buf += chunk
    finally:
        os.close(fd)


async def _pump_stream(
    stream: asyncio.StreamReader | None,
    buf: bytearray,
    lock: threading.Lock,
) -> None:
    """PIPE stderr → buf。"""
    if stream is None:
        return
    while chunk := await stream.read(_PUMP_CHUNK):
        with lock:
            buf += chunk


def _classify_rc(feed: _Feed) -> tuple[str, str, bool]:
    """非零退出码 → ``(code, message, retryable)``。"""
    tail = feed.tail
    msg = feed.errors[-1] if feed.errors else tail.strip().splitlines()[-1:]
    text = msg if isinstance(msg, str) else (msg[0] if msg else "")
    if _AUTH_RE.search(tail):
        return "provider_auth", text or "LLM 凭证被拒", False
    if _RATE_RE.search(tail):
        return "provider_rate", text or "上游限流", True
    return "compile", text or "babeldoc 未产出译文 pdf", True


def harvest_outputs(job: BabeldocJob) -> dict[str, Path]:
    """产物面收割（pdf_creater.py:1449-1457 + result_merger.py:29-38）：

    ``{stem}[.debug][.no_watermark].{lang_out}.{mono|dual}.pdf``
    + ``{stem}[.no_watermark].{lang_out}.glossary.csv`` + tracking json。
    本壳固定 ``no_watermark`` 模式 → 带 ``.no_watermark.`` 中缀的名优先。
    """
    stem = job.src.stem
    pat = f"{glob_escape(stem)}*.{glob_escape(job.lang_out)}."
    pdfs = sorted(job.outdir.glob(f"{pat}*.pdf"))
    out: dict[str, Path] = {}

    def pick(kind: str) -> Path | None:
        cands = [p for p in pdfs if p.name.endswith(f".{kind}.pdf")]
        for p in cands:
            if ".no_watermark." in p.name:
                return p
        return cands[0] if cands else None

    if (m := pick("mono")) is not None:
        out["mono"] = m
    if (d := pick("dual")) is not None:
        out["dual"] = d
    csvs = sorted(job.outdir.glob(f"{pat}glossary.csv"))
    if csvs:
        out["glossary_csv"] = csvs[0]
    tracks = tracking_paths(job.workdir, stem)
    if tracks:
        out["tracking"] = tracks[0]
    return out


def glob_escape(s: str) -> str:
    """``glob.escape`` 的窄封装（import 面内聚一处）。"""
    import glob  # noqa: PLC0415 -- 单次调用不值模块级 import

    return glob.escape(s)


def _judge_run(  # noqa: PLR0913, PLR0911 -- 退出码判定表平铺即 §三 assess 契约
    job: BabeldocJob,
    *,
    rc: int,
    timed_out: bool,
    feed: _Feed,
    outputs: dict[str, Path],
    track: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[str, str | None, str, bool]:
    """退出后判定 → ``(status, error_code, error, retryable)``（§三 assess）。"""
    if timed_out:
        return "failed", "timeout", f"babeldoc 超时（{int(job.timeout)}s）", True
    if feed.scanned:
        return (
            "failed",
            "scanned_pdf",
            "扫描件/OCR PDF（BabelDOC 拒收，走 OCR 兜底通路）",
            False,
        )
    if rc != 0:
        code, msg, retryable = _classify_rc(feed)
        return "failed", code, msg, retryable
    if not outputs.get("mono") and not outputs.get("dual"):
        return "failed", "compile", "babeldoc 未产出译文 pdf", True
    total, errors, fallbacks = (
        track["total"],
        track["errors"],
        track["fallbacks"],
    )
    if total and errors >= total * 0.5:
        # 过半段出错 → 判失败（pdf-path.md §三 assess）
        err = (
            track["error_samples"][0]
            if track["error_samples"]
            else f"{errors}/{total} 段落翻译失败"
        )
        return "failed", "babeldoc_translate", err, True
    if errors or fallbacks:
        return "degraded", None, f"{errors} 段出错 / {fallbacks} 段回退保原文", True
    if (
        feed.stats.get("total_tokens") == 0
        and feed.stats.get("cache_hit_prompt_tokens", 0) == 0
        and total == 0
    ):
        # 一次 API 都没打出去（全 cache 命中时 cache_hit>0 不误伤）
        return "failed", "zero_tokens", "babeldoc 未发起任何翻译调用", True
    if job.lang_out.startswith("zh") and (mono := outputs.get("mono")) is not None:
        ratio = cjk_ratio(mono)
        if ratio is not None and ratio < _CJK_MIN_RATIO:
            stats["cjk_ratio"] = round(ratio, 4)
            return (
                "degraded",
                None,
                f"产物 CJK 占比 {ratio:.2f} 过低（疑似整文未译）",
                True,
            )
    return "ok", None, "", True


async def _spawn(
    argv: list[str],
) -> tuple[asyncio.subprocess.Process, int | None]:
    """开 pty（可用时）+ spawn → ``(proc, master_fd)``；退化期 master=None。

    父进程侧 slave 副本在 spawn 后立即关——子进程已 dup 走自己的
    stderr；留着它 master 在子退出后读不到 EIO，泵线程死等。
    """
    env = dict(os.environ)
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("TERM", "xterm")  # pty 模式下 rich 需要
    env["PYTHONUNBUFFERED"] = "1"
    master: int | None = None
    slave: int | None = None
    # babeldoc 的进度/日志走 stdout（见模块 docstring）——pty 模式
    # stdout+stderr 同挂 slave；PIPE 退化期 stdout 并入 stderr 流。
    stderr_tgt: Any = asyncio.subprocess.PIPE
    stdout_tgt: Any = asyncio.subprocess.STDOUT
    if pty is not None:
        try:
            master, slave = pty.openpty()
            # openpty 给 0×0 winsize——rich 按 fallback 窄宽渲染会把
            # ``52/100`` 截成 ``52/…``，刮不到进度。钉 120×24。
            import fcntl  # noqa: PLC0415 -- POSIX-only，pty 分支内惰性
            import struct  # noqa: PLC0415
            import termios  # noqa: PLC0415

            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))
            stderr_tgt = slave
            stdout_tgt = slave
        except OSError:
            master = slave = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout_tgt,
            stderr=stderr_tgt,
            env=env,
        )
    except Exception:
        if master is not None:
            os.close(master)
        raise
    finally:
        if slave is not None:
            os.close(slave)
    return proc, master


def _start_pump(
    proc: asyncio.subprocess.Process,
    master: int | None,
    buf: bytearray,
    lock: threading.Lock,
) -> asyncio.Task[None]:
    """起 stderr 泵任务：pty 走 ``to_thread`` 阻塞读，PIPE 走 StreamReader。"""
    if master is not None:
        return asyncio.create_task(asyncio.to_thread(_pump_fd, master, buf, lock))
    return asyncio.create_task(_pump_stream(proc.stderr, buf, lock))


async def run_babeldoc(
    job: BabeldocJob,
    *,
    binary: str,
    on_progress: Callable[[float, str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> BabeldocRun:
    """Spawn → stderr 刮取 → 产物收割 → fallback 判定（pdf-path §三 assess）。

    ``should_cancel`` 真 → kill + ``CancelledError``（worker 段边界
    收敛同一语义）。超时 kill → ``status="failed"`` ``error_code=
    "timeout"``。
    """
    job.outdir.mkdir(parents=True, exist_ok=True)
    job.workdir.mkdir(parents=True, exist_ok=True)
    write_config(job)
    argv = build_argv(job, binary)

    feed = _Feed(on_progress=on_progress, on_log=on_log)
    t0 = time.monotonic()
    proc, master = await _spawn(argv)
    buf = bytearray()
    lock = threading.Lock()
    pump = _start_pump(proc, master, buf, lock)

    timed_out, cursor = False, 0
    deadline = t0 + job.timeout

    def drain() -> None:
        nonlocal cursor
        with lock:
            chunk = bytes(buf[cursor:])
            cursor = len(buf)
        if chunk:
            feed.feed(chunk)

    try:
        while proc.returncode is None:
            await asyncio.sleep(_POLL_S)
            drain()
            if should_cancel is not None and should_cancel():
                proc.kill()
                await proc.wait()
                raise asyncio.CancelledError
            if time.monotonic() > deadline:
                timed_out = True
                proc.kill()
                await proc.wait()
                break
    finally:
        if proc.returncode is None:
            # 外部 cancel/异常逃出：子进程不能留孤儿
            proc.kill()
            await proc.wait()
        try:
            await asyncio.wait_for(asyncio.shield(pump), timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            pump.cancel()
        drain()
        feed.flush()

    seconds = time.monotonic() - t0
    outputs = harvest_outputs(job)
    track = assess_tracking(job.workdir, job.src.stem)
    stats: dict[str, Any] = {
        **feed.stats,
        "seconds": round(seconds, 1),
        "paragraphs": track["total"],
        "error_paragraphs": track["errors"],
        "fallback_paragraphs": track["fallbacks"],
        "tracking_found": track["tracking_found"],
    }

    status, error_code, error, retryable = _judge_run(
        job,
        rc=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        feed=feed,
        outputs=outputs,
        track=track,
        stats=stats,
    )

    return BabeldocRun(
        rc=proc.returncode if proc.returncode is not None else -1,
        seconds=seconds,
        status=status,
        error_code=error_code,
        error=error,
        retryable=retryable,
        outputs=outputs,
        stats=stats,
        stderr_tail=feed.tail[-2048:],
    )
