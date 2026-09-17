r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\input 族。"""

from __future__ import annotations

import re
from pathlib import (
    Path,
)
from typing import (
    TYPE_CHECKING,
)

from texlate.latex.flatten import (
    strip_doc_shell,
)
from texlate.latex.tables import (
    FILENAME_CHARS,
    MAX_INPUTS,
)
from texlate.textutil import (
    decode_tex,
)

from .tokutil import (
    _surface,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import (
        Tok,
    )


class _Input:
    # ------------------------------------------------------------ \input 族

    def _do_input(self, trig: Tok, name: str) -> Tok | None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — 八形态参数语法平铺即 §7 触发面
        r"""``\input`` 族：解析文件名 → 压新 Mouth 进 ``inputs``（§10）。

        失败（不存在/超深/已见）→ warning + 参数回吐 + ``\input`` 本体交出。
        """
        trace = self._trace = []
        shell = False
        tag: str | None = None
        fname: str | None = None
        if name in ("input", "include", "@input"):
            if name in ("input", "@input"):
                # 先试 {file}，再试裸文件名（[A-Za-z0-9._/-]+ 至空白/反斜杠）
                grp = self._read_grouping(trace, "{", "}")
                if grp is not None:
                    fname = _surface(grp).strip()
                else:
                    fname = self._read_bare_filename(trace)
            else:
                grp = self._read_grouping(trace, "{", "}")
                if grp is None:
                    self.unread(trace)
                    return trig
                fname = _surface(grp).strip()
        elif name in ("subfile", "includestandalone"):
            grp = self._read_grouping(trace, "{", "}")
            if grp is None:
                self.unread(trace)
                return trig
            fname, shell = _surface(grp).strip(), True
        elif name in ("import", "subimport"):
            g1 = self._read_grouping(trace, "{", "}")
            g2 = self._read_grouping(trace, "{", "}") if g1 is not None else None
            if g1 is None or g2 is None:
                self.unread(trace)
                return trig
            sub = _surface(g1).strip()
            fn = _surface(g2).strip()
            fname = str(Path(sub) / fn) if sub else fn
        elif name == "InputIfFileExists":
            grp = self._read_grouping(trace, "{", "}")
            if grp is None:
                self.unread(trace)
                return trig
            fname = _surface(grp).strip()  # {then}{else} 留在流内
        elif name == "CatchFileBetweenTags":
            t = self._rt_skip(trace)
            if t is not None and t.kind != "cs":
                self._pushback(trace, t)
            g1 = self._read_grouping(trace, "{", "}")
            g2 = self._read_grouping(trace, "{", "}") if g1 is not None else None
            if g1 is None or g2 is None:
                self.unread(trace)
                return trig
            fname, tag = _surface(g1).strip(), _surface(g2).strip()
        if not fname or "\\" in fname:
            # 含 cs 的文件名是计算式（\@journal\substyle@ext）——无法按
            # 字面解析，非输入尝试：回吐走普通 token 流，不计 missing_input
            self.unread(trace)
            return trig
        file_dir = self._file_dir_of(trig)
        hit = self._resolve_input(fname, file_dir, self.root_dir, top_dir=self.top_dir)
        if hit is None or str(Path(hit).resolve()) in self._seen:
            if hit is None:
                self._warn("missing_input", trig, f"{name}:{fname}")
            self.unread(trace)
            return trig
        if len(self.inputs) > MAX_INPUTS:
            self._warn("missing_input", trig, f"depth>{MAX_INPUTS}:{fname}")
            self.unread(trace)
            return trig
        try:
            sub = decode_tex(Path(hit).read_bytes())
        except OSError:
            self._warn("missing_input", trig, f"{name}:{fname}")
            self.unread(trace)
            return trig
        if shell:
            sub = strip_doc_shell(sub)
        if tag is not None:
            region = self._extract_tag_region(sub, tag)
            if region is None:
                self._warn("missing_input", trig, f"tag:{tag}@{fname}")
                self.unread(trace)
                return trig
            sub = region
        self.push_source(sub, hit)
        # marker 文本带解析后绝对路径——分段器据此登记 inputs[]
        tag_text = f"input_tag:{hit}:{tag}" if tag is not None else f"input:{hit}"
        return self._consumed(tag_text, trig, trace)

    def _read_bare_filename(self, trace: list[Tok]) -> str | None:
        r"""``\input file`` 裸名形：``[A-Za-z0-9._/-]+`` 至空白/反斜杠。"""
        chars: list[str] = []
        while True:
            t = self._rt(trace)
            if t is None:
                break
            if t.kind in ("letter", "other") and t.text in FILENAME_CHARS:
                chars.append(t.text)
                continue
            self._pushback(trace, t)
            break
        return "".join(chars) or None

    def _file_dir_of(self, t: Tok) -> str:
        r"""Token 所在文件的目录（``\input`` 查找序第一级）。

        内存源（无路径）不回退 CWD——返回 ``root_dir``，空串即三级查找全空
        → ``\\input`` 恒不解析（standalone/纯文本入口语义）。
        """
        fid = t.pos[0]
        if 0 <= fid < len(self.file_paths) and self.file_paths[fid]:
            return str(Path(self.file_paths[fid]).parent)
        return self.root_dir

    @staticmethod
    def _resolve_input(
        fname: str, file_dir: str, root_dir: str, *, top_dir: str = ""
    ) -> str | None:
        r"""查找序：including 目录 → 根目录 → paper topdir → basename 补 ``.tex`` → 裸名。

        ``openin_any`` 等价闸（C1）：候选的 **real path** 必须落在已解析
        根集（file_dir/root_dir/top_dir）内——绝对路径或 ``..`` 逃逸出界
        的候选按 miss 处理，永不进 ``read_bytes``（不可信 e-print 经
        ``\input`` 读本机文件 = 外泄面）。含根内 symlink 指出界同样拦。

        扩展名序（F8）：``fname`` 无扩展名 → 先 ``.tex``/``.TEX`` 补全再
        裸名（TeX 对无扩展名 ``\input`` 追加 ``.tex``——裸名垃圾文件不得
        压过 ``foo.tex``）；带显式扩展名 → 原样查找不追加。
        """
        roots: list[Path] = []
        for d in (file_dir, root_dir, top_dir):
            if not d:
                continue
            try:
                r = Path(d).resolve()
            except (OSError, RuntimeError):  # symlink 环等 → 该根出局
                continue
            if r not in roots:
                roots.append(r)

        def _hit(p: Path) -> str | None:
            """``p`` 存在且 real path 落在任一根内 → 解析后绝对路径。"""
            try:
                rp = p.resolve()
            except (OSError, RuntimeError):
                return None
            if rp.exists() and any(rp.is_relative_to(r) for r in roots):
                return str(rp)
            return None

        # 阶段序：各根 × 候选名（含 .tex 补全）→ 各根 × basename 补 .tex。
        # 历史第三段「各根 × 裸名」恒被首段候选覆盖，不再单开。
        names = (
            [fname] if Path(fname).suffix else [fname + ".tex", fname + ".TEX", fname]
        )
        stem = Path(fname).name
        paths = [r / n for r in roots for n in names]
        paths += [r / (stem + ext) for r in roots for ext in (".tex", ".TEX")]
        for p in paths:
            hit = _hit(p)
            if hit is not None:
                return hit
        return None

    @staticmethod
    def _extract_tag_region(tex: str, tag: str) -> str | None:
        r"""``\CatchFileBetweenTags`` 标签区：``%<*tag>`` … ``%</tag>``。"""
        start_rx = re.compile(r"%\s*<\*?" + re.escape(tag) + r">")
        end_rx = re.compile(r"%\s*</" + re.escape(tag) + r">")
        s = start_rx.search(tex)
        if not s:
            return None
        e = end_rx.search(tex, s.end())
        return tex[s.end() : e.start() if e else len(tex)]
