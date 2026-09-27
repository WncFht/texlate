r"""specs/_fixloop.py — fixloop 配方库（原 ``fixloop_bench.py`` 引擎/配方层）。

冷 usertree XelatexEngine + tlpdb 离线索引 + _NoSandbox + _texmf_runner +
TUNA 镜像钉 + RS 惰性装载——stagerun ``fixloop``（stage_fixloop）、
e2e_real ``pipe_fix_condition``、fixloop_bench 驱动三面共用。模块级无 IO：
RS 与 tlpdb 索引皆首访才建（PEP 562 __getattr__ + 锁串行）。

环境口径（与 baseline 可比 + fixloop 需要装包能力）:
  xelatex  : XelatexEngine(halt_on_error=True, texmfhome=work/{pid}/_texmf)
             —— 每篇独立冷 usertree (对齐 baseline 冷 TEXMF 语义), 装包走
             tlmgr --usermode 落该树; init-usertree 由引擎自动补
  tectonic : TectonicEngine(bundle=TECTONIC_BUNDLE_PIN) —— docs/spec/compile.md pin,
             与 rules.yaml filemap.version_guard epoch (2022-07-14) 配套;
             install_file 由 fixloop 注入 CtanFetcher (tlnet 拉包 cwd 平铺)
  sandbox  : compile(sandbox=False) —— 对齐 compilebench_v2 (env paranoid
             flags 但无 sandbox-exec); 且 _texmf 在 wdir 外, sandbox-exec
             白名单不含它会断 usermode 读写
  runner   : run_tool 规则 (updmap-user 等) 注入带 TEXMFHOME/VAR/CONFIG 的
             env —— 否则 fixloop 默认 subprocess 继承裸 os.environ, 会写
             用户真 ~/Library/texmf (污染 + 冷口径失效)
  filemap  : texlive.tlpdb 离线索引 (ctan.py 同款 oracle) —— `tlmgr search
             --global` 逐查询远端会吃镜像 round-robin 抖动 (2026-09-15 实测
             挂出假 "no package provides"); 索引一次性拉取后常驻
             ~/.texlate/cache/filemap.json, 同一份仓库知识无偏差
  mirror   : 所有 tlnet 访问钉 tuna (本机直连实测通; mirror.ctan.org 不通)。
             xelatex usertree `option repository` 逐篇钉; CtanFetcher mirror=TUNA
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from specs import _benchlite as benchlib
from texlate.compile import (
    TectonicEngine,
    XelatexEngine,
    child_env,
    find_tool,
    run_process,
)
from texlate.compile.ctan import CtanFetcher, TlpdbIndex
from texlate.compile.engine import TECTONIC_BUNDLE_PIN
from texlate.compile.fixloop import load_ruleset

#: RS 惰性装载: stagerun/e2e_real 顶层 ``import fixloop_bench`` 只为取配方
#: (_NoSandbox/_init_usertree/_index/TUNA_TLNET), import-time 读 rules.yaml
#: 会撞上半途编辑的规则文件 → 顶层 import 直接崩。模块内走 ``_rs()``, 外部
#: ``flb.RS`` 经 PEP 562 __getattr__ 兼容, 都是首次访问才加载; 线程池并发
#: 首访经锁串行 (与 _index 同型)。
_rs_cache = None
_rs_lock = threading.Lock()


def _rs():
    global _rs_cache  # noqa: PLW0603
    if _rs_cache is None:
        with _rs_lock:
            if _rs_cache is None:
                _rs_cache = load_ruleset()
    return _rs_cache


def __getattr__(name: str):
    if name == "RS":
        return _rs()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


#: tlnet 镜像钉选: 引擎子进程 (child_env) 不透传 *_PROXY → 直连; 本机直连实测
#: tuna/aliyun/sjtug 通、mirror.ctan.org round-robin 不通 (2026-09-15)。
#: usertree `option repository` 逐篇钉住 → tlmgr install 不再吃镜像抖动。
#: 单源在 benchlib（e2e_real 经 `_fl.TUNA_TLNET` 继续从此名取）。
TUNA_TLNET = benchlib.TUNA_TLNET

# ---------------- 引擎包装 ----------------


class _NoSandbox:
    """``compile(sandbox=False)`` 的 Engine 委托 (其余方法/属性透传).

    fixloop 的 ``eng.compile(wdir, main, passes=...)`` 调用面不变;
    ``ctan_fetch`` 注入经 __setattr__ 落到内层引擎 (fixloop._wire_engine)。
    """

    def __init__(self, eng: object) -> None:
        object.__setattr__(self, "_eng", eng)

    def __getattr__(self, k: str) -> object:
        return getattr(self._eng, k)

    def __setattr__(self, k: str, v: object) -> None:
        setattr(self._eng, k, v)

    def compile(self, wdir: Path, main: str, passes: int = 2, **kw: object) -> object:
        return self._eng.compile(wdir, main, passes=passes, sandbox=False, **kw)


# file→pkg oracle: 不用 `tlmgr search --global` (逐查询远端 tlpdb, 镜像 round-robin
# 实测会挂 → 假 "no package provides") —— 换 texlive.tlpdb 离线索引 (ctan.py 同款
# oracle, 一次性 ~2.8MB 下载后 ~/.texlate/cache/filemap.json 常驻)。同一份远端
# 仓库知识, 与环境冷热无关, 不引入测量偏差。
_index_lock = threading.Lock()
_index_cache: TlpdbIndex | None = None


def _index() -> TlpdbIndex | None:
    """惰性构建/装载共享 tlpdb 索引 (tuna 镜像); 失败返回 None → filemap 回退 tlmgr。

    锁串行化首建 (并发 ensure 曾互相覆盖 texlive.tlpdb → 半写解析出残索引);
    失败不缓存——下一篇重试 (lru_cache 会把 None 钉死整批)。
    """
    global _index_cache  # noqa: PLW0603
    if _index_cache is not None:
        return _index_cache
    with _index_lock:
        if _index_cache is None:
            try:
                _index_cache = TlpdbIndex.ensure(mirror=TUNA_TLNET)
            except Exception:  # 索引不可用 → 回退 tlmgr search
                return None
    return _index_cache


def _texmf_env(texmf: Path) -> dict[str, str]:
    """usertree 三件套 env (与 XelatexEngine._env 的同名字典构造)."""
    return child_env(
        {
            "TEXMFHOME": str(texmf / "home"),
            "TEXMFVAR": str(texmf / "var"),
            "TEXMFCONFIG": str(texmf / "config"),
        }
    )


def _init_usertree(texmf: Path) -> None:
    """冷 usertree 预置: init-usertree + 钉 tuna 镜像 (写到本篇 usertree tlpdb).

    引擎 install_file 见到 tlpdb 已存在会跳过自建; 先钉镜像保证后续
    ``tlmgr --usermode install`` 不吃 mirror.ctan.org 的 round-robin 抖动。
    """
    tlmgr = find_tool("tlmgr")
    if tlmgr is None:
        return
    for sub in ("home", "var", "config"):
        (texmf / sub).mkdir(parents=True, exist_ok=True)
    env = _texmf_env(texmf)
    if not (texmf / "home" / "tlpkg" / "texlive.tlpdb").exists():
        run_process(
            [tlmgr, "--usermode", "init-usertree"],
            cwd=Path.cwd(),
            env=env,
            timeout=60,
        )
    run_process(
        [tlmgr, "--usermode", "option", "repository", TUNA_TLNET],
        cwd=Path.cwd(),
        env=env,
        timeout=30,
    )


def _texmf_runner(texmf: Path):
    """run_tool 规则 (updmap-user/mktextfm) 的子进程 env 须指向本篇 usertree。"""

    def run(
        argv: list[str], timeout: int, wdir: Path
    ) -> tuple[int | None, str, float, bool]:
        env = dict(os.environ)
        env.update(
            {
                "TEXMFHOME": str(texmf / "home"),
                "TEXMFVAR": str(texmf / "var"),
                "TEXMFCONFIG": str(texmf / "config"),
            }
        )
        t0 = time.time()
        try:
            p = subprocess.run(  # fixloop 动作原语, argv 无 shell
                argv,
                cwd=str(wdir),
                env=env,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
            return p.returncode, p.stdout or "", time.time() - t0, False
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return None, out, time.time() - t0, True
        except OSError as e:
            return None, f"{type(e).__name__}: {e}", time.time() - t0, False

    return run


def _make_engine(name: str, texmf: Path, wdir: Path) -> _NoSandbox:
    if name == "xelatex":
        _init_usertree(texmf)
        eng = XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=TUNA_TLNET)
        idx = _index()
        if idx is not None:
            # 实例遮蔽 filemap: install_file 内部 self.filemap 调用也走索引
            eng.filemap = idx.query
    else:
        eng = TectonicEngine(bundle=TECTONIC_BUNDLE_PIN)
        # 预注入 ctan_fetch (同 _wire_engine 配方, 但 mirror 钉 tuna);
        # fixloop 见到非 None 即跳过自带注入
        rs = _rs()
        vg = rs.filemap_cfg.get("version_guard") or {}
        eng.ctan_fetch = CtanFetcher(
            wdir,
            index=_index(),
            overrides=rs.filemap_cfg.get("overrides") or {},
            epoch=(str(vg["texlive_format_epoch"]) if vg.get("enabled") else None),
            mirror=TUNA_TLNET,
        )
    return _NoSandbox(eng)
