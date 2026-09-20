r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\input 族。"""

from __future__ import annotations

from pathlib import (
    Path,
)
from typing import (
    TYPE_CHECKING,
)

from texlate.latex.flatten import (
    extract_tag_region,
    read_input_blob,
    resolve_input,
    strip_doc_shell,
)
from texlate.latex.tables import (
    FILENAME_CHARS,
    MAX_INPUTS,
    strip_fname_quotes,
)
from texlate.textutil import (
    decode_tex,
)

from .entries import (
    ArgMismatch,
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

    def input_expand(self, trig: Tok) -> tuple[bool, Tok | None]:
        r"""前瞻臂 ``\input`` 族展开（``TokenSource`` 契约）→ ``(True, hit)``。

        分段器 env/verbatim 体配对用 ``read()`` 原始前瞻、不触发展开——
        ``\input`` 族 cs 交回此口正常内联（marker 顶顶替已入列的 cs，
        新源 token 由后续 ``read()`` 照常进收集）。``ArgMismatch``（流尽
        残参/必需组缺席/解析失败）→ ``_trace`` 回吐 + ``hit=None``
        （cs 留 literal）。
        """
        try:
            return True, self._do_input(trig, trig.text)
        except ArgMismatch:
            self.unread(self._trace)  # ArgMismatch 回吐协议（§3.5）
            return True, None

    def _do_input(self, trig: Tok, name: str) -> Tok | None:  # noqa: C901, PLR0912, PLR0915 — 八形态参数语法平铺即 §7 触发面
        r"""``\input`` 族：解析文件名 → 压新 Mouth 进 ``inputs``（§10）。

        失败（参数缺席/不存在/超深/已见）→ ``ArgMismatch``——§3.5 协议由
        ``input_expand``/``_exec_prim`` 统一回吐已读 + 交出 ``\input`` 本体；
        warning 在 raise 前按序记。
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
                grp = self._req_grouping(trace, "{", "}")
                fname = _surface(grp).strip()
        elif name in ("subfile", "includestandalone"):
            grp = self._req_grouping(trace, "{", "}")
            fname, shell = _surface(grp).strip(), True
        elif name in ("import", "subimport"):
            g1 = self._req_grouping(trace, "{", "}")
            g2 = self._req_grouping(trace, "{", "}")
            sub = _surface(g1).strip()
            fn = _surface(g2).strip()
            fname = str(Path(sub) / fn) if sub else fn
        elif name == "InputIfFileExists":
            grp = self._req_grouping(trace, "{", "}")
            fname = _surface(grp).strip()  # {then}{else} 留在流内
        elif name == "CatchFileBetweenTags":
            t = self._rt_skip(trace)
            if t is not None and t.kind != "cs":
                self._pushback(trace, t)
            g1 = self._req_grouping(trace, "{", "}")
            g2 = self._req_grouping(trace, "{", "}")
            fname, tag = _surface(g1).strip(), _surface(g2).strip()
        if fname is not None:
            fname = strip_fname_quotes(fname)
        if not fname or "\\" in fname:
            # 含 cs 的文件名是计算式（\@journal\substyle@ext）——无法按
            # 字面解析，非输入尝试：回吐走普通 token 流，不计 missing_input
            raise ArgMismatch
        file_dir = self._file_dir_of(trig)
        hit = self._resolve_input(fname, file_dir, self.root_dir, top_dir=self.top_dir)
        if hit is None or str(Path(hit).resolve()) in self._seen:
            if hit is None:
                self._warn("missing_input", trig, f"{name}:{fname}")
            raise ArgMismatch
        if len(self.inputs) > MAX_INPUTS:
            self._warn("missing_input", trig, f"depth>{MAX_INPUTS}:{fname}")
            raise ArgMismatch
        try:
            sub = decode_tex(read_input_blob(hit))
        except OSError:
            self._warn("missing_input", trig, f"{name}:{fname}")
            raise ArgMismatch from None
        if shell:
            sub = strip_doc_shell(sub)
        if tag is not None:
            region = extract_tag_region(sub, tag)
            if region is None:
                self._warn("missing_input", trig, f"tag:{tag}@{fname}")
                raise ArgMismatch
            sub = region
        self.push_source(sub, hit)
        # marker 文本带解析后绝对路径——分段器据此登记 inputs[]
        tag_text = f"input_tag:{hit}:{tag}" if tag is not None else f"input:{hit}"
        return self._consumed(tag_text, trig, trace)

    def _read_bare_filename(self, trace: list[Tok]) -> str | None:
        r"""``\input file`` 裸名形：``[A-Za-z0-9._/-]+`` 至空白/反斜杠。

        引号形 ``\input"a b.tex"``（web2c 带空格文件名约定）——开引号起
        字面收至闭引号，闭引号缺席则收到流尾。
        """
        t = self._rt(trace)
        if t is not None and t.kind in ("letter", "other") and t.text == '"':
            chars: list[str] = []
            while True:
                t = self._rt(trace)
                if t is None or (t.kind in ("letter", "other") and t.text == '"'):
                    break
                chars.append(t.text)
            return "".join(chars) or None
        if t is not None:
            self._pushback(trace, t)
        chars = []
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
        r"""``texlate.latex.flatten.resolve_input`` 的 static 契约面。

        查找序/``openin_any`` 闸/扩展名序（F8）实现已并入 flatten——本方法
        仅留签名面（fuzz oracle/tests 直调），``top_dir`` 空串等价缺席。
        """
        return resolve_input(fname, file_dir, root_dir, top_dir=top_dir)
