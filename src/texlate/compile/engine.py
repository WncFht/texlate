r"""引擎层：Engine 协议 + xelatex/tectonic 实现 + 静态路由表（docs/08 §4）。

- Engine 协议（§4.1）：`detect/compile/probe_file/install_file/rebuild_fontmaps/
  filemap/parse_log` + `caps` 能力集——fixloop 按 caps 降级（tectonic 无
  tlmgr/kpsewhich/updmap，走 ctan_fetch 原语，见 §5.3）。
- 命令行（§4.1）：xelatex `-no-shell-escape -interaction=nonstopmode
  [-halt-on-error] -file-line-error -recorder` ≤2 pass；tectonic `-X compile
  --untrusted -Z continue-on-errors --keep-logs --keep-intermediates
  --makefile-rules`（continue-on-errors 对齐 nonstopmode 语义——tectonic
  默认 halt-on-error，engine-matrix §0 已实证）。
- 静态路由（§4.2）：`route_project` 编译前决策；失败集互补实测联合 clean
  9/12（engine-matrix §0）。
- log 解析（§2.3）：`parse_log` 双格式错误计数（`^!` + `file:line:`）、
  `l.NNN` 行号、`(` 文件栈、tail；tectonic 有时不写 .log → stderr 兜底。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

from texlate.texlog import update_file_stack
from texlate.textutil import decode_tex

from .mask import visible_tex
from .sandbox import child_env, find_tool, run_process, sandbox_wrap

DEFAULT_TIMEOUT = 240.0  # docs/08 §4.1
MAX_PASSES = 2
_TECTONIC_ATTEMPTS = 2  # 冷 bundle 首拉超时后重试（缓存热身）

#: tectonic bundle pin（docs/08 §4.1）；None = 引擎自带默认 bundle。
#: 可用 env TEXLATE_TEX_BUNDLE 或构造参数覆盖。
TECTONIC_BUNDLE_PIN = "https://data1b.fullyjustified.net/tlextras-2022.0r0.tar"


# ================================================================ 数据类型
@dataclass
class LogInfo:
    """`parse_log` 产物：错误计数、首错+上下文、tail、文件栈。"""

    n_errors: int = 0
    first_error: str | None = None
    error_ctx: str | None = None
    error_line: int | None = None  # l.NNN
    file_stack: list[str] = field(default_factory=list)
    tail: str = ""
    errors: list[str] = field(default_factory=list)  # 全部 '^!'/'file:line:' 行
    warnings_hit: list[str] = field(default_factory=list)  # judge 红线命中


@dataclass
class CompRes:
    """一次编译调用的完整结果（clean 判定原料 + fixloop 输入）。"""

    engine: str
    ok: bool = False  # 进程正常跑完（非超时/启动失败）
    pdf: Path | None = None
    pdf_bytes: int = 0
    log_path: Path | None = None
    log: LogInfo = field(default_factory=LogInfo)
    timed_out: bool = False
    seconds: float = 0.0
    passes: int = 0
    rc: int | None = None
    stdout_tail: str = ""
    deps: list[str] | None = None  # compiled_dependencies（.fls/.mk 权威输入集）

    @property
    def has_pdf(self) -> bool:
        """是否产出非空 PDF。"""
        return self.pdf is not None and self.pdf_bytes > 0


# ================================================================ log 解析
_ERR_BANG_RE = re.compile(r"^!")
_ERR_FILELINE_RE = re.compile(r"^\S+?:\d+: \S")  # -file-line-error 引擎级错误
#: ``file:line:`` 形态的非错误行（与 fixloop/logparse 同口径）：
#: Warning 行（警告也带 file:line: 前缀时不能计入错误）与
#: ``==> Fatal error occurred`` 汇总尾行（同一失败的复述，多计一次）。
_NONERR_FILELINE_RE = re.compile(
    r"^\S+?:\d+:\s*(?:(?:LaTeX|Package|Class)\b[^\n]*?\bWarning\b|==>)"
)
_L_NUM_RE = re.compile(r"^l\.(\d+)")

#: clean 判据的 log warning 红线（docs/08 §4.3）：任一命中即 dirty。
WARNING_RED_LINES: list[tuple[str, str]] = [
    ("invalid_utf8", r"Invalid UTF-8 byte"),
    ("fffd_glyph", r"Missing character:[^\n]*U\+FFFD"),
    ("missing_chars", r"Missing character: There is no"),
    (
        "missing_graphic",
        (
            r"File `[^']+\.(?:pdf|png|jpg|jpeg|eps|mps|bb)' not found"
            r"|Cannot determine size of graphic|Unknown graphics extension"
        ),
    ),
    # tectonic 缺包静默降级行（continue-on-errors 把 missing .sty 降级为可恢复，
    # 跳包继续出残页 pdf——engine-matrix §7.4 的暗雷）
    ("degraded_file", r"^!.*(?:File|package)[^\n]*not found"),
]


def _scan_error_lines(lines: list[str], info: LogInfo) -> int:
    """数 `^!`+`file:line:` 错误、记首错位置、追踪 `(` 文件栈。返回首错行号。"""
    ctx_start = -1
    stack: list[str | None] = []
    for i, ln in enumerate(lines):
        update_file_stack(ln, stack)
        if _ERR_BANG_RE.match(ln) or (
            _ERR_FILELINE_RE.match(ln) and not _NONERR_FILELINE_RE.match(ln)
        ):
            info.n_errors += 1
            info.errors.append(ln.strip()[:300])
            if info.first_error is None:
                info.first_error = ln.strip()
                ctx_start = i
                info.file_stack = [s for s in stack if s]
    return ctx_start


def parse_log(log_text: str) -> LogInfo:
    """解析 TeX log 文本 → LogInfo（引擎无关；调用方负责拿文本）。

    错误计数**双格式**：`^!` 行 + `file:line:` 行（只数 `!` 会漏掉
    `-file-line-error` 模式下引擎级错误，docs/08 §2.3）。
    """
    info = LogInfo()
    if not log_text:
        return info
    lines = log_text.splitlines()
    ctx_start = _scan_error_lines(lines, info)
    if ctx_start >= 0:
        ctx_lines = []
        for j in range(ctx_start, min(ctx_start + 9, len(lines))):
            ctx_lines.append(lines[j])
            if info.error_line is None:
                m = _L_NUM_RE.match(lines[j].strip())
                if m:
                    info.error_line = int(m.group(1))
        info.error_ctx = "\n".join(ctx_lines)
    info.tail = "\n".join(lines[-30:])
    info.warnings_hit = [
        name
        for name, pat in WARNING_RED_LINES
        if re.search(pat, log_text, re.MULTILINE)
    ]
    return info


# ================================================================ 错误分类学
#: 首错/上下文 → 类别 的有序规则表（首个命中即返回）。
_ERROR_RULES: tuple[tuple[str, str], ...] = (
    ("missing_file", r"File `([^']+\.[a-zA-Z0-9]+)' not found"),
    ("missing_file", r"I can't find file `([^']+)'"),
    ("missing_tfm", r"Font \\?\S*?=?\s*([a-zA-Z0-9]+) at [0-9.]+pt not loadable"),
    ("missing_tfm", r"Metric \(TFM\) file[^\n]*?(\w+)\.(tfm)"),
    ("xetexglyph_tfm", r"Cannot use XeTeXglyph with (\S+)"),
    ("missing_pfb", r"Cannot proceed without .vf|physical font"),
    ("fontspec_missing", r'font [“"]([^”"]+)[”"] cannot be found'),
    ("eps_image", r"image inclusion failed for[^\n]*\.eps|PostScript image"),
    ("illegal_unit", r"Illegal unit of measure"),
    ("option_clash", r"Option clash for package ([\w-]+)"),
    ("already_def", r"Command \\?([\w@]+) already defined"),
    ("soul_err", r"Package soul Error|Reconstruction failed"),
    ("hyphenation", r"Not a letter"),
    ("minted_froz", r"frozencache|Cannot highlight code"),
    (
        "latex209",
        r"documentstyle|LaTeX ?2\.09|LaTeX2e command .* in LaTeX 2\.09",
    ),
    ("undefined_cs", r"Undefined control sequence"),
    ("capacity", r"TeX capacity exceeded"),
    ("emergency", r"Emergency stop|cannot \\read|Fatal error|job aborted"),
    ("env_mismatch", r"begin\{[^}]*\}.*ended by|Extra \\end"),
    (
        "syntax",
        (
            r"Missing|Runaway|Paragraph ended|Misplaced|Double subscript|"
            r"Illegal|There's no line|Lonely|Bad math|Something's wrong|"
            r"not in outer par|allowed only in math|improper"
        ),
    ),
    ("other", r"^!"),
)


def _match_head(head: str) -> tuple[str, str | None] | None:
    """首错上下文按 `_ERROR_RULES` 顺序匹配；undefined_cs 细分 pdf* 原语。"""
    for name, pat in _ERROR_RULES:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            pay = next((g for g in m.groups() if g), None)
            if name == "undefined_cs":
                pm = re.search(r"\\(pdf[a-zA-Z@]+)", head)
                if pm:
                    return "pdftex_prim", pm.group(1)
            return name, pay
    return None


def _match_tail(blob: str) -> tuple[str, str | None] | None:
    """无 `!` 行或首错即 emergency 时，回溯 tail 找文件名提示符。"""
    m = re.search(r"File `([^']+\.[a-zA-Z0-9]+)' not found", blob)
    if m and ("Enter file name" in blob or "Emergency" in blob):
        return "missing_file", m.group(1)
    if "Enter file name" in blob:
        return "missing_file", None
    if re.search(r"documentstyle|LaTeX ?2\.09", blob):
        return "latex209", None
    return None


def classify_error(
    err: str | None, ctx: str | None, tail: str, *, timed_out: bool
) -> tuple[str | None, str | None]:
    """首错 → `(category, payload)`；payload 给规则定位用（文件名/字体名/cs 名）。

    分类学源自 bench/py/fixloop.py 实测版 + engine-matrix §2 扩充
    （EPS 硬墙/物理字体/vendored sty/latin-5 等引擎路由相关类别）。
    """
    if timed_out:
        return "timeout", None
    head = "\n".join(x for x in (err, ctx) if x)
    if err:
        hit = _match_head(head)
        if hit is not None:
            return hit
    tail_hit = _match_tail(tail or "")
    if tail_hit is not None:
        return tail_hit
    return ("other" if err else "clean"), None


# ================================================================ 依赖记录解析
def _makefile_inputs(text: str) -> list[str] | None:  # noqa: C901, PLR0912
    r"""解析 tectonic `--makefile-rules` 产物首条依赖行（含 Make 转义文件名）。

    移植自 texglot makefile_inputs——Make 转义规则刁钻，保持上游实现原样。
    """
    text = re.sub(r"\\\r?\n", " ", text)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        separator = None
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                i += 2
                continue
            if line[i] == ":" and (i + 1 == len(line) or line[i + 1].isspace()):
                separator = i
                break
            i += 1
        if separator is None:
            return None
        values, current = [], []
        i = separator + 1
        while i < len(line):
            char = line[i]
            if char == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                current.append(line[i + 1])
                i += 2
                continue
            if char == "#":
                break
            if char.isspace():
                if current:
                    values.append("".join(current).replace("$$", "$"))
                    current = []
            else:
                current.append(char)
            i += 1
        if current:
            values.append("".join(current).replace("$$", "$"))
        return values
    return None


def _tectonic_unescaped_inputs(text: str) -> list[str]:
    """补解析 tectonic 未转义 prerequisite 名（每物理行一个）。保持上游实现。"""
    values = []
    started = False
    for raw in text.splitlines():
        line = raw
        if not started:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            separator = re.search(r"(?<!\\):(?=\s|$)", line)
            if separator is None:
                return []
            line = line[separator.end() :]
            started = True
        continued = line.endswith("\\")
        value = (line[:-1] if continued else line).strip()
        if value:
            values.append(value)
        if not continued:
            break
    return values


def _deps_from_record(main: str, out: Path, engine: str) -> list[str] | None:
    """读依赖记录文件（.fls INPUT / dependencies.mk）→ 原始名字列表。"""
    if engine == "tectonic":
        record = out / "dependencies.mk"
        if not record.is_file():
            return None
        content = record.read_text(encoding="utf-8", errors="replace")
        names = _makefile_inputs(content)
        if names is None:
            return None
        return names + _tectonic_unescaped_inputs(content)
    record = out / (Path(main).stem + ".fls")
    if not record.is_file():
        return None
    lines = record.read_text(encoding="utf-8", errors="replace").splitlines()
    names = [ln[6:] for ln in lines if ln.startswith("INPUT ")]
    return names or None


def compiled_dependencies(
    root: Path, main: str, out: Path, engine: str, *, include_eps: bool = False
) -> list[str] | None:
    r"""编译器自述的真实输入集——**翻译文件集权威**（docs/08 §3.4）。

    xelatex 读 `-recorder` 产的 `.fls` INPUT 行；tectonic 读
    `--makefile-rules` 产物。静态 `\input` 图只作编译失败时的降级。
    """
    root = root.resolve()
    cwd = (root / main).parent
    out = out.resolve()
    names = _deps_from_record(main, out, engine)
    if names is None:
        return None
    files = set()
    extensions = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"} | (
        {".eps"} if include_eps else set()
    )
    for name in names:
        path = Path(name)
        candidates = [path] if path.is_absolute() else [cwd / path]
        # tectonic 的 Make 规则把 input 写成相对 outdir 的名字，
        # 尽管实际读取是相对主文件目录——两种解都试。
        if engine == "tectonic":
            candidates.extend(
                cwd / value.relative_to(out)
                for value in (path, path.resolve())
                if value.is_relative_to(out)
            )
        for cand in candidates:
            resolved = cand.resolve()
            if (
                resolved.is_relative_to(root)
                and resolved.is_file()
                and resolved.suffix.lower() in extensions
            ):
                files.add(resolved.relative_to(root).as_posix())
                break
    if Path(main).as_posix() not in files:
        return None
    return sorted(files)


# ================================================================ Engine 协议
@runtime_checkable
class Engine(Protocol):
    """docs/08 §4.1 五方法 + detect/parse_log。

    `caps` 能力集决定 fixloop 哪些规则可跑：`{kpsewhich,tlmgr,updmap,
    shell_escape,bundle}`；tectonic 只有 `bundle`——install 系规则在其上
    走 ctan_fetch 原语（§5.3，由 fixloop 注入 callable）。
    """

    name: str
    caps: frozenset[str]

    def detect(self) -> str | None:
        """引擎二进制路径；不可用返回 None。"""
        ...

    def compile(  # noqa: PLR0913 — 签名即 docs/08 §4.1 规格面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = MAX_PASSES,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
    ) -> CompRes:
        """编译 `wdir/main`（相对路径）；产物落 `outdir`（默认 main 旁）。"""
        ...

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """文件可解析路径：kpsewhich（xelatex）| 本地+bundle 探测（tectonic）。"""
        ...

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """装 `fname` 所在包：tlmgr usermode（xelatex）| ctan_fetch（tectonic）。"""
        ...

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map（xelatex）；tectonic noop。"""
        ...

    def filemap(self, fname: str) -> list[str]:
        """file→包名索引：tlmgr search --file | 离线索引（fixloop 注入）。"""
        ...

    def parse_log(self, res: CompRes) -> LogInfo:
        """res.log_path 读不到时退 res.stdout_tail（tectonic 有时不写 .log）。"""
        ...


def _collect_compile_outputs(res: CompRes, outputs: list[str]) -> None:
    """汇总各 pass 的 stdout 尾巴进 CompRes。"""
    res.stdout_tail = outputs[-1][-4000:] if outputs else ""


# ================================================================ xelatex
class XelatexEngine:
    """TeX Live xelatex：M0 开发默认（tlmgr 可修性实测最高，engine-matrix §5）。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap", "recorder"})

    def __init__(
        self,
        binary: str | None = None,
        *,
        halt_on_error: bool = True,
        texmfhome: Path | None = None,
    ) -> None:
        """binary=None → PATH/常见落点探测；texmfhome=沙箱 usermode 树（冷启动）。"""
        self.binary = binary
        # docs/08 命令行含 -halt-on-error（fixloop 首错语义）；bench 基线跑
        # best-effort（halt_on_error=False，对齐 compile_bench 方法论）。
        self.halt_on_error = halt_on_error
        self.texmfhome = texmfhome
        self._search_cache: dict[str, list[str]] = {}
        self._usertree_inited = False

    def detect(self) -> str | None:
        """Xelatex 二进制探测（ctor 指定优先，否则 PATH/常见落点）。"""
        return self.binary or find_tool("xelatex")

    def _env(self, extra: dict[str, str] | None) -> dict[str, str]:
        add = dict(extra or {})
        if self.texmfhome:
            add.update(
                {
                    "TEXMFHOME": str(self.texmfhome / "home"),
                    "TEXMFVAR": str(self.texmfhome / "var"),
                    "TEXMFCONFIG": str(self.texmfhome / "config"),
                }
            )
        return child_env(add)

    def _cmd(self, binary: str, out: Path, main_name: str) -> list[str]:
        """构造 xelatex 命令行（docs/08 §4.1 旗标集）。"""
        cmd = [
            binary,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
        ]
        if self.halt_on_error:
            cmd.insert(3, "-halt-on-error")
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913 — 签名即 docs/08 §4.1 规格面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = MAX_PASSES,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
    ) -> CompRes:
        """执行 xelatex ≤`passes` 遍；-recorder 产 .fls 供 compiled_dependencies。"""
        res = CompRes(engine=self.name)
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "xelatex not found"
            return res
        main_path = wdir / main
        cwd = main_path.parent
        stem = main_path.stem
        out = (outdir or cwd).resolve()
        out.mkdir(parents=True, exist_ok=True)
        pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
        for stale in (pdf, log, out / f"{stem}.fls"):
            stale.unlink(missing_ok=True)
        env = self._env(env_extra)
        cmd = self._cmd(binary, out, main_path.name)
        if sandbox:
            cmd = sandbox_wrap(cmd, root=wdir, out=out)
        outputs = []
        per_pass = max(10.0, timeout / max(1, passes))
        for p in range(1, passes + 1):
            if p > 1 and not pdf.exists():
                break
            rc, out_s, sec, to = run_process(cmd, cwd=cwd, env=env, timeout=per_pass)
            res.rc = rc
            res.seconds += sec
            res.timed_out = res.timed_out or to
            res.passes = p
            outputs.append(out_s)
            if to:
                break
        _collect_compile_outputs(res, outputs)
        log_text = log.read_text(errors="replace") if log.exists() else ""
        res.log = parse_log(log_text or res.stdout_tail)
        res.log_path = log if log.exists() else None
        res.pdf = pdf if pdf.exists() else None
        res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
        res.ok = not res.timed_out
        res.deps = compiled_dependencies(wdir, main, out, self.name)
        return res

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """用 kpsewhich 探测文件可解析路径。"""
        tool = find_tool("kpsewhich")
        if tool is None:
            return None
        rc, out, _, to = run_process(
            [tool, fname],
            cwd=cwd or Path.cwd(),
            env=self._env(None),
            timeout=15,
        )
        if to or rc != 0 or not out.strip():
            return None
        return out.strip().splitlines()[0]

    def filemap(self, fname: str) -> list[str]:
        """`tlmgr search --global --file /fname` → TL 包名列表（进程内缓存）。"""
        tool = find_tool("tlmgr")
        if tool is None:
            return []
        key = "/" + fname
        if key in self._search_cache:
            return self._search_cache[key]
        rc, out, _, to = run_process(
            [tool, "search", "--global", "--file", key],
            cwd=Path.cwd(),
            env=self._env(None),
            timeout=60,
        )
        pkgs: list[str] = []
        if not to and rc == 0:
            for ln in out.splitlines():
                m = re.match(r"^([\w.-]+):$", ln.strip())
                if not m:
                    continue
                pkg = m.group(1)
                # 滤平台特定条目与 tlmgr 自身输出
                if "." in pkg and pkg.split(".")[-1] in (
                    "windows",
                    "win32",
                    "macosx",
                    "linux",
                    "x86_64",
                    "aarch64",
                    "amd64",
                    "i386",
                    "universal",
                ):
                    continue
                if pkg.startswith(("tlmgr", "tlgs")):
                    continue
                pkgs.append(pkg)
        pkgs = sorted(set(pkgs))
        self._search_cache[key] = pkgs
        return pkgs

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """经 kpsewhich 验证 → filemap 查包 → `tlmgr --usermode install` → 复核。"""
        if self.probe_file(fname):
            return True
        pkgs = self.filemap(fname)
        if not pkgs:
            return False
        tool = find_tool("tlmgr")
        if tool is None:
            return False
        env = self._env(None)
        home = env.get("TEXMFHOME")
        if (
            home
            and not self._usertree_inited
            and not (Path(home) / "tlpkg" / "texlive.tlpdb").exists()
        ):
            # 冷 TEXMFHOME：先建 usertree tlpdb，否则 --usermode 报
            # "Cannot determine type of tlpdb"（fixloop.py 实测坑）。
            run_process(
                [tool, "--usermode", "init-usertree"],
                cwd=Path.cwd(),
                env=env,
                timeout=60,
            )
            self._usertree_inited = True
        rc, _, _, to = run_process(
            [tool, "--usermode", "install", *pkgs],
            cwd=Path.cwd(),
            env=env,
            timeout=300,
        )
        if to or rc != 0:
            return False
        if font_related:
            self.rebuild_fontmaps()
        return self.probe_file(fname) is not None

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map。"""
        tool = find_tool("updmap-user") or find_tool("updmap")
        if tool is None:
            return False
        args = [tool] if tool.endswith("updmap-user") else [tool, "--user"]
        rc, _, _, to = run_process(
            args, cwd=Path.cwd(), env=self._env(None), timeout=120
        )
        return rc == 0 and not to

    def parse_log(self, res: CompRes) -> LogInfo:
        """读 res.log_path；缺席时退 stdout_tail。"""
        if res.log_path and res.log_path.exists():
            return parse_log(res.log_path.read_text(errors="replace"))
        return parse_log(res.stdout_tail)


# ================================================================ tectonic
class TectonicEngine:
    """tectonic 便携引擎：分发默认优先（bundle 自足、初始 clean 率更高）。

    硬墙（换引擎信号，engine-matrix §7）：EPS/PS 图、bundle 缺物理字体、
    bundle 包版本旧语义错。`probe_file`/`install_file` 本地无解——
    ctan_fetch 原语由 fixloop 侧注入。
    """

    name = "tectonic"
    caps = frozenset({"bundle"})

    def __init__(
        self,
        binary: str | None = None,
        *,
        bundle: str | None = None,
        continue_on_errors: bool = True,
        hide_paths: list[Path] | None = None,
        ctan_fetch: Callable[[str], str | None] | None = None,
    ) -> None:
        """bundle=None → 引擎自带默认；ctan_fetch=(fname)->落点路径|None。"""
        self.binary = binary
        # bundle=None → 引擎自带默认；env TEXLATE_TEX_BUNDLE 或 pin 可覆盖。
        self.bundle = (
            bundle if bundle is not None else os.environ.get("TEXLATE_TEX_BUNDLE")
        )
        # 对齐 nonstopmode 语义（tectonic 默认 halt-on-error）。
        self.continue_on_errors = continue_on_errors
        self.hide_paths = list(hide_paths or [])
        self.ctan_fetch = ctan_fetch
        #: file→包名 离线索引（texlive.tlpdb 解析产物，§5.3）；
        #: fixloop 可注入 {basename: [pkg,...]}。
        self.filemap_index: dict[str, list[str]] = {}

    def detect(self) -> str | None:
        """Tectonic 二进制探测（ctor 指定优先，否则 PATH/常见落点）。"""
        return self.binary or find_tool("tectonic")

    def _cmd(self, binary: str, out: Path, deps_mk: Path, main_name: str) -> list[str]:
        """构造 tectonic V2 命令行（docs/08 §4.1 + continue-on-errors 语义对齐）。"""
        cmd = [
            binary,
            "--color",
            "never",  # 全局旗标，-X compile 子命令不认（实测 unexpected argument）
            "-X",
            "compile",
            "--untrusted",
            "--keep-logs",
            "--keep-intermediates",
            "--makefile-rules",
            str(deps_mk),
            "--outdir",
            str(out),
        ]
        if self.continue_on_errors:
            cmd += ["-Z", "continue-on-errors"]
        if self.bundle:
            cmd += ["--bundle", self.bundle]
        for hide in self.hide_paths:
            cmd += ["--hide", str(hide)]
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913 — 签名即 docs/08 §4.1 规格面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 1,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
    ) -> CompRes:
        """执行 tectonic 单趟编译（自带 rerun 决策）；deps.mk 供 compiled_dependencies。"""
        del passes  # tectonic 自动决定 pass 数
        res = CompRes(engine=self.name)
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "tectonic not found"
            return res
        main_path = wdir / main
        cwd = main_path.parent
        stem = main_path.stem
        out = (outdir or cwd / "_tect_out").resolve()
        out.mkdir(parents=True, exist_ok=True)
        pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
        deps_mk = out / "dependencies.mk"
        for stale in (pdf, log, deps_mk):
            stale.unlink(missing_ok=True)
        cmd = self._cmd(binary, out, deps_mk, main_path.name)
        if sandbox:
            cmd = sandbox_wrap(cmd, root=wdir, out=out)
        env = child_env(env_extra)
        # 冷 bundle 首拉可能超时：缓存热身后重试一次（compile_bench 惯例）。
        outputs = []
        for _attempt in range(_TECTONIC_ATTEMPTS):
            rc, out_s, sec, to = run_process(cmd, cwd=cwd, env=env, timeout=timeout)
            res.rc = rc
            res.seconds += sec
            outputs.append(out_s)
            # 末次尝试的 timeout 态才算数——首拉超时后重试成功不能再背
            # timed_out=True（否则 judge 走 timeout 短路，出了 pdf 也判 fail）。
            res.timed_out = to
            if not to:
                break
        res.passes = 1
        _collect_compile_outputs(res, outputs)
        log_text = log.read_text(errors="replace") if log.exists() else ""
        info = parse_log(log_text)
        if info.first_error is None and not log_text:
            # tectonic 有时不写 .log 就崩（如 \documentstyle）——stderr 兜底。
            info = parse_log(res.stdout_tail)
            if info.first_error is None:
                m = re.search(r"^error: (.+)$", res.stdout_tail, re.MULTILINE)
                if m:
                    info.first_error = "! " + m.group(1)
                    info.n_errors = max(1, info.n_errors)
        res.log = info
        res.log_path = log if log.exists() else None
        res.pdf = pdf if pdf.exists() else None
        res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
        res.ok = not res.timed_out
        res.deps = compiled_dependencies(wdir, main, out, self.name)
        return res

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """工程内探测（vendored 文件遮蔽检查）；bundle 探测留 ctan_fetch 层。"""
        if cwd is not None:
            cand = cwd / fname
            if cand.is_file():
                return str(cand)
        return None

    def filemap(self, fname: str) -> list[str]:
        """file→包索引：tectonic 侧无 tlmgr——返回 `filemap_index` 离线索引。"""
        return list(self.filemap_index.get(fname, []))

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """ctan_fetch 降级原语（仅限 TeX 输入层文件 .sty/.cls/.tfm）。"""
        del font_related
        if self.ctan_fetch is None:
            return False
        dest = self.ctan_fetch(fname)
        return dest is not None

    def rebuild_fontmaps(self) -> bool:
        """返回 False：tectonic 无 updmap，noop。"""
        return False

    def parse_log(self, res: CompRes) -> LogInfo:
        """读 res.log_path；缺席时退 stdout_tail。"""
        if res.log_path and res.log_path.exists():
            return parse_log(res.log_path.read_text(errors="replace"))
        return parse_log(res.stdout_tail)


# ================================================================ 静态路由表
@dataclass
class RouteDecision:
    """`route_project` 产物：引擎优先序 + 拒绝/降级原因。"""

    engines: list[str]  # 优先序，如 ["tectonic", "xelatex"]
    reject: str | None = None  # 非 None = 无条件拒绝（\documentstyle）
    reasons: list[str] = field(default_factory=list)
    non_utf8: bool = False  # 非 UTF-8 源（需 iconv 预处理提示）


_PSTRICKS_RE = re.compile(
    r"\\usepackage(?:\[[^]]*\])?\{[^}]*pstricks|\\begin\s*\{pspicture\}|"
    r"\\ps(?:line|frame|curve|plot|custom|newpath)\b"
)
_MINTED_FROZEN_RE = re.compile(r"frozencache")
_BITMAP_FONT_PKGS = re.compile(
    r"\\usepackage(?:\[[^]]*\])?\{[^}]*\b(bbm|bbmfonts|dsfont|bbold|yfonts|wasy|wasysym)\b"
)


def route_project(root: Path, *, prefer: str = "tectonic") -> RouteDecision:
    r"""静态预检路由（docs/08 §4.2 表）：编译前即可决策的引擎分配。

    - `\documentstyle` → 无条件 reject（三引擎全死已实证，engine-matrix §3.2）
    - `*.eps` / pstricks / pspicture → 跳过 tectonic 直走 xelatex（E2 硬墙）
    - frozencache + minted → tectonic 优先（bundle v2.6 兼容 v2 缓存）
    - bbm/dsfont 位图字体包 → tectonic 高风险标记（失败后换 xelatex）
    - 非 UTF-8 源 → 标记（iconv 预处理或 inputenc 路注，由调用方处理）
    """
    vis: dict[Path, str] = {}
    non_utf8 = False
    for p in root.rglob("*.tex"):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
        vis[p] = visible_tex(decode_tex(raw))
    blob_vis = "\n".join(vis.values())

    # --- 无条件 reject：\documentstyle（任何文件里出现都算，主文件判定已过）
    for p, v in vis.items():
        if re.search(r"\\documentstyle\b", v):
            return RouteDecision(
                engines=[],
                reject="latex209_documentstyle",
                reasons=[f"{p.relative_to(root)}: \\documentstyle → 三引擎实测全死"],
                non_utf8=non_utf8,
            )

    reasons: list[str] = []
    has_eps = any(p.suffix.lower() == ".eps" for p in root.rglob("*"))
    has_pstricks = bool(_PSTRICKS_RE.search(blob_vis))
    has_minted_frozen = bool(_MINTED_FROZEN_RE.search(blob_vis))
    has_bitmap_fonts = bool(_BITMAP_FONT_PKGS.search(blob_vis))

    engines = (
        ["xelatex", "tectonic"] if prefer == "xelatex" else ["tectonic", "xelatex"]
    )
    if has_eps or has_pstricks:
        # E2 硬墙：xdvipdfmx 不支持 EPS/PS → 跳过 tectonic
        engines = sorted(engines, key=lambda e: 0 if e == "xelatex" else 1)
        reasons.append(
            f"eps_files={has_eps} pstricks={has_pstricks} → xelatex 优先"
            "（tectonic xdvipdfmx 硬墙）"
        )
    elif has_minted_frozen:
        engines = sorted(engines, key=lambda e: 0 if e == "tectonic" else 1)
        reasons.append("minted frozencache → tectonic 优先（bundle v2.6 兼容）")
    if has_bitmap_fonts:
        reasons.append("bbm/dsfont 类位图字体包 → tectonic 高风险，失败换 xelatex")
    if non_utf8:
        reasons.append("非 UTF-8 源 → 需 iconv 转码预处理或 inputenc 路注")
    return RouteDecision(
        engines=engines, reject=None, reasons=reasons, non_utf8=non_utf8
    )


def engine_for(name: str, **kwargs: object) -> Engine:
    """按名构造引擎实例。"""
    if name == "xelatex":
        return XelatexEngine(**kwargs)  # type: ignore[arg-type]
    if name == "tectonic":
        return TectonicEngine(**kwargs)  # type: ignore[arg-type]
    msg = f"未知引擎 {name!r}"
    raise ValueError(msg)


def tlmgr_search_cache_path() -> Path:
    """定位 tlmgr file→pkg 搜索的跨进程落盘缓存位（fixloop 共用约定）。"""
    return Path(
        os.environ.get(
            "TEXLATE_TLMGR_CACHE",
            str(Path.home() / ".cache" / "texlate" / "tlmgr-search-cache.json"),
        )
    )


def load_search_cache() -> dict[str, list[str]]:
    """读 tlmgr 搜索缓存；缺席/损坏返回空表。"""
    try:
        return json.loads(tlmgr_search_cache_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_search_cache(cache: dict[str, list[str]]) -> None:
    """写 tlmgr 搜索缓存（父目录自动建）。"""
    p = tlmgr_search_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=0, sort_keys=True))
