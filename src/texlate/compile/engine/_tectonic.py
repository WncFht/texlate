"""tectonic 引擎 —— 便携 bundle 自足通路（``engine.py`` 拆分叶）。

``run_process``/``tectonic_version``/``ensure_tectonic`` 走 ``_eng.``
运行期回查——测试 patch 缝钉在 ``texlate.compile.engine.X`` 模块名上。
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path
    from typing import Final

    from texlate.compile.loginfo import LogInfo

import texlate.compile.engine as _eng
from texlate.compile.deps import compiled_dependencies
from texlate.compile.loginfo import parse_log
from texlate.compile.sandbox import _apply_sandbox, _rc_to_signal, child_env
from texlate.textutil import env_opt, safe_is_file, safe_resolve

from ._base import DEFAULT_TIMEOUT, CompRes, _checked_main, _collect_compile_outputs

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
    for d in sorted(cwd.rglob("*")):
        if d.is_dir() and not d.is_relative_to(out):
            rel = d.relative_to(cwd)
            if not any(part.startswith(".") for part in rel.parts):
                (out / rel).mkdir(parents=True, exist_ok=True)


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
        env_bundle = env_opt("TEXLATE_TEX_BUNDLE")
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
        flags: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 tectonic V2 命令行（docs/spec/compile.md + continue-on-errors 语义对齐）。

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
        toks, _dropped, _applied = self._map_flags(flags)
        cmd += toks
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913, PLR0915 — 签名即 docs/spec/compile.md 规格面
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
        _toks, dropped, applied = self._map_flags(flist)
        res.flags_dropped = dropped
        res.flags_applied = applied
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "tectonic not found"
            return res
        main_path = _checked_main(wdir, main)
        cwd = main_path.parent
        stem = main_path.stem
        out = (outdir or cwd / "_tect_out").resolve()
        out.mkdir(parents=True, exist_ok=True)
        _mirror_source_dirs(cwd, out)
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
            res.timed_out = to
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
            # tectonic 有时不写 .log 就崩（如 \documentstyle）——stderr 兜底。
            info = parse_log(res.stdout_tail, project_root=wdir)
            if info.first_error is None:
                m = re.search(r"^error: (.+)$", res.stdout_tail, re.MULTILINE)
                if m:
                    info.first_error = "! " + m.group(1)
                    info.n_errors = max(1, info.n_errors)
        res.log = info
        res.log_text = log_text
        res.log_path = log if log.exists() else None
        res.pdf = pdf if pdf.exists() else None
        res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
        res.ok = not res.timed_out and res.rc is not None and res.rc >= 0
        res.workdir = wdir
        res.deps = compiled_dependencies(wdir, main, out, self.name)
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
        """读 res.log_path；缺席/空文件时退 stdout_tail + ``error:`` 扫描。

        ``res.log_text`` 不可作 ``text`` 源——它已合并 stdout_tail，而下方
        ``error:`` 扫描门钉在「.log 文件侧为空」上（合并值会把空 .log +
        非空 stdout 的形态错挡在门外）。
        """
        text = ""
        if res.log_path is not None:
            with contextlib.suppress(OSError):
                text = res.log_path.read_text(encoding="utf-8", errors="replace")
        info = parse_log(text or res.stdout_tail, project_root=res.workdir)
        if info.first_error is None and not text:
            m = re.search(r"^error: (.+)$", res.stdout_tail, re.MULTILINE)
            if m:
                info.first_error = "! " + m.group(1)
                info.n_errors = max(1, info.n_errors)
        return info
