"""engine._engine_ctx — LoopCtx 每格运行上下文 (C5 拆叶)。

io/deps/round/ledger 四个子 dataclass + ``_CTX_FIELD_GROUP`` 平铺名→分组
转落表 + ``LoopCtx`` facade 本体。旧平铺字段名经
``__getattr__``/``__setattr__`` 全量转落分组存储——builtins/actions/
llm_hook 与各测试的 ``ctx.<field>`` 读写面零迁移。
"""

from __future__ import annotations

import contextlib
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from texlate.compile.fixloop._engine_proto import LlmHook, RunFn
    from texlate.compile.logparse import ErrReport

__all__ = [
    "_CTX_FIELD_GROUP",
    "LoopCtx",
    "_CtxDeps",
    "_CtxIO",
    "_CtxLedger",
    "_CtxRound",
]


@dataclass
class _CtxIO:
    """工程 io 面：工作目录 + 主文件相对路径 + 进程内文本缓存。"""

    wdir: Path
    main_rel: str | None = None
    _texts: dict[Path, str | None] = field(default_factory=dict, repr=False)
    #: 本派发窗内 ``ctx.write`` 经手写件集 —— 窗开始处清零 (集差分认不出
    #: 对既有件的重写，run 级积累会把规则自改误判成外部落件); 落件同步
    #: 区分规则自改 (经缓存的 accounted 写) 与外部落件 (install/run_tool
    #: 裸写，绕过 ``_texts``) 用。
    written: set[Path] = field(default_factory=set, repr=False)
    #: cond 树敏感面快照 (actions._cond_snap 三槽惰性填) —— 每派发窗
    #: ``_apply`` 尝试即整槽作废 (``_cond_snap_reset``)。
    _cond_snap: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class _CtxDeps:
    """注入依赖：引擎名 + 外部工具 runner (测试注入点) + LLM 修复钩子。"""

    engine_name: str
    runner: RunFn | None = None
    llm_hook: LlmHook | None = None


@dataclass
class _CtxRound:
    """本轮分类/裁决态 —— 主循环每轮重写，轮间不累计。"""

    #: 本轮 taxonomy 分类结果 —— llm_hook 的 prompt 装配读这两个字段
    #: (LlmHook 签名固定 (ctx, rep), cat/pay 经 ctx 传递)。
    err_cat: str | None = None
    err_pay: str | None = None
    err_head: str = ""  # 本轮错误 blob (ctx_suggests 条件用)
    #: 本轮编译 log 的 missing-char 码位集 (``_mc_parse_log`` 同口径，
    #: nullfont 已滤)——error-cat 轮照记 (缺字警告与 ``!`` 错可同现，
    #: ``warn_missing_char`` 类别排他使族臂平时够不到这些轮)。
    mc_cps: frozenset[int] = frozenset()

    def point(self, cat: str | None, pay: str | None, rep: ErrReport) -> None:
        """重指当前派发目标 (主错/孪生): err_cat/err_pay/err_head 同写。

        三字段的派发语义一体 (when 匹配读 cat/pay, ctx_suggests/llm_hook
        读 head)——主循环与次级派发共用同一写点，免分点写字段漂移
        (写 head 忘写 pay 类)。err_head 恒为 ``rep.first + rep.ctx``
        单行推导——公式单源在此，调用点不再各开一行拼接。
        """
        self.err_cat, self.err_pay = cat, pay
        self.err_head = (rep.first or "") + "\n" + (rep.ctx or "")

    @contextlib.contextmanager
    def pointed(
        self,
        cat: str | None,
        pay: str | None,
        rep: ErrReport,
        mc_cps: frozenset[int] | None = None,
    ) -> Iterator[None]:
        """``point`` 的作用域版：进入重指 (可选 ``mc_cps`` 覆盖), 退出四字段全复元。

        warn-preempt 类临时派发用——``err_head`` 一并入保存/复元集 (分点
        手 roller 只存 cat/pay 会留 stale head, 后续族臂的 ctx_suggests
        读到的还是重指前 rep 的 head, 与 ``point`` 的三字段一体契约相悖)。
        """
        keep = (self.err_cat, self.err_pay, self.err_head, self.mc_cps)
        self.point(cat, pay, rep)
        if mc_cps is not None:
            self.mc_cps = mc_cps
        try:
            yield
        finally:
            self.err_cat, self.err_pay, self.err_head, self.mc_cps = keep


@dataclass
class _CtxLedger:
    """跨轮累计账簿：规则应用/动作/装包/事件/引擎 flag/拒修与建议记录。"""

    applied: set[str] = field(default_factory=set)  # "{rule_id}:{payload}"
    #: 缺字族臂已消费码位账：``{rule_id: {cp, ...}}``——臂**起火轮**看见
    #: 的全集记其名下 (declined 不记——未消费的码位后浪重评估仍合法);
    #: dedup 豁免按 ``mc_cps - mc_seen[rid]`` 增量判 (missdisp #189:
    #: fired_late_surface——``\bibitem`` 细空格/.bbl 字形/cs_rebind
    #: 重音后浪浮新码位，"fired" 不得把起火后才浮出的码位记消费)。
    mc_seen: dict[str, set[int]] = field(default_factory=dict)
    #: "看见但拒修" 记录面：when 命中后 cond-skip/applied=False 的 ``{id}: {why}``
    #: ——events 有但 cases.jsonl 不落，这里单收一份供 records 物化。
    declined: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    engine_flags: list[str] = field(default_factory=list)
    #: 经 ``compile(flags=…)`` seam 被引擎拒放的 flag（支持子集外）——
    #: 每 flag 记一次 advisory，cell 落 ``engine_flags_dropped``。
    flags_dropped: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    #: 解析趟请求旗 (qc-impl fp resolve-pass): 规则 yaml
    #: ``action.params.needs_pass: true`` 或 builtin 直写 (bbl 再生/citekey
    #: 改写类动了 aux/cite 记录面的修复) → 下一轮 ``_round_compile`` 走
    #: ``passes=None`` 引擎自适应趟让 ``\newlabel``/``\bibcite`` 同轮解齐;
    #: 轮头消费即清 (一次性闸，非持续态)。
    needs_pass: bool = False


#: 平铺字段名 → 所属分组：LoopCtx facade 经此表把 ``ctx.<field>`` 读写
#: 转落 ``ctx.<group>.<field>`` —— 兼容面整体保留，新代码直用分组路径。
_CTX_FIELD_GROUP = {
    "wdir": "io",
    "main_rel": "io",
    "_texts": "io",
    "engine_name": "deps",
    "runner": "deps",
    "llm_hook": "deps",
    "err_cat": "round",
    "err_pay": "round",
    "err_head": "round",
    "mc_cps": "round",
    "applied": "ledger",
    "declined": "ledger",
    "mc_seen": "ledger",
    "actions": "ledger",
    "installed": "ledger",
    "events": "ledger",
    "engine_flags": "ledger",
    "flags_dropped": "ledger",
    "advisories": "ledger",
    "needs_pass": "ledger",
}


@dataclass(init=False)
class LoopCtx:
    """单格 fixloop 的运行上下文：io/deps/round/ledger 四组状态。

    构造签名逐参复刻旧平铺 dataclass 生成面; 旧字段名全量保留为
    facade —— 读 ``ctx.<field>`` = ``ctx.<group>.<field>``, 写同理转落
    (field→group 归属见 ``_CTX_FIELD_GROUP``)。
    """

    io: _CtxIO
    deps: _CtxDeps
    round: _CtxRound
    ledger: _CtxLedger

    def __init__(  # noqa: PLR0913, PLR0917  # 签名逐参复刻旧 dataclass 生成面
        self,
        wdir: Path,
        engine_name: str,
        main_rel: str | None = None,
        applied: set[str] | None = None,
        declined: list[str] | None = None,
        actions: list[dict[str, Any]] | None = None,
        installed: list[str] | None = None,
        events: list[str] | None = None,
        engine_flags: list[str] | None = None,
        flags_dropped: list[str] | None = None,
        advisories: list[str] | None = None,
        runner: RunFn | None = None,
        llm_hook: LlmHook | None = None,
        err_cat: str | None = None,
        err_pay: str | None = None,
        err_head: str = "",
        mc_cps: frozenset[int] = frozenset(),
        mc_seen: dict[str, set[int]] | None = None,
        _texts: dict[Path, str | None] | None = None,
    ) -> None:
        """平铺 kwargs → 四组子对象; ``None`` = 该组字段取默认值。"""
        self.io = _CtxIO(
            wdir=wdir,
            main_rel=main_rel,
            _texts=_texts if _texts is not None else {},
        )
        self.deps = _CtxDeps(engine_name=engine_name, runner=runner, llm_hook=llm_hook)
        self.round = _CtxRound(
            err_cat=err_cat,
            err_pay=err_pay,
            err_head=err_head,
            mc_cps=mc_cps,
        )
        self.ledger = _CtxLedger(
            applied=applied if applied is not None else set(),
            declined=declined if declined is not None else [],
            mc_seen=mc_seen if mc_seen is not None else {},
            actions=actions if actions is not None else [],
            installed=installed if installed is not None else [],
            events=events if events is not None else [],
            engine_flags=engine_flags if engine_flags is not None else [],
            flags_dropped=flags_dropped if flags_dropped is not None else [],
            advisories=advisories if advisories is not None else [],
        )

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 平铺转发面天然 Any
        """平铺字段名 → 分组存储转读 (facade; 只兜真实属性查找失败的名)。"""
        group = _CTX_FIELD_GROUP.get(name)
        if group is None:
            raise AttributeError(name)
        return getattr(getattr(self, group), name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        """平铺字段名赋值 → 分组存储转写 (facade; 组名自身直挂实例)。"""
        group = _CTX_FIELD_GROUP.get(name)
        if group is None:
            object.__setattr__(self, name, value)
        else:
            setattr(getattr(self, group), name, value)

    def tex_files(self, exts: Iterable[str] = (".tex", ".sty", ".cls")) -> list[Path]:
        """工程内指定扩展名文件 (排序稳定)。"""
        exts_t = tuple(e.lower() for e in exts)
        return [
            p
            for p in sorted(self.io.wdir.rglob("*"))
            if p.suffix.lower() in exts_t and p.is_file()
        ]

    def read(self, f: Path) -> str | None:
        """utf-8 读文件 (进程内缓存，errors=replace); 不可读 → None。"""
        texts = self.io._texts  # noqa: SLF001  # 组内缓存直读 (facade ``_texts`` 转读亦达，省逐次 __getattr__ 一跳)
        if f not in texts:
            try:
                texts[f] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[f] = None
        return texts[f]

    def write(self, f: Path, text: str) -> None:
        """utf-8 写文件并同步缓存。"""
        f.write_text(text, encoding="utf-8")
        self.io._texts[f] = text  # noqa: SLF001  # 组内缓存同步
        self.io.written.add(f)

    def invalidate(self, f: Path) -> None:
        """外部改写过 (如字节级转码) 后失效缓存。"""
        self.io._texts.pop(f, None)  # noqa: SLF001

    def invalidate_suffixes(self, exts: Iterable[str]) -> int:
        """按扩展名集批量失效缓存条目 (compile/sweep 改盘件), 返回失效数。"""
        exts_t = {e.lower() for e in exts}
        keys = [p for p in self.io._texts if p.suffix.lower() in exts_t]  # noqa: SLF001
        for f in keys:
            self.io._texts.pop(f, None)  # noqa: SLF001
        return len(keys)

    def main_path(self) -> Path | None:
        """主文件绝对路径 (main_rel 未定 → None)。"""
        return self.io.wdir / self.io.main_rel if self.io.main_rel else None

    def main_head(self, n: int = 3000) -> str:
        r"""主文件前 n 字符 (原型用 3000 判 \documentstyle)。"""
        main = self.main_path()
        if main is None:
            return ""
        return (self.read(main) or "")[:n]

    def source_blob(self) -> str:
        """全部 tex 源拼接 (source_contains 条件用)。"""
        return "\n".join(t for f in self.tex_files() if (t := self.read(f)))

    def run_tool(
        self, argv: list[str], timeout: int = 120
    ) -> tuple[int | None, str, bool | str]:
        """跑外部工具; 默认 subprocess (测试注入 runner)。"""
        if self.deps.runner:
            _rc, out, _sec, to = self.deps.runner(argv, timeout, self.io.wdir)
            return _rc, out, to
        try:
            p = subprocess.run(  # noqa: S603  # argv 列表无 shell; fixloop 动作原语
                argv,
                cwd=str(self.io.wdir),
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
