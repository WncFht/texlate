"""Engine — fixloop 规则引擎主循环 (docs/08 §5, bench/py/fixloop.py 移植)。

管线: ``eng.compile → parse_log → taxonomy.classify → gate → match → apply →
重编``, ≤``meta.loop.max_rounds`` 轮 (默认 8)。

与 ``compile/engine.py`` 的边界: 本模块只依赖 :class:`Engine` Protocol
(docs/08:198-225 签名), 不实现引擎 —— xelatex/tectonic 引擎由
impl-compile 并行开发, 结构上满足本 Protocol 即可对接。

phase 语义 (rules.yaml 注释复制):
  ``gate``     每轮分类后最先评估 (spike 里 latex209 硬编码短路, L748-755)
  ``precheck`` 编译前一次性 (静态路由 + 装包预检)
  ``loop``     每轮错误驱动; 同 phase 按 order 升序, 每轮至多一条成功应用
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from texlate.compile.fixloop import builtins, ctan
from texlate.compile.fixloop._yamlish import load_yaml
from texlate.compile.fixloop.logparse import (
    ErrReport,
    Taxonomy,
    parse_log,
    parse_text,
)
from texlate.compile.inject import find_main_tex as _inject_find_main_tex
from texlate.textutil import decode_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.cases import CaseSink

__all__ = [
    "Engine",
    "LlmHook",
    "LoopCtx",
    "Rule",
    "Ruleset",
    "RulesetError",
    "find_main_tex",
    "fixloop",
    "load_ruleset",
]

RULES_PATH = Path(__file__).with_name("rules.yaml")
_DOC_RE = re.compile(r"\\document(class|style)")
_REJECT_PREFIX = "REJECT:"


# ════════════════════════════════════════════════════════════════
# Engine 协议 (docs/08:198-225 逐字签名; impl-compile 的实现对接此处)
# ════════════════════════════════════════════════════════════════


class CompResLike(Protocol):
    """``Engine.compile`` 返回的结构化结果 (属性级 duck-typing)。

    对接 impl-compile ``compile/engine.py`` 的 ``CompRes`` (L56-76):
    ``pdf: Path|None`` + ``has_pdf`` + ``pdf_bytes`` + ``seconds`` +
    ``stdout_tail`` (tectonic 无 .log 兜底)。spike 时代字段名 ``sec``
    经 getattr 链兼容。
    """

    pdf: object  # Path | None | bool
    log_path: Path | None
    timed_out: bool
    seconds: float


class Engine(Protocol):
    """编译引擎适配层 —— xelatex/tectonic 各一实现 (impl-compile 侧)。

    与 impl ``Engine`` Protocol (compile/engine.py:366) 的调用面兼容:
    本模块只用 ``compile(wdir, main, passes=...)`` / ``probe_file(fname[, cwd])``
    / ``install_file(fname, font_related=...)`` / ``rebuild_fontmaps()`` /
    ``filemap(fname)`` 五个方法 + ``caps``。
    """

    caps: set[str] | frozenset[str]  # {kpsewhich,tlmgr,updmap,shell_escape,bundle}

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        flags: Iterable[str] | None = None,
        best_effort: bool = False,
    ) -> CompResLike:
        """沙箱编译 ``main`` (相对 wdir), ≤``passes`` 轮 → CompResLike。

        ``flags`` = ``ctx.engine_flags`` 累计的引擎 CLI flag —— 经 impl 侧
        seam 落 argv；引擎不收的项进 ``CompResLike.flags_dropped`` (getattr
        容错读取)。
        """
        ...

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        """Kpsewhich | 本地+bundle 探测; 命中返路径, 缺返 None。

        ``cwd`` 可选 (impl 签名 ``probe_file(fname, *, cwd=None)``): 传 wdir
        时把"工程目录内已存在"也算命中 —— ctan_fetch 平铺落盘的复核靠它。
        """
        ...

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """装提供 ``fname`` 的包: tlmgr --usermode | ctan_fetch 降级。"""
        ...

    def rebuild_fontmaps(self) -> None:
        """updmap-user | noop (tectonic)。"""
        ...

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包索引: tlmgr search --file | tlpdb 表 → 候选包名。"""
        ...


RunFn = Callable[..., tuple[int | None, str, float, bool]]
LlmHook = Callable[["LoopCtx", "ErrReport"], tuple[bool, str]]


class RulesetError(ValueError):
    """rules.yaml 结构校验失败。"""


# ── Engine 适配辅助 (impl-compile CompRes/Engine 的字段名差分吸收) ──


def _probe(eng: Engine, fname: str, cwd: Path | None = None) -> str | None:
    """``probe_file`` 兼容调用: 支持可选 ``cwd`` kwarg 的 impl 直传; 裸 Protocol 实现退无参。"""
    if cwd is not None:
        try:
            return eng.probe_file(fname, cwd=cwd)
        except TypeError:
            pass  # 裸签名实现 → 退回 fname-only
    return eng.probe_file(fname)


def _res_has_pdf(res: CompResLike) -> bool:
    """Pdf 产出判定: impl ``has_pdf`` (非空文件) 优先, 否则 pdf 字段真值。"""
    hp = getattr(res, "has_pdf", None)
    # 鸭子实现若把 has_pdf 写成方法而非 property，bound method 恒真——调用之
    if hp is not None:
        return bool(hp() if callable(hp) else hp)
    return bool(getattr(res, "pdf", False))


def _note_dropped_flags(ctx: LoopCtx, res: CompResLike) -> None:
    """引擎经 ``flags`` seam 丢回的项 → ctx.flags_dropped + advisory (每 flag 一次)。"""
    for fl in getattr(res, "flags_dropped", None) or []:
        if fl not in ctx.flags_dropped:
            ctx.flags_dropped.append(fl)
            ctx.advisories.append(f"engine flag unsupported on {ctx.engine_name}: {fl}")


def _report_of(res: CompResLike, warn_patterns: list[dict[str, Any]]) -> ErrReport:
    """CompRes → ErrReport: 优先 .log 文件; 缺席/空错误时 stdout_tail 兜底。

    tectonic 有时不写 .log (impl engine.py:749-756 同策略); stderr 的
    ``error: msg`` 行归一成 ``! msg`` 喂同一套 taxonomy。
    """
    log_path = getattr(res, "log_path", None)
    rep = parse_log(Path(log_path) if log_path else None, warn_patterns)
    if rep.n_bang == 0:
        tail = getattr(res, "stdout_tail", "") or ""
        if tail:
            alt = parse_text(re.sub(r"(?m)^error:\s*", "! ", tail), warn_patterns)
            if alt.n_bang or rep.raw == "":
                rep = alt
    return rep


# ════════════════════════════════════════════════════════════════
# Ruleset —— rules.yaml 的校验装载 + phase 查询
# ════════════════════════════════════════════════════════════════

_ACTION_KINDS = {
    "scan_install",
    "install_file",
    "run_tool",
    "regex_rewrite",
    "builtin_transform",
    "reject_route",
    "escalate_llm",
}
_PHASES = {"gate", "precheck", "loop"}
_MODES = {"native", "same", "degrade", "unsupported", "skip"}


@dataclass(slots=True)
class Rule:
    """单条规则 (rules.yaml ``rules:`` 列表元素的校验视图)。"""

    raw: dict[str, Any]

    @property
    def id(self) -> str:
        """规则 id。"""
        return self.raw["id"]

    @property
    def phase(self) -> str:
        """Gate | precheck | loop。"""
        return self.raw["phase"]

    @property
    def order(self) -> int:
        """同 phase 内升序键 (缺省 0)。"""
        return int(self.raw.get("order", 0))

    @property
    def when(self) -> dict[str, Any]:
        """触发条件 (category/payload_required/main_head_contains/any/always)。"""
        return self.raw.get("when") or {}

    @property
    def condition(self) -> dict[str, Any]:
        """执行前置条件原语 dict (全键 AND)。"""
        return self.raw.get("condition") or {}

    @property
    def action(self) -> dict[str, Any]:
        """``{kind, function?, params?}`` 动作描述。"""
        return self.raw.get("action") or {}

    @property
    def engines(self) -> dict[str, Any]:
        """``engines.<name>`` 执行规格表 (mode/degrade/fallback)。"""
        return self.raw.get("engines") or {}

    @property
    def status(self) -> str:
        """stats.status, 缺省 active。"""
        return str((self.raw.get("stats") or {}).get("status", "active"))

    def engine_spec(self, engine_name: str) -> dict[str, Any]:
        """该引擎下的执行规格; 未声明的引擎按 native 处理。"""
        return self.engines.get(engine_name) or {"mode": "native"}


class Ruleset:
    """rules.yaml 装载结果: meta + taxonomy + rules + filemap/capabilities。"""

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        """校验 data → 切 meta/taxonomy/rules 三段 + phase 索引。"""
        self.path = path
        self.raw = data
        problems = self._validate(data)
        if problems:
            raise RulesetError("rules.yaml 校验失败:\n" + "\n".join(problems))
        self.meta: dict[str, Any] = data.get("meta") or {}
        self.loop_cfg: dict[str, Any] = self.meta.get("loop") or {}
        self.filemap_cfg: dict[str, Any] = data.get("filemap") or {}
        self.capabilities: dict[str, Any] = data.get("capabilities") or {}
        self.warn_patterns: list[dict[str, Any]] = data.get("warnings") or []
        tax_entries = data.get("taxonomy") or []
        if not self.loop_cfg.get("warn_driven_fixes", True):
            tax_entries = [e for e in tax_entries if e.get("scope") != "warnings"]
        self.taxonomy = Taxonomy(tax_entries)
        self.rules = [Rule(r) for r in data.get("rules") or []]
        self._by_phase: dict[str, list[Rule]] = {
            p: sorted((r for r in self.rules if r.phase == p), key=lambda r: r.order)
            for p in _PHASES
        }

    @staticmethod
    def _validate(data: dict[str, Any]) -> list[str]:  # 校验项逐条即分支
        probs: list[str] = []
        if not isinstance(data, dict):
            return ["顶层必须是 map"]
        if data.get("version") != 1:
            probs.append(f"version 应为 1, 得 {data.get('version')!r}")
        for i, r in enumerate(data.get("rules") or []):
            tag = r.get("id", f"#{i}")
            probs.extend(
                f"rule {tag}: 缺字段 {k}"
                for k in ("id", "phase", "when", "action")
                if k not in r
            )
            if r.get("phase") not in _PHASES:
                probs.append(f"rule {tag}: phase 非法 {r.get('phase')!r}")
            kind = (r.get("action") or {}).get("kind")
            if kind not in _ACTION_KINDS:
                probs.append(f"rule {tag}: action.kind 非法 {kind!r}")
            fn = (r.get("action") or {}).get("function")
            if kind == "builtin_transform" and fn not in builtins.TRANSFORM_FNS:
                probs.append(f"rule {tag}: 未知 builtin_transform {fn!r}")
            rewrites = ((r.get("action") or {}).get("params") or {}).get(
                "rewrites"
            ) or []
            probs.extend(
                f"rule {tag}: 未知 rewrite function {rw['function']!r}"
                for rw in rewrites
                if "function" in rw and rw["function"] not in builtins.REWRITE_FNS
            )
            for eng_name, spec in (r.get("engines") or {}).items():
                mode = (spec or {}).get("mode")
                if mode not in _MODES:
                    probs.append(f"rule {tag}: engines.{eng_name}.mode 非法 {mode!r}")
        return probs

    @classmethod
    def load(cls, path: Path | None = None) -> Ruleset:
        """装载 rules.yaml (默认本包附带; PyYAML 在则走全量解析)。"""
        p = path or RULES_PATH
        return cls(load_yaml(p), path=p)

    def phase(self, name: str) -> list[Rule]:
        """某 phase 的规则按 order 升序。"""
        return self._by_phase.get(name, [])

    def max_rounds(self) -> int:
        """``meta.loop.max_rounds`` (缺省 8)。"""
        return int(self.loop_cfg.get("max_rounds", 8))


def load_ruleset(path: Path | None = None) -> Ruleset:
    """``Ruleset.load`` 的函数式入口。"""
    return Ruleset.load(path)


# ════════════════════════════════════════════════════════════════
# LoopCtx —— 每格运行上下文 (spike Ctx, L133-143)
# ════════════════════════════════════════════════════════════════


@dataclass
class LoopCtx:
    """单格 fixloop 的运行上下文: 工程目录/主文件/已应用规则/安装记录。"""

    wdir: Path
    engine_name: str
    main_rel: str | None = None
    applied: set[str] = field(default_factory=set)  # "{rule_id}:{payload}"
    actions: list[dict[str, Any]] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    engine_flags: list[str] = field(default_factory=list)
    #: 经 ``compile(flags=…)`` seam 被引擎拒放的 flag（支持子集外）——
    #: 每 flag 记一次 advisory，cell 落 ``engine_flags_dropped``。
    flags_dropped: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    runner: RunFn | None = None
    llm_hook: LlmHook | None = None
    #: 本轮 taxonomy 分类结果 —— llm_hook 的 prompt 装配读这两个字段
    #: (LlmHook 签名固定 (ctx, rep), cat/pay 经 ctx 传递)。
    err_cat: str | None = None
    err_pay: str | None = None
    err_head: str = ""  # 本轮错误 blob (ctx_suggests 条件用)
    _texts: dict[Path, str | None] = field(default_factory=dict, repr=False)

    def tex_files(self, exts: Iterable[str] = (".tex", ".sty", ".cls")) -> list[Path]:
        """工程内指定扩展名文件 (排序稳定)。"""
        exts_t = tuple(exts)
        return [
            p
            for p in sorted(self.wdir.rglob("*"))
            if p.suffix in exts_t and p.is_file()
        ]

    def read(self, f: Path) -> str | None:
        """utf-8 读文件 (进程内缓存, errors=replace); 不可读 → None。"""
        if f not in self._texts:
            try:
                self._texts[f] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._texts[f] = None
        return self._texts[f]

    def write(self, f: Path, text: str) -> None:
        """utf-8 写文件并同步缓存。"""
        f.write_text(text, encoding="utf-8")
        self._texts[f] = text

    def invalidate(self, f: Path) -> None:
        """外部改写过 (如字节级转码) 后失效缓存。"""
        self._texts.pop(f, None)

    def main_path(self) -> Path | None:
        """主文件绝对路径 (main_rel 未定 → None)。"""
        return self.wdir / self.main_rel if self.main_rel else None

    def main_head(self, n: int = 3000) -> str:
        r"""主文件前 n 字符 (spike L515 用 3000 判 \documentstyle)。"""
        main = self.main_path()
        if main is None:
            return ""
        return (self.read(main) or "")[:n]

    def source_blob(self) -> str:
        """全部 tex 源拼接 (source_contains 条件用)。"""
        return "\n".join(t for f in self.tex_files() if (t := self.read(f)))

    def run_tool(
        self, argv: list[str], timeout: int = 120
    ) -> tuple[int | None, str, bool]:
        """跑外部工具; 默认 subprocess (测试注入 runner)。"""
        if self.runner:
            _rc, out, _sec, to = self.runner(argv, timeout, self.wdir)
            return _rc, out, to
        try:
            p = subprocess.run(  # noqa: S603  # argv 列表无 shell; fixloop 动作原语
                argv,
                cwd=str(self.wdir),
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return None, out, True
        except OSError as e:
            return None, f"{type(e).__name__}: {e}", False
        return p.returncode, p.stdout, False


# ════════════════════════════════════════════════════════════════
# when / condition 评估
# ════════════════════════════════════════════════════════════════


def _substitute(v: Any, payload: str | None) -> Any:  # noqa: ANN401  # yaml 值天然 Any
    """Params 值里的 ``{payload}`` 占位替换。"""
    if isinstance(v, str):
        return v.replace("{payload}", payload or "")
    if isinstance(v, dict):
        return {k: _substitute(x, payload) for k, x in v.items()}
    if isinstance(v, list):
        return [_substitute(x, payload) for x in v]
    return v


def _when_ok(
    when: dict[str, Any], cat: str | None, pay: str | None, ctx: LoopCtx
) -> bool:
    """When 匹配: ``always`` / ``any:[...]`` / 单条 category 条件。"""
    if not when:
        return False
    if when.get("always"):
        return True
    cands: list[dict[str, Any]] = when.get("any") or [when]
    for c in cands:
        if c.get("category") is not None and c["category"] != cat:
            continue
        if c.get("payload_required") and not pay:
            continue
        mhc = c.get("main_head_contains")
        if mhc is not None and mhc not in ctx.main_head():
            continue
        return True
    return False


def _package_version(eng: Engine, fname: str) -> int | None:
    """Probe 到的包文件 ``vX.Y`` 主版本号 (package_version_ge 条件用)。"""
    found = eng.probe_file(fname)
    if not found:
        return None
    try:
        text = Path(found).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(
        r"\\Provides(?:Expl)?(?:Package|Class)\s*\{[^}]*\}[^v\n]*v?(\d+)", text
    )
    return int(m.group(1)) if m else None


def _cond_ok(  # noqa: C901, PLR0911, PLR0912  # 条件原语分派表, 每键一处
    cond: dict[str, Any],
    rule: Rule,
    ctx: LoopCtx,
    eng: Engine,
    pay: str | None,
) -> tuple[bool, str]:
    """Condition 全部键 AND; ``any`` 子键 OR。未知键 fail-closed。"""
    for key, val in cond.items():
        v = _substitute(val, pay)
        if key == "any":
            subs = v if isinstance(v, list) else []
            ok = any(
                _cond_ok(sub, rule, ctx, eng, pay)[0]
                for sub in subs
                if isinstance(sub, dict)
            )
            if not ok:
                return False, "any 子条件全不中"
        elif key == "tool_available":
            if not shutil.which(str(v)):
                return False, f"tool {v} unavailable"
        elif key == "cap_available":
            if str(v) not in getattr(eng, "caps", set()):
                return False, f"cap {v} missing"
        elif key == "engine_in":
            if ctx.engine_name not in v:
                return False, f"engine {ctx.engine_name} not in {v}"
        elif key == "main_head_contains":
            if str(v) not in ctx.main_head():
                return False, "main head 无该子串"
        elif key == "source_contains":
            if not re.search(str(v), ctx.source_blob()):
                return False, "源码无该 pattern"
        elif key == "ctx_suggests":
            if not re.search(str(v), ctx.err_head or ""):
                return False, "err ctx 无提示"
        elif key == "fileset":
            has = v.get("has_ext") or []
            lacks = v.get("lacks_ext") or []
            names = {p.suffix for p in ctx.wdir.rglob("*") if p.is_file()}
            if any(e not in names for e in has) or any(e in names for e in lacks):
                return False, "fileset 不满足"
        elif key == "cache_dir_glob":
            if not any(ctx.wdir.glob(str(v))):
                return False, f"无 {v} 匹配"
        elif key == "vendored_shadow":
            if not builtins.find_vendored_shadows(ctx, eng, (".sty", ".cls")):
                return False, "无遮蔽候选"
        elif key == "package_version_ge":
            got = _package_version(eng, str(v.get("file", "")))
            if got is None or got < int(v.get("version", 0)):
                return False, f"{v.get('file')} 版本 {got} < {v.get('version')}"
        elif key == "prim_read_form":
            prim = re.escape(str(v))
            if not re.search(rf"\\if[a-zA-Z@]*\s*\\{prim}\b", ctx.source_blob()):
                return False, f"无 \\if*\\{v} 读取语境"
        elif key == "shim_known":
            shim_map = ((rule.action.get("params") or {}).get("shim_map")) or {}
            if not builtins.shim_pkgs_in_use(ctx, shim_map):
                return False, "工程未用 shim_map 内包"
        else:
            return False, f"unknown condition {key!r}"
    return True, ""


# ════════════════════════════════════════════════════════════════
# 动作分派 —— 7 种 action.kind (docs/08:260)
# ════════════════════════════════════════════════════════════════


def _patch_files(
    ctx: LoopCtx, exts: Iterable[str], subs: list[tuple[re.Pattern[str], Any]]
) -> int:
    """对全部匹配文件做 ``pattern→repl|function`` 替换; 返回改动文件数 (spike L245-261)。"""
    n = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for pat, repl in subs:
            nt = pat.sub(repl, nt)
        if nt != t:
            ctx.write(f, nt)
            n += 1
    return n


def _compile_rewrites(
    rewrites: list[dict[str, Any]],
) -> list[tuple[re.Pattern[str], Any]]:
    subs = []
    for rw in rewrites:
        flags = 0
        for fl in rw.get("flags") or []:
            flags |= getattr(re, fl, 0)
        pat = re.compile(rw["pattern"], flags)
        if "function" in rw:
            subs.append((pat, builtins.REWRITE_FNS[rw["function"]]))
        else:
            subs.append((pat, rw.get("repl", "")))
    return subs


def _apply_scan_install(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""静态扫 ``\usepackage``/``\documentclass`` → 探测缺失 → 批量装 (spike L594-618)。"""
    need: set[str] = set()
    noise = re.compile(params["noise_filter"]) if params.get("noise_filter") else None
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None:
            continue
        for sp in params.get("scan_patterns") or []:
            for m in re.finditer(sp["regex"], t):
                names = [m.group(1)]
                if sp.get("split"):
                    names = m.group(1).split(sp["split"])
                for nm in names:
                    name = nm.strip()
                    if not name:
                        continue
                    fname = name + sp.get("suffix", "")
                    if noise and not noise.match(name):
                        continue
                    need.add(fname)
    missing = sorted(f for f in need if not _probe(eng, f, cwd=ctx.wdir))
    installed = [f for f in missing if eng.install_file(f)]
    ctx.installed.extend(installed)
    return True, f"missing files={missing} -> installed {installed}"


def _filemap_candidates(eng: Engine, fname: str) -> list[str]:
    """``filemap`` 查询 + tectonic 侧 tlpdb 索引兜底 (CtanFetcher.peek_index)。"""
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname) or idx.suggest(fname.rsplit(".", 1)[0])
    return pkgs


def _apply_install_file(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any]
) -> tuple[bool, str]:
    """缺文件 → probe → install_file → 复核; font_related → rebuild_fontmaps (spike L264-276)。"""
    font_exts = tuple(params.get("font_related_exts") or ())
    candidates = []
    if params.get("try_exts"):
        candidates = [params["file"] + e for e in params["try_exts"]]
    else:
        candidates = [params["file"]]
    for fname in candidates:
        font_related = bool(params.get("font_related")) or fname.endswith(font_exts)
        # probe 带 cwd=wdir: 工程内文件/ctan_fetch 平铺落盘均算命中
        # (tectonic probe_file 无 cwd 恒 None, 复核必败)
        if _probe(eng, fname, cwd=ctx.wdir):
            if params.get("already_present_ok", True):
                return True, f"already-present {fname}"
            continue
        if not eng.install_file(fname, font_related=font_related):
            pkgs = _filemap_candidates(eng, fname)
            hint = f" (candidates: {', '.join(pkgs)})" if pkgs else ""
            ctx.advisories.append(f"no package provides {fname}{hint}")
            continue
        if not _probe(eng, fname, cwd=ctx.wdir):
            ctx.advisories.append(f"installed but {fname} still not found")
            continue
        ctx.installed.append(fname)
        if font_related:
            eng.rebuild_fontmaps()
        return True, f"installed {fname}"
    return False, f"no candidate file installed for {params['file']}"


def _apply(  # noqa: C901, PLR0911  # action.kind 分派表, 每种一处
    rule: Rule, ctx: LoopCtx, eng: Engine, pay: str | None, rep: ErrReport
) -> tuple[bool, str]:
    """按 action.kind 分派执行一条规则 → (applied, note)。"""
    action = rule.action
    kind = action.get("kind")
    params = _substitute(action.get("params") or {}, pay)
    if kind == "scan_install":
        return _apply_scan_install(ctx, eng, params)
    if kind == "install_file":
        return _apply_install_file(ctx, eng, params)
    if kind == "run_tool":
        rc, out, to = ctx.run_tool(
            list(params.get("argv") or []), int(params.get("timeout", 120))
        )
        ctx.events.append(
            f"run {' '.join(params.get('argv') or [])} -> rc={rc}{' TIMEOUT' if to else ''}"
        )
        return True, f"rc={rc}{' TIMEOUT' if to else ''} {out[-200:].strip()}"
    if kind == "regex_rewrite":
        subs = _compile_rewrites(params.get("rewrites") or [])
        n = _patch_files(ctx, params.get("exts") or (".tex", ".sty"), subs)
        if params.get("engine_flags"):
            for fl in params["engine_flags"]:
                if fl not in ctx.engine_flags:
                    ctx.engine_flags.append(fl)
        return (n > 0), f"rewrite in {n} files"
    if kind == "builtin_transform":
        fn = builtins.TRANSFORM_FNS[action["function"]]
        return fn(ctx, eng, pay, params)
    if kind == "reject_route":
        route = params.get("route", "")
        reason = params.get("reason", "")
        return True, f"{_REJECT_PREFIX} route={route} {reason}".strip()
    if kind == "escalate_llm":
        if ctx.llm_hook is None:
            return False, "no llm hook; stub (spike L523-527 parity)"
        return ctx.llm_hook(ctx, rep)
    return False, f"unknown action kind {kind!r}"


# ════════════════════════════════════════════════════════════════
# 规则匹配 (spike pick_and_apply L549-565 + mode/condition/fallback)
# ════════════════════════════════════════════════════════════════


def _match_apply(  # noqa: C901, PLR0913, PLR0917  # spike pick_and_apply 签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> tuple[Rule | None, str]:
    """Order 序找第一条 when+condition 过、mode 可行且应用成功的规则。"""
    for rule in rs.phase("loop"):
        key = f"{rule.id}:{pay}"
        if key in ctx.applied:
            continue
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.engine_name)
        mode = spec.get("mode", "native")
        if mode == "skip" or (mode == "degrade" and spec.get("degrade") == "skip"):
            continue
        if mode == "unsupported":
            if spec.get("fallback") == "escalate_llm" and ctx.llm_hook is not None:
                applied, note = ctx.llm_hook(ctx, rep)
                if applied:
                    ctx.applied.add(key)
                    return rule, f"escalated: {note}"
            ctx.advisories.append(f"{rule.id} unsupported on {ctx.engine_name}")
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay)
        if not ok:
            ctx.events.append(f"rule {rule.id}: cond skip ({why})")
            continue
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001  # 规则崩溃=放弃该条, 试下一条 (spike L557-559)
            applied, note = False, f"rule crashed: {type(e).__name__}: {e}"
        if applied:
            ctx.applied.add(key)
            return rule, note
        if note:
            ctx.events.append(f"rule {rule.id}: skip ({note})")
        fb = spec.get("fallback")
        if fb == "advisory":
            ctx.advisories.append(f"{rule.id}: {note}")
    return None, ""


# ════════════════════════════════════════════════════════════════
# 主循环 (spike run_cell L691-792 + docs/08:295-310 伪码)
# ════════════════════════════════════════════════════════════════


def find_main_tex(proj: Path) -> Path | None:
    r"""主文件定位：先严格档后宽松档。

    严格档 = ``inject.find_main_tex``（注释遮盖 + 语种排序）；无命中退
    宽松档——``\documentclass|style`` 在即可（fixloop 的职责是修坏论文，
    ``\begin{document}`` 缺失正是要修的对象；spike L575-587 口径保留）。
    """
    strict = _inject_find_main_tex(proj)
    if strict is not None:
        return strict
    cands = []
    for f in sorted(proj.rglob("*.tex")):
        with contextlib.suppress(OSError):
            head = decode_tex(f.read_bytes())[:60000]
            if _DOC_RE.search(head):
                has_body = "\\begin{document}" in head
                depth = len(f.relative_to(proj).parts)
                cands.append((depth, 0 if has_body else 1, str(f)))
    if not cands:
        return None
    cands.sort()
    return Path(cands[0][2])


def _gate_eval(  # noqa: PLR0913, PLR0917  # 与 _match_apply 同签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> str | None:
    """Gate phase 规则逐条评估; REJECT note → verdict ``reject:<rid>``。"""
    for rule in rs.phase("gate"):
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.engine_name)
        if spec.get("mode") == "skip":
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay)
        if not ok:
            ctx.events.append(f"gate {rule.id}: cond skip ({why})")
            continue
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001
            applied, note = False, f"gate crashed: {type(e).__name__}: {e}"
        if applied and note.startswith(_REJECT_PREFIX):
            return f"reject:{rule.id}"
        if applied:
            ctx.applied.add(f"{rule.id}:{pay}")
            ctx.actions.append({"round": -1, "rule": rule.id, "detail": note})
    return None


def _wire_filemap_overrides(
    eng: Engine, overrides: dict[str, Any], ctx: LoopCtx
) -> None:
    """``eng.filemap`` 实例遮蔽: basename 先过手工映射, 未中走原查询。

    xelatex 通路 ``install_file``/``_filemap_candidates`` 共用 ``self.filemap``
    —— 单点遮蔽即全通路生效 (bench 现场 ``eng.filemap = idx.query`` 的既有
    遮蔽也照包, 次序 = overrides → 既有查询; worker 的 ``_RecEngine`` 与
    bench 的 ``_NoSandbox`` 均 ``__setattr__`` 透传, 遮蔽落在真引擎实例上)。
    显式 null = 已知噪声 → 空表短路, 不再落 tlmgr/索引往返。
    """
    orig = getattr(eng, "filemap", None)
    if not callable(orig) or getattr(orig, "overrides_wrapped", False):
        return

    def filemap(fname: str) -> list[str]:
        if fname in overrides:
            v = overrides[fname]
            return [v] if isinstance(v, str) else []
        return list(orig(fname))

    filemap.overrides_wrapped = True  # type: ignore[attr-defined]  # 幂等: 重入不叠包
    try:
        eng.filemap = filemap  # type: ignore[method-assign]  # 实例遮蔽协议方法
    except Exception as e:  # noqa: BLE001  # 遮蔽失败不阻塞: 退化为原生 filemap
        ctx.advisories.append(f"filemap overrides wire failed: {type(e).__name__}: {e}")
    else:
        ctx.events.append("wire filemap overrides")


def _wire_engine(eng: Engine, rs: Ruleset, wdir: Path, ctx: LoopCtx) -> None:
    """引擎侧降级原语注入 (docs/08 §5.3)。

    ``filemap.overrides`` 手工映射对全引擎生效 (实例遮蔽 ``eng.filemap``);
    tectonic 追加: ``install_file`` 内部走 ``self.ctan_fetch`` callable ——
    未注入时这里装上 CtanFetcher (惰性 tlpdb 索引 + rules.yaml
    ``filemap.version_guard`` 的 bundle epoch 接线)。
    """
    _wire_filemap_overrides(eng, rs.filemap_cfg.get("overrides") or {}, ctx)
    if ctx.engine_name != "tectonic":
        return
    if getattr(eng, "ctan_fetch", None) is not None or not hasattr(eng, "ctan_fetch"):
        return
    vg = rs.filemap_cfg.get("version_guard") or {}
    try:
        eng.ctan_fetch = ctan.CtanFetcher(
            wdir,
            overrides=rs.filemap_cfg.get("overrides") or {},
            epoch=(str(vg["texlive_format_epoch"]) if vg.get("enabled") else None),
        )
        ctx.events.append("wire ctan_fetch (lazy tlpdb index)")
    except Exception as e:  # noqa: BLE001  # 注入失败不阻塞: install_* 走 advisory
        ctx.advisories.append(f"ctan_fetch wire failed: {type(e).__name__}: {e}")


def fixloop(  # noqa: C901, PLR0912, PLR0913, PLR0915  # 主循环分支即 spike 状态机
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    corpus_id: str | None = None,
    cond: str | None = None,
    llm_hook: LlmHook | None = None,
    runner: RunFn | None = None,
    case_sink: CaseSink | None = None,
) -> dict[str, Any]:
    """跑一格修复循环 → cell dict (字段与 spike fixloop-results.json 兼容)。

    verdict ∈ clean / acceptable_pdf / dirty_pdf / best_effort_pdf /
    unfixable:<cat> / stuck / max_rounds / reject:<rid> /
    no_errors_no_pdf / no_main_tex
    """
    rs = ruleset or Ruleset.load()
    engine_name = engine_name or getattr(
        eng, "name", rs.meta.get("engine_default", "xelatex")
    )
    wdir = Path(proj)
    cfg = rs.loop_cfg
    max_rounds = int(cfg.get("max_rounds", 8))
    clean_err_max = int(cfg.get("clean_err_max", 3))
    passes = int(cfg.get("compile_passes", 2))
    stuck_n = int(cfg.get("stuck_sig_repeat", 3))

    cell: dict[str, Any] = {
        "project": corpus_id or wdir.name,
        "cond": cond,
        "main": None,
        "engine": engine_name,
        "rounds": [],
        "actions": [],
        "verdict": None,
    }
    ctx = LoopCtx(wdir=wdir, engine_name=engine_name, runner=runner, llm_hook=llm_hook)

    main = find_main_tex(wdir)
    if main is None:
        cell["verdict"] = "no_main_tex"
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell
    ctx.main_rel = str(main.relative_to(wdir))
    cell["main"] = ctx.main_rel
    cell["actions"] = ctx.actions  # 同一 list: precheck/gate/loop 动作汇入一处
    _wire_engine(eng, rs, wdir, ctx)

    # —— precheck phase (第 0 招; 静态路由也在这里) ——
    dummy_rep = parse_log(None, rs.warn_patterns)
    for rule in rs.phase("precheck"):
        if not _when_ok(rule.when, None, None, ctx):
            continue
        spec = rule.engine_spec(engine_name)
        mode = spec.get("mode")
        if mode in ("skip", "unsupported") or (
            mode == "degrade" and spec.get("degrade") == "skip"
        ):
            ctx.events.append(f"precheck {rule.id}: {mode} on {engine_name}")
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, None)
        if not ok:
            ctx.events.append(f"precheck {rule.id}: cond skip ({why})")
            continue
        try:
            applied, note = _apply(rule, ctx, eng, None, dummy_rep)
        except Exception as e:  # noqa: BLE001
            applied, note = False, f"precheck crashed: {type(e).__name__}: {e}"
        cell["actions"].append(
            {"round": 0, "rule": rule.id, "detail": note, "applied": applied}
        )
        if applied and note.startswith(_REJECT_PREFIX):
            cell["verdict"] = f"reject:{rule.id}"
            _record_case(
                case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
            )
            return cell

    prev_sig, sig_n = "", 0
    last_rep: ErrReport | None = None
    for rnd in range(1, max_rounds + 1):
        res = eng.compile(
            wdir, ctx.main_rel, passes=passes, flags=list(ctx.engine_flags)
        )
        _note_dropped_flags(ctx, res)
        rep = _report_of(res, rs.warn_patterns)
        last_rep = rep
        cat, pay = rs.taxonomy.classify(
            rep, timed_out=bool(getattr(res, "timed_out", False))
        )
        ctx.err_cat, ctx.err_pay = cat, pay
        ctx.err_head = (rep.first or "") + "\n" + (rep.ctx or "")
        pdf = _res_has_pdf(res)
        pdf_bytes = getattr(res, "pdf_bytes", None)
        if pdf and pdf_bytes is None:
            pdf_attr = getattr(res, "pdf", None)
            try:
                pdf_bytes = Path(pdf_attr).stat().st_size if pdf_attr else 0
            except (OSError, TypeError):
                pdf_bytes = 0
        entry = {
            "round": rnd,
            "pdf": pdf,
            "pdf_bytes": int(pdf_bytes or 0),
            "n_errors": rep.n_bang,
            "category": cat,
            "payload": pay,
            "warnings": list(rep.warnings),
            "line_no": rep.line_no,
            "file_stack": rep.file_stack,
            "sec": round(float(getattr(res, "seconds", getattr(res, "sec", 0.0))), 1),
        }
        cell["rounds"].append(entry)
        ctx.events.append(
            f"r{rnd}: pdf={pdf} err={rep.n_bang} cat={cat} pay={pay} ({entry['sec']}s)"
        )
        # —— 终止判据 (spike L742-761 + docs/08:312) ——
        if pdf and rep.n_bang == 0 and cat not in rs.taxonomy.warn_cats:
            # spike 首门 `pdf and nerr==0 → clean`; v1.1 放行 warn_* 伪类别
            # 让 warning 驱动的修复轮有机会跑 (non_utf8_source)
            cell["verdict"] = "clean"
            break
        if cat in (None, "clean"):
            cell["verdict"] = "clean" if pdf else "no_errors_no_pdf"
            break
        v = _gate_eval(rs, ctx, eng, cat, pay, rep)
        if v:
            cell["verdict"] = v
            break
        sig = f"{cat}:{pay}"
        sig_n = sig_n + 1 if sig == prev_sig else 1
        prev_sig = sig
        if sig_n >= stuck_n:
            cell["verdict"] = "stuck"
            break
        # —— loop 规则匹配 + 应用 ——
        rule, note = _match_apply(rs, ctx, eng, cat, pay, rep)
        if rule is None:
            cell["verdict"] = f"unfixable:{cat}" if not pdf else "dirty_pdf"
            break
        if note.startswith(_REJECT_PREFIX):
            cell["verdict"] = f"reject:{rule.id}"
            break
        cell["actions"].append({"round": rnd, "rule": rule.id, "detail": note})
        ctx.events.append(f"apply {rule.id}: {note}")
    else:
        cell["verdict"] = "max_rounds"

    # —— best-effort 兜底 pass: 规则耗尽且末轮无 pdf → 去 halt-on-error 让
    # TeX 错误恢复跑到底救残页 (astro-ph/0306068 型真回归: 首错即停 vs
    # nonstopmode 续跑出 partial pdf)。reject:* 是语义拒绝不救; clean/
    # dirty/acceptable 已有 pdf 不救; timeout 重跑大概率再超时, 不救。
    v_now = str(cell["verdict"] or "")
    if (
        v_now
        and not v_now.startswith("reject:")
        and v_now not in ("clean", "acceptable_pdf", "dirty_pdf", "unfixable:timeout")
        and not (cell["rounds"] and cell["rounds"][-1]["pdf"])
    ):
        sres = eng.compile(
            wdir,
            ctx.main_rel,
            passes=1,
            best_effort=True,
            flags=list(ctx.engine_flags),
        )
        _note_dropped_flags(ctx, sres)
        srep = _report_of(sres, rs.warn_patterns)
        spdf = _res_has_pdf(sres)
        cell["rounds"].append(
            {
                "round": len(cell["rounds"]) + 1,
                "salvage": True,
                "pdf": spdf,
                "pdf_bytes": int(getattr(sres, "pdf_bytes", 0) or 0),
                "n_errors": srep.n_bang,
                "category": None,
                "payload": None,
                "warnings": list(srep.warnings),
                "line_no": srep.line_no,
                "file_stack": srep.file_stack,
                "sec": round(float(getattr(sres, "seconds", 0.0)), 1),
            }
        )
        cell["actions"].append(
            {
                "round": "salvage",
                "rule": "_best_effort_pass",
                "detail": f"nonstopmode 兜底: pdf={spdf} err={srep.n_bang}",
            }
        )
        ctx.events.append(f"salvage best_effort: pdf={spdf} err={srep.n_bang}")
        if spdf:
            cell["verdict"] = "best_effort_pdf"

    # —— 汇总最终态 (spike L776-791) ——
    last = cell["rounds"][-1] if cell["rounds"] else {}
    cell["final_pdf"] = bool(last.get("pdf"))
    cell["final_errors"] = last.get("n_errors")
    cell["final_cat"] = last.get("category")
    cell["installed"] = ctx.installed
    cell["advisories"] = ctx.advisories
    cell["engine_flags"] = ctx.engine_flags
    cell["engine_flags_dropped"] = ctx.flags_dropped
    cell["log"] = ctx.events
    if last_rep is not None:  # triage 原料: 终态错误上下文 (docs/08:318 log_excerpt)
        head = "\n".join(x for x in (last_rep.first, last_rep.ctx) if x)
        cell["log_excerpt"] = (head or last_rep.tail)[:2000]
    cell["started_fail"] = not (cell["rounds"] and cell["rounds"][0]["pdf"])
    if cell["verdict"] in (None, "max_rounds", "stuck") and cell["final_pdf"]:
        cell["verdict"] = "dirty_pdf" if (last.get("n_errors") or 9) > 0 else "clean"
    if (
        cell["final_pdf"]
        and (cell["final_errors"] or 0) <= clean_err_max
        and cell["verdict"] == "dirty_pdf"
    ):
        cell["verdict"] = "acceptable_pdf"
    _record_case(
        case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
    )
    return cell


def _record_case(
    sink: CaseSink | None,
    cell: dict[str, Any],
    *,
    corpus_id: str | None,
    cond: str | None,
    engine_name: str,
) -> None:
    """沉淀 cases.jsonl (docs/08 §5.5); sink 缺省即不写。"""
    if sink is None:
        return
    sink.record(cell, corpus_id=corpus_id, cond=cond, engine=engine_name)
