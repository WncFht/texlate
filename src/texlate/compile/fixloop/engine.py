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
from texlate.compile.inject import classify_no_main as _classify_no_main
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

#: yaml 模式串占位符 → builtins 原语族 (扩表免手同步: 1e0e5c8 手工
#: 13→75 交替即此债)。``@pdftex_prims`` 在任何字符串值里出现即展开成
#: ``(?:…)`` 非捕获交替——按长度降序排, 防短名前缀截长名。
_FAMILY_TOKENS: dict[str, frozenset[str]] = {
    "@pdftex_prims": builtins.PDFTEX_PRIMS,
}


def _expand_family_tokens(node: Any) -> Any:  # noqa: ANN401  # yaml 树天然 Any
    """递归展开 ``_FAMILY_TOKENS`` 占位符 → 正则交替片段 (yaml 全树)。"""
    if isinstance(node, str):
        for tok, fam in _FAMILY_TOKENS.items():
            if tok in node:
                alts = "|".join(sorted(fam, key=lambda s: (-len(s), s)))
                node = node.replace(tok, f"(?:{alts})")
        return node
    if isinstance(node, list):
        return [_expand_family_tokens(x) for x in node]
    if isinstance(node, dict):
        return {k: _expand_family_tokens(v) for k, v in node.items()}
    return node


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

    def compile(  # noqa: PLR0913  # 镜像 impl Engine.compile 调用面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        timeout: float = 240.0,  # 同 compile/engine.py DEFAULT_TIMEOUT
        flags: Iterable[str] | None = None,
        best_effort: bool = False,
    ) -> CompResLike:
        """沙箱编译 ``main`` (相对 wdir), ≤``passes`` 轮 → CompResLike。

        ``timeout`` = 单格编译预算秒 (fixloop 传 ``meta.loop.timeout_sec``
        或调用方覆盖); ``flags`` = ``ctx.engine_flags`` 累计的引擎 CLI
        flag —— 经 impl 侧 seam 落 argv；引擎不收的项进
        ``CompResLike.flags_dropped`` (getattr 容错读取)。
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


def _when_problems(when: Any, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``when`` 段键名白名单校验 (typo 键在旧 _when_ok 下是 fail-open 面)。"""
    if when is None:
        return []
    if not isinstance(when, dict):
        return [f"rule {tag}: when 必须是 map"]
    probs = [f"rule {tag}: when 未知键 {k!r}" for k in when if k not in _WHEN_KEYS]
    anys = when.get("any")
    if anys is not None:
        if not isinstance(anys, list):
            probs.append(f"rule {tag}: when.any 必须是 list")
        else:
            for j, c in enumerate(anys):
                if not isinstance(c, dict):
                    probs.append(f"rule {tag}: when.any[{j}] 必须是 map")
                else:
                    probs.extend(
                        f"rule {tag}: when.any[{j}] 未知键 {k!r}"
                        for k in c
                        if k not in _WHEN_ITEM_KEYS
                    )
    return probs


def _cond_problems(cond: Any, tag: str) -> list[str]:  # noqa: ANN401  # yaml 值天然 Any
    """``condition`` 段键名白名单 (``any`` 子表递归); 与 _cond_ok 分派同源。"""
    if cond is None:
        return []
    if not isinstance(cond, dict):
        return [f"rule {tag}: condition 必须是 map"]
    probs = [f"rule {tag}: condition 未知键 {k!r}" for k in cond if k not in _COND_KEYS]
    for j, sub in enumerate(cond.get("any") or []):
        probs.extend(_cond_problems(sub, f"{tag}.any[{j}]"))
    return probs


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
#: ``when:`` 段合法键 (顶层) / ``any:`` 子项键 —— 键名 typo (``categry:``)
#: 旧行为是对全 category 点火 (fail-open), 白名单 load 期拦 + _when_ok
#: 对无可识别键的候选 fail-closed, 与 _cond_ok 未知键语义对称。
_WHEN_KEYS = frozenset(
    {"always", "any", "category", "payload_required", "main_head_contains"}
)
_WHEN_ITEM_KEYS = frozenset({"category", "payload_required", "main_head_contains"})
#: ``condition:`` 段合法键 —— 与 _cond_ok 分派表一一对应。
_COND_KEYS = frozenset(
    {
        "any",
        "tool_available",
        "cap_available",
        "engine_in",
        "main_head_contains",
        "source_contains",
        "ctx_suggests",
        "fileset",
        "cache_dir_glob",
        "vendored_shadow",
        "package_version_ge",
        "prim_read_form",
        "shim_known",
    }
)


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
            probs.extend(_when_problems(r.get("when"), tag))
            probs.extend(_cond_problems(r.get("condition"), tag))
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
        return cls(_expand_family_tokens(load_yaml(p)), path=p)

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
        exts_t = tuple(e.lower() for e in exts)
        return [
            p
            for p in sorted(self.wdir.rglob("*"))
            if p.suffix.lower() in exts_t and p.is_file()
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
    """When 匹配: ``always`` / ``any:[...]`` / 单条 category 条件。

    无可识别键的候选 fail-closed (与 _cond_ok 未知键对称)——``categry:``
    型 typo 旧行为是对全 category 点火; load 期另有 _when_problems 白名单。
    """
    if not when:
        return False
    if when.get("always"):
        return True
    cands: list[dict[str, Any]] = when.get("any") or [when]
    for c in cands:
        if not isinstance(c, dict) or not (_WHEN_ITEM_KEYS & c.keys()):
            continue
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
            # 逐行切注释后扫——``% \input foo`` 注释行不该触发安装
            # (pst-notreal 实证; ``\%`` 转义不算注释起点)
            for line in t.splitlines():
                code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
                for m in re.finditer(sp["regex"], code):
                    names = [m.group(1)]
                    if sp.get("split"):
                        names = m.group(1).split(sp["split"])
                    for nm in names:
                        name = nm.strip()
                        if not name:
                            continue
                        # suffix 仅补给无扩展名 (``\input epsf`` → epsf.tex);
                        # 已带扩展名者 (``\input{x.tex}``) 照旧不叠。
                        fname = (
                            name if Path(name).suffix else name + sp.get("suffix", "")
                        )
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


#: 包文件行首依赖声明 —— 注释掉的 ``% \RequirePackage`` 不命中。
_DEP_DECL_RE = re.compile(
    r"^[ \t]*\\(?:RequirePackage|RequirePackageWithOptions|LoadClass|usepackage)"
    r"\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)

#: ``\input stem``/``\input{stem}`` 裸名依赖——行内允许 (pst-* generic 实证:
#: pstricks-add.tex l.27-32 ``\ifx\PSTnodesLoaded\endinput\else \input pst-node \fi``
#: 顺序链, 条件不管照装——probe/install 门控天然无害)。
_DEP_INPUT_RE = re.compile(r"\\input\s+(?:\{([^}\n]*)\}|([^\s{}%\\]+))")

#: 行内注释切尾 —— ``\%`` 转义不算注释起点。
_COMMENT_CUT_RE = re.compile(r"(?<!\\)%")


def _dep_stems(path: Path) -> list[str]:
    r"""包文件依赖名表: 行首 ``\\RequirePackage``/``\\LoadClass`` + 行内 ``\\input``。"""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    stems = [
        stem
        for m in _DEP_DECL_RE.finditer(text)
        for stem in (s.strip() for s in m.group(1).split(","))
        if stem
    ]
    for line in text.splitlines():
        code = _COMMENT_CUT_RE.split(line, maxsplit=1)[0]
        stems += [
            g for m in _DEP_INPUT_RE.finditer(code) if (g := m.group(1) or m.group(2))
        ]
    return stems


def _try_install_dep(ctx: LoopCtx, eng: Engine, stem: str) -> Path | None:
    """单依赖名探测/补装 → 已解析路径 (供闭包续层)。"""
    cands = (
        [stem] if Path(stem).suffix else [f"{stem}.sty", f"{stem}.cls", f"{stem}.tex"]
    )
    for cand in cands:
        if r := _probe(eng, cand, cwd=ctx.wdir):
            return Path(r)
        if eng.install_file(cand):
            ctx.installed.append(cand)
            if r := _probe(eng, cand, cwd=ctx.wdir):
                return Path(r)
            return None
    return None


def _dep_fanout(
    ctx: LoopCtx, eng: Engine, seeds: Iterable[Path], seen: set[str], *, depth: int
) -> None:
    """``seeds`` 各文件依赖声明 BFS 补装 (就地改 ``ctx.installed``/``seen``)。"""
    frontier = list(seeds)
    for _ in range(depth):
        nxt: list[Path] = []
        for p in frontier:
            for stem in _dep_stems(p):
                if stem in seen:
                    continue
                seen.add(stem)
                if r := _try_install_dep(ctx, eng, stem):
                    nxt.append(r)
        if not nxt:
            return
        frontier = nxt


def _install_dep_closure(
    ctx: LoopCtx, eng: Engine, fname: str, path: str | None, *, depth: int = 2
) -> None:
    r"""包装文件的依赖闭包补装: 行首 ``\RequirePackage``/``\LoadClass`` 逐层探测+装。

    2410.00012 实证: 装 mhchem 不装 chemgreek (包内 ``\RequirePackage`` 依赖),
    texmf 遮蔽下依赖缺席 → log 尾 Emergency stop。``depth`` 界住链长。
    """
    if path is None:
        return
    _dep_fanout(ctx, eng, [Path(path)], set(ctx.installed) | {fname}, depth=depth)


#: ``-file-line-error`` 锚里的要求方文件 token (``./pst-all.sty:25:``)
_REQ_ANCHOR_RE = re.compile(r"([^\s(){}]+?\.(?:sty|cls|def|clo|tex)):\d+:")


def _requester_paths(ctx: LoopCtx, eng: Engine, rep: ErrReport) -> list[Path]:
    r"""missing_file 报错的要求方文件 (``\\RequirePackage`` 宿主) 逐个解析。

    pst-all 实证 (delta b4akkgal5): meta-wrapper 连发 11 个成员包, 缺谁报谁、
    file:line 锚是要求方自身 —— 一轮补一个要等 8+ 轮 max_rounds; 直接扫
    要求方依赖全表一轮补齐。锚序: 首错行 > ctx > tail 末位 > file_stack
    内层包文件兜底 (无 ``file:line`` 的老式 ``!`` 错误) > popped_files
    尾段 (runaway 把肇事帧先弹走——``\@iiiparbox``/``\next`` 扫描族)。
    """
    names = _REQ_ANCHOR_RE.findall(rep.first or "")
    names += _REQ_ANCHOR_RE.findall(rep.ctx or "")
    names += _REQ_ANCHOR_RE.findall(rep.tail)[::-1]
    stack = [s for s in rep.file_stack[-2:] if s.endswith((".sty", ".cls", ".def"))]
    if not stack:
        # runaway 错报位在最近关闭帧（``popped_files[-1]`` 肇事候选，
        # #78/\@iiiparbox×3/\next 扫描实证）——栈取不到时 popped 尾段递补
        stack = [
            s
            for s in reversed(rep.popped_files)
            if s.endswith((".sty", ".cls", ".def"))
        ]
    names += stack
    out: list[Path] = []
    seen: set[str] = set()
    for name in names:
        base = Path(name).name
        if base in seen:
            continue
        seen.add(base)
        p = Path(name)
        if not p.is_absolute():
            p = ctx.wdir / p
        if not p.exists():
            hit = _probe(eng, base, cwd=ctx.wdir)
            if hit is None:
                continue
            p = Path(hit)
        if p not in out:
            out.append(p)
    return out


def _apply_install_file(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any], rep: ErrReport
) -> tuple[bool, str]:
    """缺文件 → probe → install_file → 复核; font_related → rebuild_fontmaps (spike L264-276)。"""
    fanout_seeds = _requester_paths(ctx, eng, rep)
    if fanout_seeds:
        before = len(ctx.installed)
        _dep_fanout(ctx, eng, fanout_seeds, set(ctx.installed), depth=2)
        fanout_note = f" (+{len(ctx.installed) - before} requester deps)"
    else:
        fanout_note = ""
    font_exts = tuple(params.get("font_related_exts") or ())
    candidates = []
    if params.get("try_exts"):
        candidates = [params["file"] + e for e in params["try_exts"]]
    else:
        candidates = [params["file"]]
        if not Path(candidates[0]).suffix:
            # `I can't find file `X'` 裸 payload (\input/openin 系报错) ——
            # TeX 语义实际找 X.tex; 裸名照试后补 .tex 变体 (epsf 实证:
            # filemap/shim_map 键全带扩展名, 裸名恒 miss)。
            candidates.append(params["file"] + ".tex")
    missed: list[str] = []
    for fname in candidates:
        font_related = bool(params.get("font_related")) or fname.endswith(font_exts)
        # probe 带 cwd=wdir: 工程内文件/ctan_fetch 平铺落盘均算命中
        # (tectonic probe_file 无 cwd 恒 None, 复核必败)
        if present := _probe(eng, fname, cwd=ctx.wdir):
            _install_dep_closure(ctx, eng, fname, present)
            if params.get("already_present_ok", True):
                return True, f"already-present {fname}{fanout_note}"
            continue
        if not eng.install_file(fname, font_related=font_related):
            pkgs = _filemap_candidates(eng, fname)
            hint = f" (candidates: {', '.join(pkgs)})" if pkgs else ""
            missed.append(f"no package provides {fname}{hint}")
            continue
        if not (installed := _probe(eng, fname, cwd=ctx.wdir)):
            ctx.advisories.append(f"installed but {fname} still not found")
            continue
        ctx.installed.append(fname)
        _install_dep_closure(ctx, eng, fname, installed)
        if font_related:
            eng.rebuild_fontmaps()
        return True, f"installed {fname}{fanout_note}"
    # 全候选失败才落 advisory——前候选 miss 后候选成 (裸名→.tex fallback)
    # 的常态路径不该污染归因统计 (scout-pst 实证噪音)
    ctx.advisories.extend(missed)
    return False, f"no candidate file installed for {params['file']}{fanout_note}"


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
        return _apply_install_file(ctx, eng, params, rep)
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
        if n > 0:  # 0 命中不落 engine_flags——空转规则不该给后续编译注 flag
            for fl in params.get("engine_flags") or []:
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


def _match_apply(  # noqa: C901, PLR0912, PLR0913, PLR0917  # spike pick_and_apply 签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> tuple[Rule | None, str]:
    """Order 序找第一条 when+condition 过、mode 可行且应用成功的规则。

    ``unsupported`` + ``fallback: escalate_llm`` 不就地烧 LLM——记下首个
    待 escalate 规则继续扫描, 同 category 的廉价规则全耗尽后才调 hook
    (missing_pfb_updmap 原位评估会把后置的 font_sub_shim 饿死在 LLM 后面)。
    """
    pending_esc: tuple[Rule, str] | None = None
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
            if spec.get("fallback") == "escalate_llm" and pending_esc is None:
                pending_esc = (rule, key)
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
    if pending_esc is not None and ctx.llm_hook is not None:
        rule, key = pending_esc
        applied, note = ctx.llm_hook(ctx, rep)
        if applied:
            ctx.applied.add(key)
            return rule, f"escalated: {note}"
        if note:
            ctx.events.append(f"rule {rule.id}: escalate skip ({note})")
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
    for f in sorted(f for f in proj.rglob("*") if f.suffix.lower() == ".tex"):
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
        key = f"{rule.id}:{pay}"
        if key in ctx.applied:  # 非 REJECT 型 gate 已应用过 → 不重发不重记账
            continue
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
            ctx.applied.add(key)
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
    # texmfhome 缺省时 ``tlmgr --usermode install`` 落 kpathsea 默认 ~/texmf
    # ——全局可见树，跨跑污染 base 对照线（modec-rerun 实证：youngtab.sty 进
    # ~/texmf 后 1306.1931 base 臂 fail→clean 假象）。装包隔离到任务树内。
    if getattr(eng, "texmfhome", "unset") is None:
        eng.texmfhome = wdir / "_texmf"  # type: ignore[attr-defined]
        ctx.events.append("wire texmfhome -> workdir _texmf")
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
    compile_timeout: float | None = None,
) -> dict[str, Any]:
    """跑一格修复循环 → cell dict (字段与 spike fixloop-results.json 兼容)。

    verdict ∈ clean / acceptable_pdf / dirty_pdf / best_effort_pdf /
    unfixable:<cat> / stuck / max_rounds / reject:<rid> /
    no_errors_no_pdf / no_main_tex[:<sub>]（``classify_no_main`` 细分）
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
    # 重编超时: 参数 > meta.loop.timeout_sec > 引擎缺省 (None = 不透传)
    if compile_timeout is not None:
        timeout = float(compile_timeout)
    elif cfg.get("timeout_sec") is not None:
        timeout = float(cfg["timeout_sec"])
    else:
        timeout = None
    compile_kw: dict[str, Any] = {}
    if timeout is not None:
        compile_kw["timeout"] = timeout

    cell: dict[str, Any] = {
        "project": corpus_id or wdir.name,
        "cond": cond,
        "main": None,
        "engine": engine_name,
        "rounds": [],
        "actions": [],
        "verdict": None,
        "floor_restored": False,
    }
    ctx = LoopCtx(wdir=wdir, engine_name=engine_name, runner=runner, llm_hook=llm_hook)

    main = find_main_tex(wdir)
    if main is None:
        sub = _classify_no_main(wdir)
        cell["verdict"] = f"no_main_tex:{sub}" if sub else "no_main_tex"
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell
    ctx.main_rel = str(main.relative_to(wdir))
    cell["main"] = ctx.main_rel
    cell["actions"] = ctx.actions  # 同一 list: precheck/gate/loop 动作汇入一处
    _wire_engine(eng, rs, wdir, ctx)

    # —— 不退化底板: 快照入口态 PDF ——
    # 先于 precheck/loop 一切编辑: 规则若把能出 pdf 的树打死, finalize 拷回
    # 入口产物兜底 (loop1 实证 partial→fail 真退化 4 格)。reject:* 不救。
    main_pdf = wdir / Path(ctx.main_rel).with_suffix(".pdf")
    floor_snap: Path | None = None
    if main_pdf.is_file() and main_pdf.stat().st_size > 0:
        snap = wdir / ".fixloop-entry.pdf"
        try:
            shutil.copy2(main_pdf, snap)
            floor_snap = snap
        except OSError as e:  # 快照失败仅失底板, 不阻塞修复
            ctx.advisories.append(f"floor snapshot: {e}")

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
            wdir,
            ctx.main_rel,
            passes=passes,
            flags=list(ctx.engine_flags),
            **compile_kw,
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
        if floor_snap is None and pdf:  # 入口无现存产物 → 快照首轮 pdf
            src = getattr(res, "pdf", None)
            if isinstance(src, Path):
                snap = wdir / ".fixloop-entry.pdf"
                try:
                    shutil.copy2(src, snap)
                    floor_snap = snap
                except OSError as e:
                    ctx.advisories.append(f"floor snapshot: {e}")
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
            **compile_kw,
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
    # —— 底板兜回: 入口有 pdf 而末态无 → 拷回快照, verdict 置 None 让下方
    # 既有公式自然落成 dirty_pdf/clean; floor_from 记兜底前 verdict 供
    # triage/cases 观测 (不新增 verdict 词, 保持 docs/08 §6 词表封闭)。
    v_end = str(cell["verdict"] or "")
    if (
        not cell["final_pdf"]
        and floor_snap is not None
        and not v_end.startswith("reject:")
    ):
        main_pdf.unlink(missing_ok=True)  # 末态同名碎片先清再拷, 防半截混语义
        shutil.copy2(floor_snap, main_pdf)
        cell["floor_from"] = v_end
        cell["floor_restored"] = True
        cell["final_pdf"] = True
        cell["verdict"] = None
        ctx.events.append(f"floor: entry pdf restored (was {v_end or 'none'})")
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
