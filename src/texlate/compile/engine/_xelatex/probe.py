r"""xelatex 文件探测/file→pkg 索引 mixin（``engine/_xelatex`` 二级缝叶）。

``_XelatexProbe`` 是 ``XelatexEngine`` 的探测臂：``kpsewhich`` 树探测
（进程内 memo + cwd 直查）、tlpdb 离线索引与 ``tlmgr search --file``
在线兜底。``find_tool``/``run_process`` 走 ``_eng.`` 运行期回查——
测试 patch 缝钉在 ``texlate.compile.engine.X`` 模块名上。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Final

    from texlate.compile.proc import run_process
    from texlate.compile.toolchain import find_tool

    class _EngNS:
        """``_eng`` 静态面——锚位真签名经 staticmethod 别名钉入。

        ``engine/__init__`` 经 seams ``__getattr__`` 惰性回指锚位模块，ty
        仅见 ``object``；借 TYPE_CHECKING 命名空间把 ``_eng.X`` 回查收窄到
        真签名。仅类型面视图——运行期 ``else`` 分支绑定原样，patch 缝
        （``monkeypatch.setattr(engine.X, …)`` → 叶侧 ``_eng.X`` 命中）零漂移。
        """

        find_tool = staticmethod(find_tool)
        run_process = staticmethod(run_process)

    _eng = _EngNS()
else:
    import texlate.compile.engine as _eng

from texlate.compile.engine._cache import load_search_cache, save_search_cache
from texlate.textutil import env_raw, safe_is_file

#: ``probe_file`` texmf 树探测 memo 条数上限（B14 fix#3）：fixloop 格均
#: ~10–40 名、跨 cell 名集高重叠，容量远超格均即全覆盖；撞顶整表清——
#: 树态随 install 漂移，老条目残值低。
_PROBE_MEMO_MAX: Final = 4096


class _XelatexProbe:
    """kpsewhich/tlpdb/tlmgr 探测 mixin（实例状态由 ``XelatexEngine.__init__`` 初始化）。"""

    if TYPE_CHECKING:
        # ------------------------------------------------------------ 宿主契约（ty 静态面）
        # ``XelatexEngine.__init__`` 注入的状态；``_XelatexEnv`` 提供的方法。
        texmfhome: Path | None
        repository: str | None
        _probe_cache: dict[tuple[str, str, str], str | None]
        _search_cache: dict[str, list[str]] | None

        def _env(self, extra: dict[str, str] | None) -> dict[str, str]: ...
        def _usertree_env(self) -> dict[str, str]: ...

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """用 kpsewhich 探测文件可解析路径（texmf 树侧结果进程内 memo）。

        ``cwd`` 对应的 ``.`` 搜索元素拆成 ``Path.is_file`` 直查、不进 memo
        ——wdir 内文件随 fixloop 落件动态出现（vendored 平铺/stub 写件），
        直查让阴性缓存永不遮蔽新件。texmf 树探测按 ``(fname, texmfhome,
        宿主 TEXMFHOME)`` 键进 ``_probe_cache``——树内容变动只发生在本实例
        install/updmap 通路（各落件点统一清缓存）；跨进程同伴装件的陈旧
        阴性顶多让 tlmgr 空转一趟，``_post_install_verify`` 复核链自清。
        """
        if "\x00" in fname:
            return None  # NUL 进 argv 炸 Popen ValueError（log 可控面）
        base = cwd if cwd is not None else Path.cwd()
        if safe_is_file(cand := base / fname):
            return str(cand)
        key = (fname, str(self.texmfhome), env_raw("TEXMFHOME"))
        if key in self._probe_cache:
            return self._probe_cache[key]
        hit = self._probe_tree(fname, base)
        if len(self._probe_cache) >= _PROBE_MEMO_MAX:
            self._probe_cache.clear()
        self._probe_cache[key] = hit
        return hit

    def _probe_tree(self, fname: str, base: Path) -> str | None:
        """``kpsewhich`` 纯树探测（``.`` 元素已由 ``probe_file`` cwd 直查覆盖）。

        子进程 cwd 取 ``base`` 而非进程 cwd——``safe_is_file`` 已直查过
        ``base/fname``, ``.`` 元素在该基上永不另产命中; 进程 cwd 落 wdir
        内时旧写法会让 kpsewhich ``.`` 命中 vendored 自件并毒化 memo
        (seki 15 era 件全 self-hit → vendored_shadow 条件死面实证)。
        ``base`` 不在档（wdir 中途被清）时回落**文件系统根**而非进程
        cwd——进程 cwd 的 ``.`` 命中是 cwd 相关结果，却会按 cwd 无关键
        ``(fname, texmfhome, TEXMFHOME)`` 进 ``_probe_cache`` 毒化后续
        一切 workdir 的探测；根目录下相对 ``fname`` 必 miss，结果天然
        cwd 无关、缓存安全。
        """
        tool = _eng.find_tool("kpsewhich")
        if tool is None:
            return None
        rc, out, _, to = _eng.run_process(
            [tool, fname],
            cwd=base if base.is_dir() else Path(base.anchor or os.sep),
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
        from texlate.compile.ctan import (  # noqa: PLC0415  # 冷路径惰载
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
        if "\x00" in fname:
            return []  # NUL 进 tlmgr argv 炸 Popen ValueError（log 可控面）
        cache = self._search_cache_map()
        key = "/" + fname
        if key in cache:
            return cache[key]
        pkgs = self._filemap_index(fname)
        if pkgs is not None:
            cache[key] = pkgs
            return pkgs
        pkgs = self._filemap_tlmgr(fname)
        cache[key] = pkgs  # 进程内 memo 保留阴性（同文件重查不打爆 tlmgr）
        if pkgs:
            save_search_cache(cache)
        return pkgs

    def _filemap_tlmgr(self, fname: str) -> list[str]:
        """`tlmgr search --global --file /fname` 在线通路（索引缺席时兜底）。"""
        tool = _eng.find_tool("tlmgr")
        if tool is None:
            return []
        rc, out, _, to = _eng.run_process(
            [tool, "search", "--global", "--file", "/" + fname],
            cwd=Path.cwd(),
            env=self._usertree_env(),
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
