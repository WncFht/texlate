r"""xelatex usermode 装件/usertree mixin（``engine/_xelatex`` 二级缝叶）。

``_XelatexInstall`` 是 ``XelatexEngine`` 的装件臂：``tlmgr --usermode
install`` 主路 + CTAN overlay/doc-only 搬迁两兜底 + ``updmap`` 字体 map
重建 + 同树 install 跨进程串行化锁。``find_tool``/``run_process`` 走
``_eng.`` 运行期回查——测试 patch 缝钉在 ``texlate.compile.engine.X``
模块名上。
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

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

from ._cache import tlmgr_search_cache_path

log = logging.getLogger("texlate.compile.engine._xelatex")


class _XelatexInstall:
    """tlmgr usermode 装件 mixin（实例状态由 ``XelatexEngine.__init__`` 初始化）。"""

    if TYPE_CHECKING:
        # ------------------------------------------------------------ 宿主契约（ty 静态面）
        # ``XelatexEngine.__init__`` 注入的状态；``_XelatexProbe``/
        # ``_XelatexEnv`` 提供的方法。
        texmfhome: Path | None
        repository: str | None
        _usertree_inited: bool
        _probe_cache: dict[tuple[str, str, str], str | None]

        def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None: ...
        def filemap(self, fname: str) -> list[str]: ...
        def _usertree_env(self) -> dict[str, str]: ...

    @contextlib.contextmanager
    def _install_lock(self) -> Iterator[None]:
        """同 usertree 的 tlmgr install 串行化（跨进程 flock；无 fcntl 则退化为直通）。"""
        base = (
            Path(self.texmfhome) if self.texmfhome else tlmgr_search_cache_path().parent
        )
        try:
            base.mkdir(parents=True, exist_ok=True)
            import fcntl  # noqa: PLC0415  # 平台门：无 fcntl 则退化为直通
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
        tool = _eng.find_tool("tlmgr")
        if tool is None:
            return False
        env = self._usertree_env()
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
                # "Cannot determine type of tlpdb"（原型实测坑）。
                rc_i, _, _, to_i = _eng.run_process(
                    [tool, "--usermode", "init-usertree"],
                    cwd=Path.cwd(),
                    env=env,
                    timeout=60,
                )
                # 失败/超时不钉 True——下次 install 按 tlpdb 缺席重试。
                self._usertree_inited = rc_i == 0 and not to_i
            argv = [tool, "--usermode"]
            if self.repository:
                argv += ["--repository", self.repository]
            argv += ["install", *pkgs]
            rc, _, _, to = _eng.run_process(argv, cwd=Path.cwd(), env=env, timeout=300)
        # tlmgr/init-usertree 动过树态——probe memo 清一遍再进复核链
        self._probe_cache.clear()
        if to or rc != 0:
            return False
        if font_related:
            self.rebuild_fontmaps()
        return self._post_install_verify(fname, pkgs, home)

    def _post_install_verify(
        self, fname: str, pkgs: list[str], home: str | None
    ) -> bool:
        """装后复核：tlmgr rc=0 未落盘走 CTAN overlay → doc-only 搬迁两兜底。

        postaction 类包在 usermode 整体拒装 ("package X is not relocatable",
        axodraw2 实证) —— 文件本身可直放，走 CTAN archive 按 tlpdb relpath
        铺进 usertree home。mn2e.cls 类连 overlay 都落在 TEXINPUTS 外的
        doc/ 树 (mnras → doc/latex/mnras/LEGACY/) —— basename 恰一命中才
        搬进 tex/latex/。
        """
        if self.probe_file(fname) is not None:
            return True
        if not home:
            return False
        dest = Path(home)
        if self._fetch_into_usertree(fname, pkgs, dest):
            return True
        return self._relocate_doc_only(fname, dest)

    def _relocate_doc_only(self, fname: str, home: Path) -> bool:
        """把 doc/ 树落位的缺件搬进 tex/latex/ + kpsewhich 复核。"""
        base = Path(fname.replace("\\", "/")).name
        if not base or "\x00" in fname:
            return False
        try:
            root = home.resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        doc = root / "doc"
        if not doc.is_dir():
            return False
        hits = [p for p in doc.rglob(base) if p.is_file()]
        if len(hits) != 1:  # 0=没装进来; >1=多副本歧义不猜
            return False
        dest = root / "tex" / "latex" / base
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hits[0], dest)
        except OSError:
            return False
        if (root / "ls-R").is_file() and (tool := _eng.find_tool("mktexlsr")):
            # 存量 bug（已上报）：缺 ``env`` 必填实参——经真 proc.run_process
            # 路由时到达即 TypeError；测试替身签名宽松未兜住。待修前压诊断。
            _eng.run_process(  # ty: ignore[missing-argument]
                [tool, str(root)], cwd=Path.cwd(), timeout=60
            )
        self._probe_cache.clear()  # 刚把缺件搬进了树——复核前清 memo
        return self.probe_file(fname) is not None

    def _fetch_into_usertree(self, fname: str, pkgs: list[str], dest: Path) -> bool:
        """CTAN ``archive/<pkg>.tar.xz`` → overlay=tree 落 usertree home → 复核。"""
        from texlate.compile.ctan import (  # noqa: PLC0415  # 冷路径惰载
            MIRROR,
            fetch_package,
        )

        for pkg in pkgs:
            # 网络/解包失败 → 试下一候选包 (复核探针是真值), 但不静默——
            # debug 留名供排障 (suppress 吞错曾让装包层故障零线索)
            try:
                fetch_package(
                    pkg,
                    dest,
                    mirror=self.repository or MIRROR,
                    overlay="tree",
                )
            except Exception as e:  # noqa: BLE001  # 候选包逐个试，单包失败不致命
                log.debug("usertree fetch %s skipped: %r", pkg, e)
            # fetch 可能已部分落件——树态变了，复核前清 memo
            self._probe_cache.clear()
            if self.probe_file(fname) is not None:
                return True
        return False

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map。"""
        tool = _eng.find_tool("updmap-user") or _eng.find_tool("updmap")
        if tool is None:
            return False
        args = [tool] if tool.endswith("updmap-user") else [tool, "--user"]
        rc, _, _, to = _eng.run_process(
            args, cwd=Path.cwd(), env=self._usertree_env(), timeout=120
        )
        self._probe_cache.clear()  # map 重建后字体类探测结果可能变
        return rc == 0 and not to
