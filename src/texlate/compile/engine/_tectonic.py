"""tectonic 引擎 —— 便携 bundle 自足通路（``engine.py`` 拆分叶）。

``run_process``/``tectonic_version``/``ensure_tectonic`` 走 ``_eng.``
运行期回查——测试 patch 缝钉在 ``texlate.compile.engine.X`` 模块名上。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Final

    from texlate.compile.loginfo import LogInfo
    from texlate.compile.proc import run_process
    from texlate.compile.toolchain import ensure_tectonic, tectonic_version

    class _EngNS:
        """``_eng`` 静态面——锚位真签名经 staticmethod 别名钉入。

        ``engine/__init__`` 经 seams ``__getattr__`` 惰性回指锚位模块，ty
        仅见 ``object``；借 TYPE_CHECKING 命名空间把 ``_eng.X`` 回查收窄到
        真签名。仅类型面视图——运行期 ``else`` 分支绑定原样，patch 缝
        （``monkeypatch.setattr(engine.X, …)`` → 叶侧 ``_eng.X`` 命中）零漂移。
        """

        ensure_tectonic = staticmethod(ensure_tectonic)
        run_process = staticmethod(run_process)
        tectonic_version = staticmethod(tectonic_version)

    _eng = _EngNS()
else:
    import texlate.compile.engine as _eng

from texlate.compile.loginfo import parse_log
from texlate.compile.sandbox import _apply_sandbox, _rc_to_signal, child_env
from texlate.texlog import normalize_stderr_errors
from texlate.textutil import env_opt, safe_is_file, safe_resolve
from texlate.textutil.osutil import ENV_TEX_BUNDLE

from ._base import DEFAULT_TIMEOUT, CompRes, _collect_compile_outputs
from ._xelatex import _harvest, _prepare_main

_TECTONIC_ATTEMPTS = 2  # 冷 bundle 首拉超时后重试（缓存热身）

#: 重试趟预算上限——首趟已烧满 timeout，重试时缓存已热、只需覆盖真实编译
#: 时长；再给满 timeout 会把单次调用真超时翻倍且救不了真超时的论文。
_TECTONIC_RETRY_TIMEOUT = 120.0

#: tectonic bundle pin（docs/spec/compile.md）——引擎默认 bundle；可用 env
#: TEXLATE_TEX_BUNDLE 或构造参数覆盖，置空串回落引擎自带默认 bundle。
TECTONIC_BUNDLE_PIN = "https://data1b.fullyjustified.net/tlextras-2022.0r0.tar"

#: engine_flags → tectonic argv 的受支持子集映射（原拼写 → argv token）。
#: ``-shell-escape`` 刻意不映射：``--untrusted`` 恒在 cmd 即禁 \write18，
#: 开 shell 与之矛盾且放大不可信源的 RCE 面 → 走 dropped，由 e2e 跨引擎
#: 换 xelatex 承载。
_TECTONIC_FLAG_MAP: Final = {
    "-synctex": ["--synctex"],
    "-synctex=1": ["--synctex"],
}

#: ``-Z`` 原生拼写直通是 ``-shell-escape`` 的后门（``-Z shell-escape``
#: 落位在 ``--untrusted`` 之后仍开 \write18；``-Z search-path=…`` 在 env
#: 降级下可读工程外路径）——只放已知无害子集，按 ``=`` 前值名匹配。
_TECTONIC_Z_OK: Final = frozenset(
    {
        "continue-on-errors",
        "minify-bundle",
        "keep-intermediates",
        "keep-logs",
        "deterministic-output",
        "synctex",
        "paper-size",
        "trace",
        "hide",
    }
)

#: ``-X compile`` 撤 ``--web-bundle`` 的分界版本：0.17.0 起 URL 并入
#: ``--bundle``（0.17.0 help 实测 ``--bundle <BUNDLE>  Use this URL or
#: path``；老版 ``--bundle`` 只认本地路径，URL 必须 ``--web-bundle``，
#: 否则 URL 被当文件打开 → os error 2）。
_TECTONIC_BUNDLE_URL_MIN: Final = (0, 17, 0)


def _mirror_source_dirs(cwd: Path, out: Path) -> None:
    r"""按源树目录集在 ``out`` 下镜像预建子目录（dot 目录不镜像）。

    tectonic ``--outdir`` 不预建子目录：``\\include``/``\\input`` 目标在
    子目录时 aux 写 ``<out>/<sub>/*.aux`` 直接 os error 2（modec-tec
    实证 2308.00125）。
    """
    # os.walk(followlinks=False) 而非 rglob——rglob 跟随目录符号链且无环
    # 检测，工程内 ``sub -> .`` 软链环会炸 RecursionError 并让 sorted()
    # 物化无穷生成器（normalize.py ``_iter_files`` 同款教训）；walk 的
    # dirnames 原地剪枝同步实现 dot 目录不镜像 + ``out`` 子树不递归，
    # 软链目录只镜像自身（真目录落位供 aux 写入）不下钻。
    # cwd 统一 resolve——``_prepare_main`` 的 ``out`` 恒绝对而 ``cwd``
    # 随 ``wdir`` 可相对, rel-vs-abs 的 ``is_relative_to`` 恒 False →
    # ``out`` 子树剪枝失效, 镜像自我喂养递归爆径长 (c32920 replay 实证)。
    cwd = cwd.resolve()
    for dirpath, dirnames, _files in os.walk(cwd, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and not (base / d).is_relative_to(out)
        ]
        for d in sorted(dirnames):
            (out / (base / d).relative_to(cwd)).mkdir(parents=True, exist_ok=True)


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
        # 默认走 pin（docs/spec/compile.md）；env TEXLATE_TEX_BUNDLE 覆盖，
        # 置空串 = 引擎自带默认 bundle。
        env_bundle = env_opt(ENV_TEX_BUNDLE)
        self.bundle = (
            bundle
            if bundle is not None
            else (env_bundle if env_bundle is not None else TECTONIC_BUNDLE_PIN)
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
        return self.binary or _eng.ensure_tectonic()

    @staticmethod
    def _map_flags(
        flags: Iterable[str] | None,
    ) -> tuple[list[str], list[str], list[str]]:
        """engine_flags → (argv 追加 token, 丢弃的原 flag, 实放行的原 token)。

        放行面 = ``_TECTONIC_FLAG_MAP`` 显式映射 + ``-Z`` 白名单值域
        （``_TECTONIC_Z_OK``；``-Z<opt>`` 单 token 与 ``-Z <opt>`` 两 token
        都收）；其余（含 ``-shell-escape``、``-Z shell-escape`` 后门拼写与
        任何 ``--outdir`` 类重键尝试）进 dropped。``applied`` 是源 token
        级记账——``CompRes.flags_applied`` 取它（dropped 里 ``-Z <x>`` 是
        合体串，按 flist 差集会漏记成已放行）。
        """
        toks, dropped, applied = [], [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            if fl in _TECTONIC_FLAG_MAP:
                toks += _TECTONIC_FLAG_MAP[fl]
                applied.append(fl)
            elif fl == "-Z" and i + 1 < len(flist) and not flist[i + 1].startswith("-"):
                if flist[i + 1].split("=", 1)[0] in _TECTONIC_Z_OK:
                    toks += [fl, flist[i + 1]]
                    applied += [fl, flist[i + 1]]
                else:
                    dropped.append(f"-Z {flist[i + 1]}")
                i += 1
            elif fl.startswith("-Z") and fl != "-Z":
                if fl[2:].split("=", 1)[0] in _TECTONIC_Z_OK:
                    toks.append(fl)
                    applied.append(fl)
                else:
                    dropped.append(fl)
            else:
                dropped.append(fl)
            i += 1
        return toks, dropped, applied

    def _bundle_flag(self, binary: str) -> str:
        """Bundle 落 argv 的 flag 名：本地路径恒 ``--bundle``；URL 按版本分支。

        ``_TECTONIC_BUNDLE_URL_MIN`` 起 ``-X compile`` 撤了 ``--web-bundle``
        （URL 并入 ``--bundle``）；更老的 ``--bundle`` 只认本地路径。版本
        探不出 → ``--bundle``（托管件钉版已在新语法侧，新版是未来默认）。
        """
        if "://" not in self.bundle:
            return "--bundle"
        ver = _eng.tectonic_version(binary)
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
        flag_toks: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 tectonic V2 命令行（docs/spec/compile.md + continue-on-errors 语义对齐）。

        ``flag_toks`` 是 ``_map_flags`` 已放行的 argv token——compile() 喂
        过滤产物（``_map_flags`` 记账单点在 compile 头段，此处不复切；
        xelatex ``_cmd`` 同款预切签名）。
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
            "--print",  # 引擎原话回显——静默模下 stdout 零 ``[N]`` shipout 页标，
            # 活哨 vbox 密度门分母恒 0 退化为「≥30 签名即杀」（t_95c4 JBHI 模板
            # 30 条慢性告警被当 runaway 误杀实证）；页洪臂同埋。``!`` 错误上
            # 下文一并回显——静默模 ``error:`` 摘要不携 payload，fixloop 盲
        ]
        if self.continue_on_errors or best_effort:
            cmd += ["-Z", "continue-on-errors"]
        if self.bundle:
            cmd += [self._bundle_flag(binary), self.bundle]
        for hide in self.hide_paths:
            cmd += ["--hide", str(hide)]
        cmd += list(flag_toks or ())
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913 — 签名即 docs/spec/compile.md 规格面
        self,
        wdir: Path,
        main: str,
        *,
        passes: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CompRes:
        """执行 tectonic 单趟编译（自带 rerun 决策）；deps.mk 供 compiled_dependencies。"""
        del passes  # tectonic 自动决定 pass 数
        res = CompRes(engine=self.name)
        flist = list(flags or ())
        toks, dropped, applied = self._map_flags(flist)
        res.flags_dropped = dropped
        res.flags_applied = applied
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "tectonic not found"
            return res
        main_path, cwd, _stem, out, pdf, log = _prepare_main(
            wdir,
            main,
            outdir,
            default_subdir="_tect_out",
            extra_stale=("dependencies.mk",),
        )
        _mirror_source_dirs(cwd, out)  # 引擎私有步——aux 落子目录需预建
        env = child_env(env_extra)
        cmd = self._cmd(
            binary, out, main_path.name, best_effort=best_effort, flag_toks=toks
        )
        # tectonic 冷拉 bundle/包走进程内 HTTPS——不能像 xelatex 那样断网。
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd, root=wdir, out=out, env=env, enabled=sandbox, allow_net=True
        )
        # 冷 bundle 首拉可能超时：缓存热身后重试一次（compile_bench 惯例）。
        # 重试趟预算封顶 `_TECTONIC_RETRY_TIMEOUT`——首趟超时已烧满 timeout，
        # 满预算重试会把真超时翻倍（audit wave2）。
        outputs = []
        for budget in (timeout, min(timeout, _TECTONIC_RETRY_TIMEOUT))[
            :_TECTONIC_ATTEMPTS
        ]:
            rc, out_s, sec, to = _eng.run_process(
                cmd, cwd=cwd, env=env, timeout=budget, should_cancel=should_cancel
            )
            res.rc = rc
            sig = _rc_to_signal(rc, res.sandbox_mode)
            if sig is not None:
                res.killed_signal = sig
            res.seconds += sec
            outputs.append(out_s)
            # 末次尝试的 timeout 态才算数——首拉超时后重试成功不能再背
            # timed_out=True（否则 judge 走 timeout 短路，出了 pdf 也判 fail）。
            # ``to`` 可携活哨原因 str——槽位短暂带 str 经
            # ``_collect_compile_outputs`` 归位 sentry_reason 并复归 bool。
            res.timed_out = to  # ty: ignore[invalid-assignment]
            if not to:
                break
        res.passes = 1
        _collect_compile_outputs(res, outputs)
        try:
            log_text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        info = parse_log(log_text, project_root=wdir)
        if info.first_error is None and not log_text:
            # tectonic 有时不写 .log 就崩（如 \documentstyle）——stderr 兜底；
            # 无 ``!``/``file:line:`` 错时把 ``error:``/``*: fatal:`` 签名行
            # 归一成 ``! `` 再解析（fixloop ``_report_of`` 同词素双臂）。
            info = parse_log(res.stdout_tail, project_root=wdir)
            if info.first_error is None:
                info = parse_log(
                    normalize_stderr_errors(res.stdout_tail), project_root=wdir
                )
        res.log = info
        _harvest(res, wdir, main, out, pdf, log, log_text)
        return res

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """工程内探测（vendored 文件遮蔽检查）；bundle 探测留 ctan_fetch 层。"""
        if cwd is not None:
            # fixloop 供给的 fname 是 log 可控面——巨名/NUL 按未命中计，
            # ``../``/绝对路逃逸命中同样拒答：命中须留在 cwd 之内。
            cand = cwd / fname
            cand_r = safe_resolve(cand)
            cwd_r = safe_resolve(cwd)
            if (
                cand_r is not None
                and cwd_r is not None
                and cand_r.is_relative_to(cwd_r)
                and safe_is_file(cand)
            ):
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
        """``res.log_text`` 优先、``.log_path`` 读盘兜底；皆空退 stdout_tail。

        ``log_text`` 是 compile 捕获的 .log 原文（未合并 stdout_tail）——
        fixloop 快照/restore、workdir 迁移或测试 double 下 log_path 可缺席/
        不可读，此时 log_text 是唯一真源（repair.log_text_of 同口径）。
        下方 ``error:``/``fatal:`` 归一扫描门钉在「.log 侧文本为空」上。
        """
        text = res.log_text or ""
        if not text and res.log_path is not None:
            with contextlib.suppress(OSError):
                text = res.log_path.read_text(encoding="utf-8", errors="replace")
        info = parse_log(text or res.stdout_tail, project_root=res.workdir)
        if info.first_error is None and not text:
            info = parse_log(
                normalize_stderr_errors(res.stdout_tail), project_root=res.workdir
            )
        return info
