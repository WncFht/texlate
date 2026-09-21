r"""llm_hook — ``escalate_llm`` 动作的统一出口 (LLM 修编译错误的补丁契约层)。

rules/ ``action.kind: escalate_llm`` / ``engines.*.fallback: escalate_llm``
命中时 engine 调 ``ctx.llm_hook(ctx, rep)`` (engine.py LlmHook 协议既有通路,
spike L523-527 恒 False stub 的实装位)。本模块只含机制本体::

    hook = make_llm_hook()                       # 网关默认路 (env 解析)
    hook = make_llm_hook(translator=translator)  # 注入缝: MockTranslator 等
    cell = fixloop(proj, eng, llm_hook=hook)     # 显式传入才启用

契约 (硬): 模型回 ``{"patches": [{"file","old","new"}]}``; ``old`` 必须在
目标文件**精确匹配一次**否则弃用该 patch; 全部 patch 被弃 → ``(False, …)``
= 未修复, 主循环继续, 不报错。只许改 wdir 内 ``.tex/.sty/.cls``; banned
构造 (``\\write18``/shell 逃逸/``\\input|`` 管道/绝对路径+``..`` 穿越)
整条拒。落盘走 ``ctx.write`` —— 与 builtin transform 同一路径。

网关面: 默认 env ``TEXLATE_BASE_URL``/``TEXLATE_API_KEY``/``TEXLATE_MODEL``
(key 另按已决议端点 provider 专名 env 兜底 —— ``xlat.client.env_key_for_url``
单源, ``env_credentials``/server ``env_key_for`` 同口径); 单次调用
``timeout_s`` 60s, 模块级信号量把同时在飞的网关请求压在 4
(swe-2-medium 并发硬闸)。

注: 本轮 taxonomy ``cat``/``pay`` 若由 engine 落到 ``ctx.err_cat``/
``ctx.err_pay`` (冻结期未挂) 会进 prompt 与 note; 未挂时 getattr 兜底
为 ``?``/``(none)`` —— log 摘要 + file_stack + 出错片段已够修复语义。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from texlate.textutil import JSON_FENCE_RX, env_raw, safe_resolve
from texlate.textutil.osutil import ENV_BASE_URL, ENV_DIALECT, ENV_MODEL
from texlate.xlat.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ChatClient,
    ChatOptions,
    env_key_for_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from texlate.compile.fixloop.engine import LlmHook, LoopCtx
    from texlate.compile.logparse import ErrReport
    from texlate.xlat.pipeline import Translator

__all__ = ["LlmFixer", "Patch", "make_llm_hook"]

#: 网关默认端点/模型单源 = ``xlat.client`` (a91a474; env 覆盖优先)
DEFAULT_TIMEOUT_S = 60.0  # 单次调用预算 (任务约定)
#: reasoning 模型 (swe-2-*) 思考链也吃 max_tokens —— 8192 与 xlat 翻译同档
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_PATCHES = 8

#: 送给模型的 log 摘要 / 出错文件片段各自的字符上限 (~4KB, 任务约定)
_LOG_BUDGET = 4096
_FRAG_BUDGET = 4096
_FRAG_CTX_LINES = 25  # l.N 前后各取行数; 无行号时取文件头 80 行
_FRAG_HEAD_LINES = 80
_HISTORY_MAX = 12  # 已尝试动作历史条数上限

#: _drive 放弃等待后给协程的收尾宽限 (httpx 超时已在协程内兜底, 这是双保险)
_ABANDON_GRACE_S = 10.0

#: swe-2-medium 网关并发硬闸 4 —— 跨线程共享; hook 内部请求天然串行 (单次调用)
_GATEWAY_SEM = threading.BoundedSemaphore(4)

_PATCHABLE_EXTS = frozenset({".tex", ".sty", ".cls"})

#: 文件装载族宏 —— patch ``new`` 里出现绝对路径/``..`` 穿越形态即拒
_PATH_MACRO = (
    r"\\(?:input|include|InputIfFileExists|IfFileExists|import|subimport|"
    r"lstinputlisting|verbatiminput|openin|openout|read|writefile)\b"
)

#: ``new`` 文本的 banned 构造表 (任务约定三类: write18 / shell 逃逸 / 路径穿越)
_BANNED_NEW: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\\write\s*18\b"), "shell-escape \\write18"),
    (re.compile(r"\\pdfsystem\b"), "\\pdfsystem shell escape"),
    (re.compile(r"\\directlua\b"), "\\directlua (os.execute 面)"),
    (re.compile(r"\\input\s*\{?\s*[\"']?\s*\|"), "\\input| pipe escape"),
]

#: 文件装载宏的调用面 —— ``arg``/``arg2`` 实参捕获供 ``_path_arg_escape``
#: 逐组件判。可选流号/目标 cs 站位 (``\openout\w=``/``\read\w to\x``) 先吃
#: 掉, 否则流号 cs 的 ``\`` 落进路径判定 —— 旧拼 ``[/\\]`` 尾哨兵把
#: ``\openout\w=x`` 误当绝对路径拒。``arg2`` 收 ``\import{dir}{file}`` 双参形。
_PATH_ARG_RX = re.compile(
    _PATH_MACRO
    + r"(?:[^\S\n]*\\[a-zA-Z@*]+[^\S\n]*"
    r"(?:=|to[^\S\n]*\\[a-zA-Z@*]+))?"
    r"[^\S\n]*(?:\[[^\]\n]*\][^\S\n]*)?[\{=]?[^\S\n]*[\"']?"
    r"(?P<arg>\{[^{}\n]*\}|[^\s{}\"'=\\]+)"
    r"(?:[^\S\n]*(?P<arg2>\{[^{}\n]*\}))?"
)


def _path_arg_escape(arg: str) -> bool:
    r"""装载宏实参是否绝对/``.``/``..`` 穿越形 —— 逐组件判, 非首字符扫。

    旧 ``.{1,2}[/\\]`` 前哨形只盖行首, ``{sub/../x}`` 中位 ``..`` 直通;
    ``\`` 先归一成 ``/`` 再切组件 (TeX 侧 ``\``/``/`` 分隔双吃)。
    """
    s = arg.strip().strip("\"'").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    if not s:
        return False
    s = s.replace("\\", "/")
    if s.startswith("/") or re.match(r"[A-Za-z]:/", s):
        return True
    parts = s.split("/")
    return "." in parts or ".." in parts

_SYSTEM = """\
You are a LaTeX compile-error repair engine inside an automated fix loop. \
Rule-based fixes are exhausted; analyze the error and propose minimal source \
patches.

Reply with STRICT JSON only (no prose, no markdown fences):
{"patches": [{"file": "<path relative to project root>", \
"old": "<exact current bytes>", "new": "<replacement>"}]}

Hard contract:
- "old" must appear EXACTLY ONCE, verbatim, in that file (whitespace/newlines \
count). Ambiguous or absent "old" gets the patch discarded.
- Only files under the project root with extension .tex/.sty/.cls are writable.
- Never emit shell-escape constructs (\\write18, \\pdfsystem, \\directlua, \
\\input|"cmd") or absolute/parent-traversal paths in file-loading macros.
- Prefer the smallest correct diff: define a missing control sequence, fix a \
typo, add a \\usepackage. Do not rewrite whole files.
- If no safe patch exists, return {"patches": []}."""


@dataclass(frozen=True, slots=True)
class Patch:
    """一条通过形状校验的补丁 (尚未过文件侧检查)。"""

    file: str  # wdir 相对路径 (LLM 原样, 应用前再过路径闸)
    old: str
    new: str


def _drive(coro_fn: Callable[[], Coroutine[Any, Any, str]], wait_s: float) -> str:
    """专用线程驱动协程。

    调用方线程可能已持运行中 loop (server worker ``asyncio.to_thread`` 里
    能跑 ``asyncio.run``, 但裸 async 调用方不能), 故统一放新线程。

    协程对象在线程内工厂构造: ``ChatClient``/``AsyncClient`` 绑到新建 loop,
    避免跨 loop 复用 httpx 池的 "attached to a different loop"。
    """
    box: dict[str, Any] = {}

    def _go() -> None:
        try:
            box["v"] = asyncio.run(coro_fn())
        except BaseException as e:  # noqa: BLE001  # 任意失败搬回调用方分类
            box["e"] = e

    t = threading.Thread(target=_go, name="fixloop-llm", daemon=True)
    t.start()
    t.join(wait_s)
    if t.is_alive():
        msg = f"llm call exceeded {wait_s:.0f}s (abandoned)"
        raise TimeoutError(msg)
    if "e" in box:
        raise box["e"]
    return str(box.get("v") or "")


def _log_excerpt(rep: ErrReport) -> str:
    """首错 + ctx + tail 拼 ~4KB 摘要 (tail 偏置: 错误细节常在尾部)。"""
    blob = "\n".join(x for x in (rep.first, rep.ctx, "[log tail]", rep.tail) if x)
    if len(blob) > _LOG_BUDGET:
        blob = "…" + blob[-_LOG_BUDGET:]
    return blob


def _err_tok_path(ctx: LoopCtx, tok: str) -> Path | None:
    """file_stack/popped_files 单 token → 可落盘路径 (工程内优先, 系统侧作上下文)。"""
    cand = Path(tok)
    if not cand.is_absolute():
        w = ctx.wdir / tok
        if w.is_file():
            return w
        for f in ctx.tex_files():
            if f.name == tok.rsplit("/", 1)[-1]:
                return f
        return None
    return cand if cand.is_file() else None


def _resolve_err_file(ctx: LoopCtx, rep: ErrReport) -> Path | None:
    """file_stack 顶→底找工程内出错文件; 再不中退主文件。

    栈全不命中并入 ``reversed(popped_files)`` 递补——
    ``File ended while scanning`` 类 runaway 错报位在最近关闭帧
    (``popped_files[-1]`` = 肇事候选, #78)。帧序单源
    ``ErrReport.site_frames``。
    """
    for tok in rep.site_frames():
        t = tok.strip()
        if t and (hit := _err_tok_path(ctx, t)) is not None:
            return hit
    return ctx.main_path()


def _fragment(ctx: LoopCtx, f: Path | None, line_no: int | None) -> str:
    """出错文件片段: ``l.N`` ±25 行带行号; 无行号取头 80 行。不可读 → 占位。"""
    if f is None:
        return "(no file identified)"
    text = ctx.read(f)
    if text is None:
        return f"({f.name} unreadable)"
    lines = text.splitlines()
    if line_no is not None:
        lo = max(0, line_no - _FRAG_CTX_LINES - 1)
        hi = min(len(lines), line_no + _FRAG_CTX_LINES)
    else:
        lo, hi = 0, min(len(lines), _FRAG_HEAD_LINES)
    blob = "\n".join(f"{i + 1:>5}  {lines[i]}" for i in range(lo, hi))
    return blob[:_FRAG_BUDGET]


def _history(ctx: LoopCtx) -> str:
    """已尝试动作历史 (round/rule/detail 截断) —— 让模型避开已失败路径。"""
    lines = [
        f"r{a.get('round')} {a.get('rule')}: {str(a.get('detail', ''))[:160]}"
        for a in ctx.actions[-_HISTORY_MAX:]
    ]
    return "\n".join(lines) or "(none)"


def _rel_label(ctx: LoopCtx, f: Path | None) -> str:
    """工程内文件给相对路径, 工程外给绝对串。"""
    if f is None:
        return "?"
    try:
        return str(f.resolve().relative_to(ctx.wdir.resolve()))
    except ValueError:
        return str(f)


def _strip_fence(raw: str) -> str:
    """整段 ``` 围栏剥一层; 非围栏原文返回。"""
    m = JSON_FENCE_RX.match(raw)
    return m.group("body") if m else raw


def _extract_json(raw: str) -> dict[str, Any] | None:
    """严格 JSON 抽取: 剥皮 → loads → 首个 ``{`` 到末个 ``}`` 兜底。"""
    text = _strip_fence(raw.strip())
    try:
        # RecursionError: 模型输出可构造超深嵌套 ([~50000 撞解释器上限)
        # —— 与坏 JSON 同处理 (xlat/client.py 同范式)。
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            data = json.loads(text[i : j + 1])
        except (json.JSONDecodeError, RecursionError):
            return None
    return data if isinstance(data, dict) else None


def _one_patch(it: Any) -> Patch | str:  # noqa: ANN401  # json 元素天然 Any
    """单条 patch 形状校验 → Patch; 不合格 → 弃用理由。"""
    if not isinstance(it, dict):
        return f"{it!r:.60}: not an object"
    f, o, n = it.get("file"), it.get("old"), it.get("new")
    if not isinstance(f, str) or not f.strip():
        return "patch: missing/empty file"
    if not isinstance(o, str) or o == "":
        return f"{f}: empty old"
    if not isinstance(n, str):
        return f"{f}: non-string new"
    if o == n:
        return f"{f}: no-op patch"
    return Patch(file=f.strip(), old=o, new=n)


def _parse_patches(raw: str, max_patches: int) -> tuple[list[Patch], list[str]]:
    """模型输出 → (形状合格的 Patch 列表, 弃用理由列表)。"""
    data = _extract_json(raw)
    if data is None:
        return [], ["unparseable JSON"]
    items = data.get("patches", data.get("patch"))
    if items is None and {"file", "old", "new"} <= set(data):
        items = [data]  # 裸单 patch 对象宽容收下
    if not isinstance(items, list):
        return [], ["no patches list"]
    patches: list[Patch] = []
    rejects: list[str] = []
    for it in items[:max_patches]:
        one = _one_patch(it)
        (patches.append if isinstance(one, Patch) else rejects.append)(one)
    if len(items) > max_patches:
        rejects.append(f"dropped {len(items) - max_patches} patch(es) over cap")
    return patches, rejects


def _banned(new: str) -> str | None:
    """命中 banned 构造 → 理由; 干净 → None。"""
    for rx, why in _BANNED_NEW:
        if rx.search(new):
            return why
    for m in _PATH_ARG_RX.finditer(new):
        if any(
            _path_arg_escape(m.group(g))
            for g in ("arg", "arg2")
            if m.group(g) is not None
        ):
            return "absolute/.. path in file-loading macro"
    return None


def _apply_patches(ctx: LoopCtx, patches: list[Patch]) -> tuple[list[str], list[str]]:
    """逐 patch 过路径闸 + 精确一次匹配 → ``ctx.write`` 落盘。"""
    applied: list[str] = []
    rejects: list[str] = []
    wdir_r = ctx.wdir.resolve()
    for p in patches:
        rel = str(Path(p.file))  # 归一 ./ 前缀; .. 段在下一步被拦
        target = ctx.wdir / rel
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            rejects.append(f"{p.file}: path escapes workdir")
            continue
        if target.suffix.lower() not in _PATCHABLE_EXTS:
            rejects.append(f"{p.file}: not a .tex/.sty/.cls")
            continue
        resolved = safe_resolve(target)
        if resolved is None or not resolved.is_relative_to(wdir_r):
            rejects.append(f"{p.file}: path escapes workdir")
            continue
        if (why := _banned(p.new)) is not None:
            rejects.append(f"{p.file}: banned construct ({why})")
            continue
        text = ctx.read(target)
        if text is None:
            rejects.append(f"{p.file}: unreadable/missing")
            continue
        n_hits = text.count(p.old)
        if n_hits != 1:
            rejects.append(f"{p.file}: old matched {n_hits}x (need exactly 1)")
            continue
        ctx.write(target, text.replace(p.old, p.new, 1))
        applied.append(rel)
    return applied, rejects


class LlmFixer:
    """``escalate_llm`` 的 LlmHook 实现: 上下文装配 → Translator → 补丁契约。

    ``translator`` 满足 :class:`~texlate.xlat.pipeline.Translator` 协议
    (MockTranslator 即测件); None 走默认网关路 —— 每次调用在驱动线程的
    loop 里新建 ``ChatClient`` (env ``TEXLATE_BASE_URL``/``TEXLATE_MODEL``
    /``TEXLATE_DIALECT`` 裸读 + key 走 ``env_key_for_url`` provider 兜底),
    不跨 loop 复用 httpx 池。
    """

    def __init__(  # noqa: PLR0913  # endpoint/key/model/timeout/预算全是独立旋钮
        self,
        *,
        translator: Translator | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dialect: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_patches: int = DEFAULT_MAX_PATCHES,
    ) -> None:
        """组装配置; ``translator=None`` 时 env 解析网关三件套。"""
        self.translator = translator
        self.base_url = base_url or env_raw(ENV_BASE_URL) or DEFAULT_BASE_URL
        self.api_key = api_key if api_key is not None else env_key_for_url(self.base_url)
        self.model = model or env_raw(ENV_MODEL) or DEFAULT_MODEL
        self.dialect = dialect or env_raw(ENV_DIALECT) or "auto"
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_patches = max_patches

    async def _ask(self, system: str, user: str) -> str:
        """一次 chat 往返 → content 原文 (Translator 或自建 ChatClient 两路)。"""
        if self.translator is not None:
            return await self.translator.translate(
                system=system,
                user=user,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
        timeout = httpx.Timeout(self.timeout_s, connect=10.0)
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        async with ChatClient(
            self.base_url, self.api_key, timeout=timeout, dialect=self.dialect
        ) as c:
            r = await c.chat(
                self.model,
                msgs,
                options=ChatOptions(
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                ),
            )
            return r.content

    def _prompt(self, ctx: LoopCtx, rep: ErrReport) -> tuple[str, str]:
        """装配 (system, user): 类别/payload + log 摘要 + 出错片段 + 历史。"""
        cat = getattr(ctx, "err_cat", None) or "?"  # 字段挂载前优雅降级
        pay = getattr(ctx, "err_pay", None) or "(none)"
        err_file = _resolve_err_file(ctx, rep)
        user = "\n\n".join(
            [
                f"ERROR CATEGORY: {cat}\nPAYLOAD: {pay}",
                "FIRST ERROR + LOG EXCERPT:\n" + _log_excerpt(rep),
                "FILE STACK AT ERROR: "
                + (" -> ".join(rep.file_stack) if rep.file_stack else "(empty)"),
                f"ERRORING FILE FRAGMENT ({_rel_label(ctx, err_file)}):\n"
                + _fragment(ctx, err_file, rep.line_no),
                "TRIED FIXES THIS RUN:\n" + _history(ctx),
                "Respond with the JSON patch object only.",
            ]
        )
        return _SYSTEM, user

    def __call__(self, ctx: LoopCtx, rep: ErrReport) -> tuple[bool, str]:
        """LlmHook 入口: ``(applied, note)`` —— note 以 ``llm_hook`` 打头供追溯。"""
        # 全空 rep (precheck 的 dummy) 才不烧 token; warn_* 伪类别轮有 tail
        # 可喂 —— missing_char 类 escalate 不该被这道闸误杀。
        if not (rep.first or rep.ctx or rep.tail.strip()):
            return False, "llm_hook: no error context"
        system, user = self._prompt(ctx, rep)
        try:
            with _GATEWAY_SEM:
                raw = _drive(
                    lambda: self._ask(system, user),
                    self.timeout_s + _ABANDON_GRACE_S,
                )
        except Exception as e:  # noqa: BLE001  # 调用失败=未修复, 主循环继续
            return False, f"llm_hook: call failed {type(e).__name__}: {e}"
        patches, rejects = _parse_patches(raw, self.max_patches)
        if not patches:
            why = "; ".join(rejects) or "empty patches"
            return False, f"llm_hook: no usable patch ({why})"
        applied, apply_rejects = _apply_patches(ctx, patches)
        rejects += apply_rejects
        pay = getattr(ctx, "err_pay", None) or getattr(ctx, "err_cat", None) or "?"
        if applied:
            note = (
                f"llm_hook[{self.model}]({pay}): applied "
                f"{len(applied)}/{len(patches)} on {','.join(applied)}"
            )
            if rejects:
                note += f"; dropped: {'; '.join(rejects)}"
            return True, note
        return (
            False,
            f"llm_hook({pay}): 0/{len(patches)} applied: {'; '.join(rejects)}",
        )


def make_llm_hook(**kwargs: Any) -> LlmHook:  # noqa: ANN401  # 旋钮透传 LlmFixer
    """``LlmFixer`` 的工厂入口 —— ``fixloop(..., llm_hook=make_llm_hook(...))``。

    kwargs 全透传 :class:`LlmFixer` (translator/base_url/api_key/model/
    timeout_s/temperature/max_tokens/max_patches)。
    """
    return LlmFixer(**kwargs)
