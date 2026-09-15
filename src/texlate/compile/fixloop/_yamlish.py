"""yamlish — rules.yaml 的零依赖 YAML 子集加载器。

`load_yaml()` 优先走 PyYAML (若环境已装), 否则用本模块的子集解析器。
子集范围 (rules.yaml 只用这些, 刻意收窄以保两个解析器结果一致):

- 块级 mapping: ``key: value`` / ``key:`` + 缩进更深子块
- 块级 sequence: ``- item``; item 可为标量/flow/行内开始的 map
  (``- id: x`` 后续同缩进行续写同一 map); key 下同缩进 ``- `` 列表合法
- flow 集合: ``{k: v, ...}`` / ``[a, b]``, 可嵌套, **可跨行**
  (prettier 会把超长 flow 折成多行块 —— 续行吸进同一集合,
  要求缩进深于父行)
- 标量: 裸串 / "双引号"(转义集见 _DQ_ESC) / '单引号'(''→');
  归并 int/float/true/false/null
- 注释: 行首或空白后 ``#`` 到行尾 (引号内不计)

不支持 (报 YamlishError): 多文档 ``---``、anchor ``&``/别名 ``*``、
tag ``!``、块标量 ``|``/``>``、tab 缩进、多行裸标量。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["YamlishError", "load_yaml", "loads"]


class YamlishError(ValueError):
    """rules.yaml 子集语法错误 (带行号)。"""


def _die(msg: str) -> NoReturn:
    """统一抛 :class:`YamlishError` (长消息集中构造)。"""
    raise YamlishError(msg)


_DQ_ESC = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "_": "_",
    "N": "",
    "L": " ",
    "P": " ",
}
_INT_RE = re.compile(r"[-+]?\d+$")
_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?$")
_CLOSER_ONLY_RE = re.compile(r"[}\], \t]+")  # 多行 flow 的纯闭合行 (可与父同缩进)
_NULLS = {"", "~", "null", "Null", "NULL"}
_TRUE = {"true", "True", "TRUE"}
_FALSE = {"false", "False", "FALSE"}


def load_yaml(path: Path) -> Any:  # noqa: ANN401  # yaml 装载天然 Any 返回
    """加载 yaml 文件; PyYAML 可用时优先 (fast-path), 否则子集解析器。"""
    try:
        import yaml  # noqa: PLC0415  # 可选依赖: 存在则用全量实现
    except ImportError:
        yaml = None
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)
    return loads(text)


def loads(text: str) -> Any:  # noqa: ANN401
    """解析 YAML 子集文本 → python 对象。"""
    return _Parser(text).parse()


@dataclass(slots=True)
class _Line:
    no: int
    indent: int
    text: str  # 已剥注释与行尾空白; 前导空白深度在 indent


def _strip_comment(raw: str, lineno: int) -> str:  # noqa: C901  # 引号状态机分支即本体
    """剥行尾注释: ``#`` 仅在行首或前置空白且不在引号内时生效。"""
    in_s = in_d = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_s:
            if ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    i += 1
                else:
                    in_s = False
        elif in_d:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_d = False
        elif ch == "'":
            in_s = True
        elif ch == '"':
            in_d = True
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].rstrip()
        i += 1
    if in_s or in_d:
        _die(f"L{lineno}: 引号未闭合")
    return raw.rstrip()


class _Parser:
    def __init__(self, text: str) -> None:
        self.lines: list[_Line] = []
        for no, raw in enumerate(text.splitlines(), 1):
            stripped = _strip_comment(raw, no)
            if not stripped.strip():
                continue
            lead = len(stripped) - len(stripped.lstrip())  # 全空白前缀
            if "\t" in stripped[:lead]:
                _die(f"L{no}: 缩进含 tab")
            indent = len(stripped) - len(stripped.lstrip(" "))
            head = stripped.strip()
            for bad, why in (
                ("---", "多文档标记"),
                ("...", "文档结束标记"),
                ("%", "指令行"),
            ):
                if head.startswith(bad):
                    _die(f"L{no}: 不支持 {why} ({bad})")
            self.lines.append(_Line(no, indent, head))
        self.pos = 0

    def _peek(self) -> _Line | None:
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def parse(self) -> Any:  # noqa: ANN401
        if not self.lines:
            return None
        out = self._block(self.lines[0].indent)
        if self._peek() is not None:
            t = self._peek()
            _die(f"L{t.no}: 顶层块已闭合后仍有内容 (缩进 {t.indent})")
        return out

    # ---- 块级 ----

    def _block(self, indent: int) -> Any:  # noqa: ANN401
        t = self._peek()
        if t is None or t.indent < indent:
            return None
        if t.indent != indent:
            _die(f"L{t.no}: 缩进 {t.indent} 与块级 {indent} 不齐")
        if self._is_seq_item(t.text):
            return self._seq(indent)
        if self._map_key(t.text) is not None:
            return self._map(indent)
        # 单行裸值 (flow 可续行: 传 -1 允许同缩进闭合行)
        self.pos += 1
        return self._inline(t.text, t.no, t.indent - 1)

    @staticmethod
    def _is_seq_item(text: str) -> bool:
        return text == "-" or text.startswith(("- ", "-\t"))

    def _seq(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            t = self._peek()
            if t is None or t.indent != indent or not self._is_seq_item(t.text):
                return items
            self.pos += 1
            body = t.text[1:].lstrip()
            item_indent = indent + 2
            if not body:
                nxt = self._peek()
                items.append(
                    self._block(nxt.indent) if nxt and nxt.indent > indent else None
                )
            elif self._map_key(body) is not None:
                # "- key: val" —— item 是 map, 首键内嵌, 后续同缩进续写
                items.append(self._map(item_indent, first=(t.no, body)))
            else:
                items.append(self._inline(body, t.no, indent))

    def _map(self, indent: int, first: tuple[int, str] | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        pending = first
        while True:
            if pending is not None:
                no, text = pending
                pending = None
            else:
                t = self._peek()
                if (
                    t is None
                    or t.indent != indent
                    or self._is_seq_item(t.text)
                    or self._map_key(t.text) is None
                ):
                    return out
                self.pos += 1
                no, text = t.no, t.text
            key, rest = self._split_key(text, no)
            if key in out:
                _die(f"L{no}: 重复键 {key!r}")
            out[key] = self._value(rest, indent, no)

    def _value(self, rest: str, indent: int, no: int) -> Any:  # noqa: ANN401
        if rest:
            return self._inline(rest, no, indent)
        nxt = self._peek()
        if nxt is not None and nxt.indent > indent:
            return self._block(nxt.indent)
        if nxt is not None and nxt.indent == indent and self._is_seq_item(nxt.text):
            return self._seq(indent)  # key 下同缩进 seq 合法
        return None

    # ---- key 判定 ----

    @staticmethod
    def _map_key(text: str) -> int | None:  # noqa: C901, PLR0912  # 冒号定位状态机
        """返回 ``key:`` 的冒号位置 (后随空白或行尾), 非 map 行返 None。"""
        if text[0] in "{[":
            return None
        in_s = in_d = False
        depth = 0
        i = 0
        while i < len(text):
            ch = text[i]
            if in_s:
                if ch == "'":
                    if i + 1 < len(text) and text[i + 1] == "'":
                        i += 1
                    else:
                        in_s = False
            elif in_d:
                if ch == "\\":
                    i += 1
                elif ch == '"':
                    in_d = False
            elif ch == "'":
                in_s = True
            elif ch == '"':
                in_d = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
            elif ch == ":" and depth == 0:
                if i + 1 == len(text) or text[i + 1] in " \t":
                    return i
            elif ch == "#" and text[i - 1] in " \t":
                return None
            i += 1
        return None

    def _split_key(self, text: str, no: int) -> tuple[str, str]:
        i = self._map_key(text)
        if i is None:
            _die(f"L{no}: 期望 map 行, 得到 {text!r}")
        key = text[:i].strip()
        if not key:
            _die(f"L{no}: 空键")
        if key[0] in "\"'":
            key = self._quoted(key, no)[0]
        return key, text[i + 1 :].strip()

    # ---- 行内 (flow / 标量) ----

    def _inline(self, text: str, no: int, parent_indent: int = -1) -> Any:  # noqa: ANN401
        text = text.strip()
        if not text:
            return None
        if text[0] in "|>&*!":
            _die(f"L{no}: 不支持块标量/anchor/tag ({text[0]})")
        if text[0] in "{[":
            while not _flow_closed(text):  # prettier 折行的多行 flow: 续行吸进
                t = self._peek()
                if t is None or (
                    t.indent <= parent_indent and not _CLOSER_ONLY_RE.fullmatch(t.text)
                ):
                    _die(f"L{no}: flow 集合未闭合")
                self.pos += 1
                text = f"{text} {t.text}"
            val, pos = self._flow(text, 0, no)
            if text[pos:].strip():
                _die(f"L{no}: flow 集合后有尾随内容")
            return val
        if text[0] in "\"'":
            val, pos = self._quoted(text, no)
            if text[pos:].strip():
                _die(f"L{no}: 引号标量后有尾随内容")
            return val
        return _coerce(text)

    def _flow(self, text: str, i: int, no: int) -> tuple[Any, int]:  # noqa: C901, PLR0912, PLR0915  # flow 递归下降分支即本体
        i = _skip_ws(text, i)
        ch = text[i] if i < len(text) else ""
        if ch == "{":
            out: dict[str, Any] = {}
            i += 1
            while True:
                i = _skip_ws(text, i)
                if i >= len(text):
                    _die(f"L{no}: flow map 未闭合")
                if text[i] == "}":
                    return out, i + 1
                if text[i] == ",":
                    i += 1
                    continue
                j = i
                in_s = in_d = False
                while j < len(text):
                    c = text[j]
                    if in_s:
                        if c == "'":
                            in_s = False
                    elif in_d:
                        if c == "\\":
                            j += 1
                        elif c == '"':
                            in_d = False
                    elif c == "'":
                        in_s = True
                    elif c == '"':
                        in_d = True
                    elif c == ":":
                        break
                    elif c in ",{}[]":
                        _die(f"L{no}: flow map 键内非法字符 {c!r}")
                    j += 1
                if j >= len(text):
                    _die(f"L{no}: flow map 键缺冒号")
                key_txt = text[i:j].strip()
                key = self._quoted(key_txt, no)[0] if key_txt[:1] in "\"'" else key_txt
                val, i = self._flow(text, j + 1, no)
                out[key] = val
        if ch == "[":
            out_l: list[Any] = []
            i += 1
            while True:
                i = _skip_ws(text, i)
                if i >= len(text):
                    _die(f"L{no}: flow seq 未闭合")
                if text[i] == "]":
                    return out_l, i + 1
                if text[i] == ",":
                    i += 1
                    continue
                val, i = self._flow(text, i, no)
                out_l.append(val)
        return self._scalar_in_flow(text, i, no)

    def _scalar_in_flow(self, text: str, i: int, no: int) -> tuple[Any, int]:
        i = _skip_ws(text, i)
        if i < len(text) and text[i] in "\"'":
            return self._quoted_at(text, i, no)
        j = i
        while j < len(text) and text[j] not in ",}]":
            j += 1
        return _coerce(text[i:j].strip()), j

    def _quoted(self, text: str, no: int) -> tuple[str, int]:
        return self._quoted_at(text, 0, no)

    def _quoted_at(self, text: str, i: int, no: int) -> tuple[str, int]:  # noqa: C901, PLR0912  # 引号转义状态机
        q = text[i]
        j = i + 1
        buf: list[str] = []
        if q == "'":
            while j < len(text):
                if text[j] == "'":
                    if j + 1 < len(text) and text[j + 1] == "'":
                        buf.append("'")
                        j += 1
                    else:
                        return "".join(buf), j + 1
                else:
                    buf.append(text[j])
                j += 1
            _die(f"L{no}: 单引号串未闭合")
        while j < len(text):
            c = text[j]
            if c == '"':
                return "".join(buf), j + 1
            if c == "\\":
                j += 1
                if j >= len(text):
                    break
                e = text[j]
                if e in _DQ_ESC:
                    buf.append(_DQ_ESC[e])
                elif e == "x":
                    buf.append(chr(int(text[j + 1 : j + 3], 16)))
                    j += 2
                elif e == "u":
                    buf.append(chr(int(text[j + 1 : j + 5], 16)))
                    j += 4
                elif e == "U":
                    buf.append(chr(int(text[j + 1 : j + 9], 16)))
                    j += 8
                else:
                    _die(f"L{no}: 未知转义 \\{e}")
            else:
                buf.append(c)
            j += 1
        _die(f"L{no}: 双引号串未闭合")


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def _flow_closed(text: str) -> bool:  # noqa: C901  # 引号状态机分支即本体
    """Flow 括号深度在引号外归零 → True (多行 flow 续行判定用)。"""
    depth = 0
    in_s = in_d = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_s:
            if c == "'":
                in_s = False
        elif in_d:
            if c == "\\":
                i += 1
            elif c == '"':
                in_d = False
        elif c == "'":
            in_s = True
        elif c == '"':
            in_d = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return depth <= 0


def _coerce(s: str) -> Any:  # noqa: PLR0911, ANN401  # 标量归并 + yaml Any 语义
    if s in _NULLS:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s) and any(c.isdigit() for c in s):
        try:
            return float(s)
        except ValueError:
            return s
    return s
