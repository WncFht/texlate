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
- OS 沙箱（§4.4）：darwin 走 ``sandbox-exec``（sandbox.py）；linux 无 FS
  沙箱原语 → bwrap 可用时以 userns + 挂载白名单复刻同语义（``$HOME``
  影子化只挂白名单子路径、pid/ipc/uts unshare、xelatex 断网、tectonic
  冷拉 bundle 留网），缺席退回 env 白名单 + TeX 阀层；实落形态记
  ``CompRes.sandbox_mode``，``TEXLATE_NO_BWRAP=1`` 显式关停。
- log 解析（§2.3）：`parse_log` 双格式错误计数（`^!` + `file:line:`）、
  `l.NNN` 行号、`(` 文件栈、tail；tectonic 有时不写 .log → stderr 兜底。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

from texlate.texlog import update_file_stack
from texlate.textutil import decode_tex

from .mask import visible_tex
from .sandbox import child_env, find_tool, run_process, sandbox_wrap
from .toolchain import ensure_tectonic, tectonic_version

DEFAULT_TIMEOUT = 240.0  # docs/08 §4.1
MAX_PASSES = 2
_TECTONIC_ATTEMPTS = 2  # 冷 bundle 首拉超时后重试（缓存热身）

#: tectonic bundle pin（docs/08 §4.1）——引擎默认 bundle；可用 env
#: TEXLATE_TEX_BUNDLE 或构造参数覆盖，置空串回落引擎自带默认 bundle。
TECTONIC_BUNDLE_PIN = "https://data1b.fullyjustified.net/tlextras-2022.0r0.tar"

#: ``compile(flags=…)`` 拒放面：重键输出落点的 flag 会毁掉 ``{stem}.pdf/.log``
#: 按 outdir 回收的约定——这类请求进 ``CompRes.flags_dropped`` 而非 argv。
_OUTPUT_REKEY_PREFIXES: Final = ("-output-directory", "-aux-directory", "-jobname")

#: engine_flags → tectonic argv 的受支持子集映射（原拼写 → argv token）。
#: ``-shell-escape`` 刻意不映射：``--untrusted`` 恒在 cmd 即禁 \write18，
#: 开 shell 与之矛盾且放大不可信源的 RCE 面 → 走 dropped，由 e2e 跨引擎
#: 换 xelatex 承载。
_TECTONIC_FLAG_MAP: Final = {
    "-synctex": ["--synctex"],
    "-synctex=1": ["--synctex"],
}

#: ``-X compile`` 撤 ``--web-bundle`` 的分界版本：0.17.0 起 URL 并入
#: ``--bundle``（0.17.0 help 实测 ``--bundle <BUNDLE>  Use this URL or
#: path``；老版 ``--bundle`` 只认本地路径，URL 必须 ``--web-bundle``，
#: 否则 URL 被当文件打开 → os error 2，archbox 全灭根因）。
_TECTONIC_BUNDLE_URL_MIN: Final = (0, 17, 0)


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
    rc: int | None = None  # 最后一个 pass 的 rc（逐 pass 覆写）
    #: 任一 pass 被信号杀死时记信号号（如 13=SIGPIPE）——res.rc 只留
    #: 末 pass，mid-loop 死亡会被后 pass 掩盖（2211.13013 实证）。
    killed_signal: int | None = None
    stdout_tail: str = ""
    deps: list[str] | None = None  # compiled_dependencies（.fls/.mk 权威输入集）
    #: 本次实际生效的 OS 沙箱形态：``off``（sandbox=False 或未走到 wrap
    #: 决策）/ ``sandbox-exec``（darwin）/ ``bwrap``（linux）/ ``env``
    #: （OS 包裹缺席，只剩 env 白名单 + TeX 阀层）——bench/stagerun 归因用。
    sandbox_mode: str = "off"
    #: ``compile(flags=…)`` 实落 argv 的请求 flag（tectonic 记映射前原拼写）。
    flags_applied: list[str] = field(default_factory=list)
    #: 请求但引擎拒放的 flag（支持子集外 / 会重键输出落点）→ fixloop 记
    #: advisory、e2e 凭它跨引擎取优。
    flags_dropped: list[str] = field(default_factory=list)

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
    ("ps_image", r"image inclusion failed for[^\n]*\.eps|PostScript image"),
    ("inputenc_unicode", r"inputenc is not designed for"),
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


#: tail 侧真 2.09 签名（`_match_tail` 专用）：`\documentstyle` 控制序列
#: 现身错上下文（`l.N` 行/tectonic stderr）、内核 compat-mode 横幅与
#: "Compatibility mode" 注记行、2e 内核 "in LaTeX 2.09" 错文、上古格式
#: "LaTeX Version 2.09" 版横幅。不收任意位置 "LaTeX2.09" 字样——aastex
#: 系 cls 的 info 横幅 "Original \LaTeX2.09 style"（LaTeX2e 文档）曾连
#: 吃 15+ 篇零 '!' 行静默死误报（fixloop-replay-baseline-2026-09-16）。
_LATEX209_TAIL_RE = re.compile(
    r"\\documentstyle\b|LaTeX 2\.09 COMPATIBILITY MODE|"
    r"LaTeX2e command[^\n]*\bin LaTeX 2\.09|LaTeX Version 2\.09|"
    r"^[ \t]*Compatibility mode",
    re.MULTILINE,
)


def _match_tail(blob: str) -> tuple[str, str | None] | None:
    """无 `!` 行或首错即 emergency 时，回溯 tail 找文件名提示符。"""
    m = re.search(r"File `([^']+\.[a-zA-Z0-9]+)' not found", blob)
    if m and ("Enter file name" in blob or "Emergency" in blob):
        return "missing_file", m.group(1)
    if "Enter file name" in blob:
        return "missing_file", None
    if _LATEX209_TAIL_RE.search(blob):
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


# ================================================================ Linux bwrap 兜底
#: bwrap 挂载面默认覆盖的系统前缀（ro-bind-try：缺席跳过）。texmf 树不在此列
#: ——发行版布局分散（arch 把 TEXMFSYSVAR 放 ``/var/lib/texmf``，上游安装进
#: ``~/texlive/YYYY`` 或 ``/usr/local/texlive``），由 ``_kpathsea_dirs`` 按
#: texmf.cnf 权威值动态补挂。
_BWRAP_SYS_RO: Final = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/opt",
    "/etc",
    "/var/cache/fontconfig",
)

#: 需 RW 进沙箱的 env 键：texmf 可写树 + 自定义 tmp 目录。
_BWRAP_ENV_RW: Final = {
    "TEXMFHOME",
    "TEXMFVAR",
    "TEXMFCONFIG",
    "TEXMFSYSVAR",
    "TEXMFSYSCONFIG",
    "TMPDIR",
    "TEMP",
    "TMP",
}
#: env 键里 TMPDIR 系的子集——落 ``/tmp`` 内时不挂（沙箱 /tmp 是私有
#: tmpfs，挂宿主子目录反而扩写面）。
_BWRAP_TMP_KEYS: Final = {"TMPDIR", "TEMP", "TMP"}
#: 需 RO 进沙箱的 env 键：kpathsea 搜索路径列表 + 本地 bundle 文件。
_BWRAP_ENV_RO: Final = {
    "TEXINPUTS",
    "BIBINPUTS",
    "BSTINPUTS",
    "TFMFONTS",
    "VFFONTS",
    "T1FONTS",
    "TTFONTS",
    "OPENTYPEFONTS",
    "TEXFONTMAPS",
    "ENCFONTS",
    "XDVIFONTS",
    "TEXLATE_TEX_BUNDLE",
}
#: kpathsea 树变量：rw 侧是用户树；ro 侧是系统树（用户可写的经
#: ``os.access(W_OK)`` 升 rw——存在用户可写 SYSVAR 的发行版布局）。
_BWRAP_KPSE_RW: Final = ("TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG")
_BWRAP_KPSE_RO: Final = (
    "TEXMFSYSVAR",
    "TEXMFSYSCONFIG",
    "TEXMFLOCAL",
    "TEXMFDIST",
    "TEXMFMAIN",
    "TEXMFINIT",
)
_KPATHSEA_ELEM_RX: Final = re.compile(r"[\s,:{}]+")
_TRUE_VALUES: Final = {"1", "true", "yes", "on"}
#: 沙箱内私有 tmpfs 挂点字面量——``/tmp`` 下的宿主路径判定专用。
_SANDBOX_TMP: Final = "/tmp"  # noqa: S108 -- 挂点语义即字面 /tmp


def _kpathsea_list(value: str) -> list[str]:
    """拆 kpathsea 路径列表（``:``/``,``/``{}`` 分隔，剥 ``!`` 与 ``//`` 尾）。"""
    out = []
    for elem in _KPATHSEA_ELEM_RX.split(value):
        p = elem.lstrip("!").removesuffix("//")
        if p and Path(p).is_absolute():
            out.append(p)
    return out


def _kpse_var(tool: str, var: str) -> str:
    """``kpsewhich -var-value <var>`` 单变量查询；任何失败返空串。"""
    try:
        rc, out, _, to = run_process(
            [tool, "-var-value", var], cwd=Path.cwd(), env=child_env(), timeout=15
        )
    except OSError:
        return ""
    return out if rc == 0 and not to else ""


@lru_cache(maxsize=1)
def _kpathsea_dirs() -> tuple[list[str], list[str]]:
    """问 kpathsea 各 texmf 树落点 → ``(rw, ro)``（进程内一次性探测）。

    发行版布局分散（arch 的 TEXMFSYSVAR 在 ``/var/lib/texmf``、上游装在
    ``~/texlive/YYYY`` 或 ``/usr/local/texlive``）——按 texmf.cnf 权威值挂，
    比写死路径或只按 binary 锚点可靠；kpsewhich 缺席返空表。
    """
    tool = find_tool("kpsewhich")
    if tool is None:
        return [], []
    rw: list[str] = []
    ro: list[str] = []
    for var in _BWRAP_KPSE_RW:
        rw += _kpathsea_list(_kpse_var(tool, var))
    for var in _BWRAP_KPSE_RO:
        for p in _kpathsea_list(_kpse_var(tool, var)):
            (rw if os.access(p, os.W_OK) else ro).append(p)
    return rw, ro


def _bwrap_env_paths(env: dict[str, str]) -> tuple[list[str], list[str]]:
    """编译子进程 env 里的路径值 → ``(rw, ro)`` 挂载名单。"""
    rw: list[str] = []
    ro: list[str] = []
    for key, val in env.items():
        if not val:
            continue
        if key in _BWRAP_ENV_RW:
            if Path(val).is_absolute() and not (
                key in _BWRAP_TMP_KEYS and Path(val).is_relative_to(_SANDBOX_TMP)
            ):
                rw.append(val)
        elif key in _BWRAP_ENV_RO:
            ro += _kpathsea_list(val)
    return rw, ro


def _bwrap_mounts(
    binary: str,
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    extra_rw: Iterable[Path | str] = (),
) -> tuple[list[str], list[str]]:
    """汇总 ``(rw, ro)`` 挂载面——root/out 由调用方单独硬挂，不在返回值里。

    ``$HOME`` 本体不挂：bwrap 为嵌套 bind 自建的父目录是沙箱内 tmpfs，
    宿主机 ``~/.ssh``/``~/.aws`` 保持不可见——对齐 macOS deny-$HOME 语义。
    """
    home = Path.home()
    rw: list[str] = [
        *(str(p) for p in sorted(home.glob(".texlive*"))),
        str(home / "texmf"),
        str(home / ".cache" / "fontconfig"),
        str(home / ".cache" / "Tectonic"),
        str(home / ".cache" / "TectonicProject.Tectonic"),
        *(str(p) for p in extra_rw),
    ]
    ro: list[str] = [
        str(home / ".fonts"),
        str(home / ".local" / "share" / "fonts"),
    ]
    env_rw, env_ro = _bwrap_env_paths(env)
    kpse_rw, kpse_ro = _kpathsea_dirs()
    rw += env_rw + kpse_rw
    ro += env_ro + kpse_ro
    # 引擎本体在系统前缀/工程/输出之外时锚发行根（``<dist>/bin/<arch>/<tool>``
    # 上三级即发行根，连带同级 texmf 树与 bin 伙伴）；锚点过宽（``/``、
    # ``$HOME``、``/home``）时退化为只挂二进制文件本身——托管/自装引擎
    # （~/.texlate/tools、~/.local/bin）都是自足单文件，足够。
    covered = [*_BWRAP_SYS_RO, str(root), str(out)]
    real = Path(binary).resolve()
    if not any(real.is_relative_to(p) for p in covered):
        anchor = real.parent.parent.parent
        if anchor in (Path("/"), home, home.parent):
            anchor = real
        if anchor not in (Path("/"), home, home.parent):
            ro.append(str(anchor))
    rw_set = set(rw)
    return sorted(set(rw)), sorted({p for p in ro if p not in rw_set})


@lru_cache(maxsize=1)
def _bwrap_capable() -> bool:
    """探测 bwrap 可用性：二进制在 + userns/pid/ipc/uts/net/cap-drop 全旗标可建。

    一次性全量探测——任一 namespace 被内核禁用（如
    ``kernel.unprivileged_userns_clone=0``）即返 False，编译退回 env-only
    而不是批量挂掉。``TEXLATE_NO_BWRAP`` 真值 = 显式关停（坏件逃生门）。
    """
    if os.environ.get("TEXLATE_NO_BWRAP", "").strip().lower() in _TRUE_VALUES:
        return False
    tool = find_tool("bwrap")
    if tool is None:
        return False
    try:
        rc, _, _, to = run_process(
            [
                tool,
                "--die-with-parent",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--unshare-net",
                "--cap-drop",
                "ALL",
                "--ro-bind-try",
                "/",
                "/",
                "--",
                "/bin/true",
            ],
            cwd=Path.cwd(),
            env={},
            timeout=10,
        )
    except OSError:
        return False
    return rc == 0 and not to


def _bwrap_wrap(  # noqa: PLR0913 -- 挂载面组装参数即签名
    cmd: list[str],
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    allow_net: bool,
    extra_rw: Iterable[Path | str] = (),
) -> list[str] | None:
    """Linux 用 bwrap 复刻 sandbox-exec 语义；不可用返 ``None``（调用方直通）。

    - ``--die-with-parent`` + unshare pid/ipc/uts：pid-ns init 死亡时内核清
      场整棵进程树，与 run_process 的 killpg 互为兜底（**不**加
      ``--new-session``——那会另起进程组让 killpg 打不中孙进程）。
    - ``allow_net=False`` 追加 ``--unshare-net``：xelatex 工具链全本地可断
      网；tectonic 冷拉 bundle 必须留网，恒 True。
    - 挂载白名单见 ``_bwrap_mounts``；``--dir $HOME`` 保底存在（自建的
      tmpfs 影子目录，mktex 系 mkdir 有落点）。
    """
    if not _bwrap_capable():
        return None
    tool = find_tool("bwrap") or "bwrap"
    rw, ro = _bwrap_mounts(cmd[0], root=root, out=out, env=env, extra_rw=extra_rw)
    argv = [
        tool,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--cap-drop",
        "ALL",
    ]
    if not allow_net:
        argv.append("--unshare-net")
    argv += [
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        _SANDBOX_TMP,
        "--dir",
        str(Path.home()),
    ]
    for prefix in _BWRAP_SYS_RO:
        argv += ["--ro-bind-try", prefix, prefix]
    # ro 先挂、rw 后挂：重叠路径上后挂的 rw 生效（如 TEXMFVAR 恰好落在
    # ro 系统树之下仍保持可写）。
    for p in ro:
        argv += ["--ro-bind-try", p, p]
    argv += ["--bind", str(root), str(root), "--bind", str(out), str(out)]
    # XDG_CACHE_HOME 不在 env 白名单内、子进程本不可见；宿主设了它则补挂并
    # --setenv 还原，让 tectonic 继续命中父侧热缓存而不是沙箱内重拉 bundle。
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute() and not Path(xdg).is_relative_to(_SANDBOX_TMP):
        argv += ["--setenv", "XDG_CACHE_HOME", xdg]
        cache = str(Path(xdg) / "Tectonic")
        argv += ["--bind-try", cache, cache]
    for p in rw:
        argv += ["--bind-try", p, p]
    argv += ["--", *cmd]
    return argv


def _apply_sandbox(  # noqa: PLR0913 -- 沙箱决策参数面
    cmd: list[str],
    *,
    root: Path,
    out: Path,
    env: dict[str, str],
    enabled: bool,
    allow_net: bool,
    extra_rw: Iterable[Path | str] = (),
) -> tuple[list[str], str]:
    """OS 沙箱分发 → ``(argv, mode)``，mode 落 ``CompRes.sandbox_mode``。

    ``sandbox=True`` 的既有契约本就含 env 白名单 + TeX 阀（恒在）；本层补
    OS 包裹：darwin ``sandbox-exec``、linux ``bwrap``、其余/能力缺席退回
    ``env``（与改动前 linux 行为一致）。
    """
    if not enabled:
        return cmd, "off"
    wrapped = sandbox_wrap(cmd, root=root, out=out)
    if wrapped is not cmd:
        return wrapped, "sandbox-exec"
    if sys.platform != "linux":
        return cmd, "env"
    bw = _bwrap_wrap(
        cmd, root=root, out=out, env=env, allow_net=allow_net, extra_rw=extra_rw
    )
    if bw is None:
        return cmd, "env"
    return bw, "bwrap"


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
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> CompRes:
        """编译 `wdir/main`（相对路径）；产物落 `outdir`（默认 main 旁）。

        ``best_effort=True`` 强制 nonstopmode 兜底语义：xelatex 去掉
        ``-halt-on-error``（TeX 错误恢复跑到底，救残页），tectonic 强制
        continue-on-errors——fixloop 规则耗尽后的最后一搏用。

        ``flags`` = fixloop 规则请求追加的引擎 CLI flag（engine_flags cell
        的落点）：xelatex 原样追加 argv（kpathsea last-wins，可压
        ``-no-shell-escape``）；tectonic 只放 ``_map_flags`` 支持子集，
        其余记 ``CompRes.flags_dropped`` 降级为 advisory。
        """
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
        repository: str | None = None,
    ) -> None:
        """binary=None → PATH/常见落点探测；texmfhome=沙箱 usermode 树（冷启动）。

        repository=tlnet 镜像 pin：`tlmgr --usermode install` 与 tlpdb 索引
        拉取共用（env ``TEXLATE_TLNET`` 同效）；None = tlmgr 既有配置
        （mirror.ctan.org round-robin 在部分网络下不稳，bench 侧钉 TUNA）。
        """
        self.binary = binary
        # docs/08 命令行含 -halt-on-error（fixloop 首错语义）；bench 基线跑
        # best-effort（halt_on_error=False，对齐 compile_bench 方法论）。
        self.halt_on_error = halt_on_error
        self.texmfhome = texmfhome
        self.repository = repository or os.environ.get("TEXLATE_TLNET") or None
        self._search_cache: dict[str, list[str]] | None = None
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

    @staticmethod
    def _split_flags(flags: Iterable[str] | None) -> tuple[list[str], list[str]]:
        """engine_flags → (进 argv, 丢弃)。

        ``_OUTPUT_REKEY_PREFIXES`` 系 flag 会重键 pdf/log 落点、毁掉按
        outdir 回收产物的约定 → 拒放进 dropped；其余原样直通。
        """
        applied, dropped = [], []
        for fl in flags or ():
            if fl.startswith(_OUTPUT_REKEY_PREFIXES):
                dropped.append(fl)
            elif fl not in applied:
                applied.append(fl)
        return applied, dropped

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 xelatex 命令行（docs/08 §4.1 旗标集 + fixloop engine_flags）。

        ``flags`` 追加在基线旗标之后、``main_name`` 之前——kpathsea 选项
        last-wins，规则请求（如 minted 的 ``-shell-escape``）可压过
        ``-no-shell-escape``。
        """
        cmd = [
            binary,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
        ]
        if self.halt_on_error and not best_effort:
            cmd.insert(3, "-halt-on-error")
        applied, _ = self._split_flags(flags)
        for fl in applied:
            if fl not in cmd:
                cmd.append(fl)
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
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> CompRes:
        """执行 xelatex ≤`passes` 遍；-recorder 产 .fls 供 compiled_dependencies。"""
        res = CompRes(engine=self.name)
        res.flags_applied, res.flags_dropped = self._split_flags(flags)
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
        cmd = self._cmd(
            binary, out, main_path.name, best_effort=best_effort, flags=flags
        )
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd,
            root=wdir,
            out=out,
            env=env,
            enabled=sandbox,
            # xelatex 工具链（kpsewhich/mktex*/xdvipdfmx）全本地——断网兜底
            # ``-shell-escape`` flag 穿透场景（fixloop minted 规则可压过
            # -no-shell-escape）的 curl 外联面。
            allow_net=False,
            extra_rw=[self.texmfhome] if self.texmfhome else [],
        )
        outputs = []
        per_pass = max(10.0, timeout / max(1, passes))
        for p in range(1, passes + 1):
            if p > 1 and not pdf.exists():
                break
            rc, out_s, sec, to = run_process(cmd, cwd=cwd, env=env, timeout=per_pass)
            res.rc = rc
            if rc is not None and rc < 0:
                res.killed_signal = -rc
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

    def _search_cache_map(self) -> dict[str, list[str]]:
        """file→pkg 进程内缓存，首次访问时并入落盘缓存（远端仓库知识）。"""
        if self._search_cache is None:
            self._search_cache = load_search_cache()
        return self._search_cache

    def _filemap_index(self, fname: str) -> list[str] | None:
        """texlive.tlpdb 离线索引查询；索引不可用 → None（回退 tlmgr）。

        `tlmgr search --global` 逐查询远端 tlpdb，镜像 round-robin 实测挂出
        假 "no package provides"（fixloop-bench 口径）——同一份仓库知识走
        本地索引既稳又快（~/.texlate/cache/filemap.json 常驻）。
        """
        from texlate.compile.fixloop.ctan import (  # noqa: PLC0415  # 延迟: 防循环
            MIRROR,
            TlpdbIndex,
        )

        try:
            idx = TlpdbIndex.ensure(mirror=self.repository or MIRROR)
        except Exception:  # noqa: BLE001  # 索引拉取失败不阻塞在线通路
            return None
        return idx.query(fname)

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包名索引：tlpdb 离线索引优先，`tlmgr search --file` 兜底。"""
        cache = self._search_cache_map()
        key = "/" + fname
        if key in cache:
            return cache[key]
        pkgs = self._filemap_index(fname)
        if pkgs is not None:
            cache[key] = pkgs
            return pkgs
        pkgs = self._filemap_tlmgr(fname)
        cache[key] = pkgs
        save_search_cache(cache)
        return pkgs

    def _filemap_tlmgr(self, fname: str) -> list[str]:
        """`tlmgr search --global --file /fname` 在线通路（索引缺席时兜底）。"""
        tool = find_tool("tlmgr")
        if tool is None:
            return []
        rc, out, _, to = run_process(
            [tool, "search", "--global", "--file", "/" + fname],
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
        return sorted(set(pkgs))

    @contextlib.contextmanager
    def _install_lock(self) -> Iterator[None]:
        """同 usertree 的 tlmgr install 串行化（跨进程 flock；无 fcntl 则退化为直通）。"""
        base = (
            Path(self.texmfhome) if self.texmfhome else tlmgr_search_cache_path().parent
        )
        try:
            base.mkdir(parents=True, exist_ok=True)
            import fcntl  # noqa: PLC0415  # 平台门: 无 fcntl 则退化为直通
        except (OSError, ImportError):
            yield
            return
        with (base / ".texlate-install.lock").open("a+b") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

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
        with self._install_lock():
            if self.probe_file(fname):
                return True  # 并发同伴已装好
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
            argv = [tool, "--usermode"]
            if self.repository:
                argv += ["--repository", self.repository]
            argv += ["install", *pkgs]
            rc, _, _, to = run_process(argv, cwd=Path.cwd(), env=env, timeout=300)
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
        """bundle=None → 钉版 tlextras-2022.0r0；ctan_fetch=(fname)->落点|None。"""
        self.binary = binary
        # 默认走 pin（docs/08 §4.1）；env TEXLATE_TEX_BUNDLE 覆盖，
        # 置空串 = 引擎自带默认 bundle。
        self.bundle = (
            bundle
            if bundle is not None
            else os.environ.get("TEXLATE_TEX_BUNDLE", TECTONIC_BUNDLE_PIN)
        )
        # 对齐 nonstopmode 语义（tectonic 默认 halt-on-error）。
        self.continue_on_errors = continue_on_errors
        self.hide_paths = list(hide_paths or [])
        self.ctan_fetch = ctan_fetch
        #: file→包名 离线索引（texlive.tlpdb 解析产物，§5.3）；
        #: fixloop 可注入 {basename: [pkg,...]}。
        self.filemap_index: dict[str, list[str]] = {}

    def detect(self) -> str | None:
        """Ctor 指定 → PATH/常见落点 → 托管件 → 自动下载（toolchain 矩阵）。"""
        return self.binary or ensure_tectonic()

    @staticmethod
    def _map_flags(flags: Iterable[str] | None) -> tuple[list[str], list[str]]:
        """engine_flags → (argv 追加 token, 丢弃的原 flag)：只放支持子集。

        放行面 = ``_TECTONIC_FLAG_MAP`` 显式映射 + ``-Z`` 原生拼写直通
        （``-Z<opt>`` 单 token 与 ``-Z <opt>`` 两 token 都收）；其余（含
        ``-shell-escape`` 与任何 ``--outdir`` 类重键尝试）进 dropped。
        """
        toks, dropped = [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            if fl in _TECTONIC_FLAG_MAP:
                toks += _TECTONIC_FLAG_MAP[fl]
            elif fl == "-Z" and i + 1 < len(flist) and not flist[i + 1].startswith("-"):
                toks += [fl, flist[i + 1]]
                i += 1
            elif fl.startswith("-Z") and fl != "-Z":
                toks.append(fl)
            else:
                dropped.append(fl)
            i += 1
        return toks, dropped

    def _bundle_flag(self, binary: str) -> str:
        """Bundle 落 argv 的 flag 名：本地路径恒 ``--bundle``；URL 按版本分支。

        ``_TECTONIC_BUNDLE_URL_MIN`` 起 ``-X compile`` 撤了 ``--web-bundle``
        （URL 并入 ``--bundle``）；更老的 ``--bundle`` 只认本地路径。版本
        探不出 → ``--bundle``（托管件钉版已在新语法侧，新版是未来默认）。
        """
        if "://" not in self.bundle:
            return "--bundle"
        ver = tectonic_version(binary)
        if ver is not None and ver < _TECTONIC_BUNDLE_URL_MIN:
            return "--web-bundle"
        return "--bundle"

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 tectonic V2 命令行（docs/08 §4.1 + continue-on-errors 语义对齐）。

        ``flags`` 经 ``_map_flags`` 过滤——只放受支持子集（见该方法 docstring）。
        """
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
            str(out / "dependencies.mk"),
            "--outdir",
            str(out),
        ]
        if self.continue_on_errors or best_effort:
            cmd += ["-Z", "continue-on-errors"]
        if self.bundle:
            cmd += [self._bundle_flag(binary), self.bundle]
        for hide in self.hide_paths:
            cmd += ["--hide", str(hide)]
        toks, _ = self._map_flags(flags)
        cmd += toks
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
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
    ) -> CompRes:
        """执行 tectonic 单趟编译（自带 rerun 决策）；deps.mk 供 compiled_dependencies。"""
        del passes  # tectonic 自动决定 pass 数
        res = CompRes(engine=self.name)
        flist = list(flags or ())
        _, dropped = self._map_flags(flist)
        res.flags_dropped = dropped
        dset = set(dropped)
        res.flags_applied = [f for f in flist if f not in dset]
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
        env = child_env(env_extra)
        cmd = self._cmd(
            binary, out, main_path.name, best_effort=best_effort, flags=flist
        )
        # tectonic 冷拉 bundle/包走进程内 HTTPS——不能像 xelatex 那样断网。
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd, root=wdir, out=out, env=env, enabled=sandbox, allow_net=True
        )
        # 冷 bundle 首拉可能超时：缓存热身后重试一次（compile_bench 惯例）。
        outputs = []
        for _attempt in range(_TECTONIC_ATTEMPTS):
            rc, out_s, sec, to = run_process(cmd, cwd=cwd, env=env, timeout=timeout)
            res.rc = rc
            if rc is not None and rc < 0:
                res.killed_signal = -rc
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
    reject: str | None = None  # 非 None = 无条件拒绝
    reasons: list[str] = field(default_factory=list)
    non_utf8: bool = False  # 非 UTF-8 源（需 iconv 预处理提示）
    latex209_suspect: bool = False  # \documentstyle 检出：降级为试编标记


#: 高置信 pstricks 依赖签名（visible_tex 遮蔽视图上匹配）：包名元素级
#: 精确（pstricks / pstricks-add / pst-* 家族——元素边界防 `{notpstricks}`
#: 类子串误中）+ `pspicture` 环境 + `\psset` 配置宏（vendored/传递装载的
#: 兜底信号，0905.2435/0905.4369 实证）。裸 `\psline`/`\psframe` 族不收——
#: polyfill 守卫与自定义宏残影假命中（corpus_v3 全扫零独立命中；新口径
#: 68 vs 旧 61，反增收 `{amsmath,pstricks}` 非首元素声明）。
_PSTRICKS_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*"
    r"\{[^}]*?\b(?:pstricks(?:-\w+)?|pst-\w+)\b|"
    r"\\begin\s*\{pspicture\*?\}|\\pspicture\b|\\psset\b"
)
_MINTED_FROZEN_RE = re.compile(r"frozencache")
_BITMAP_FONT_PKGS = re.compile(
    r"\\usepackage(?:\[[^]]*\])?\{[^}]*\b(bbm|bbmfonts|dsfont|bbold|yfonts|wasy|wasysym)\b"
)


def route_project(root: Path, *, prefer: str = "tectonic") -> RouteDecision:
    r"""静态预检路由（docs/08 §4.2 表）：编译前即可决策的引擎分配。

    - `\documentstyle` → `latex209_suspect` 降级标记，**不再无条件 reject**
      （TL2026 实测 ~23% FP：cond-mat/9703223 等真 2.09 源编出 clean——
      先试编，fixloop `latex209_reject` gate 在真 2.09 错时兜底拒；
      inject 层仍按原样拒，两类 reject 在账本里分流）
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

    # --- \documentstyle → latex209_suspect 标记（任何文件里出现都算）
    latex209_suspect = [
        str(p.relative_to(root))
        for p, v in vis.items()
        if re.search(r"\\documentstyle\b", v)
    ]

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
    if latex209_suspect:
        reasons.append(
            f"latex209_suspect: {', '.join(latex209_suspect)} "
            "\\documentstyle → 试编不定死（fixloop gate 兜底拒）"
        )
    if non_utf8:
        reasons.append("非 UTF-8 源 → 需 iconv 转码预处理或 inputenc 路注")
    return RouteDecision(
        engines=engines,
        reject=None,
        reasons=reasons,
        non_utf8=non_utf8,
        latex209_suspect=bool(latex209_suspect),
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
