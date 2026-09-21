"""三级术语表 + ph→ph 恒等注入 + 文档级过滤烤进稳定 system prompt（docs/spec/translate.md）。

yaml 装载走 PyYAML safe_load；`flatten_terms` 把 `{en: zh}` / `{en: {target: zh}}` /
`{"terms": {...}}` 三种形态归一为平表，list 值拒绝（宁可拒载不静默读歪）。

层级（高→低优先级，先写者胜）：

    ① 用户表     数据目录/glossary.yaml | --glossary user.csv    独占覆盖
    ② 论文级     output/{paper}/glossary.local.yaml              介于 user 与 category
    ③ category  terms/{primary_cat}.csv（+ 次 category 并集，声明序先命中先写）
    ④ 内建默认   terms/default.csv                               兜底
    ⑤ 占位符     ph→ph 恒等注入                                   最低，不覆盖真术语

种子表 `terms/*.csv` 搬运自 LaTeXTrans（MIT，tmp/refs/LaTeXTrans/terms/），
category→file 映射 `terms/index.yaml`——加领域不改代码。
"""

from __future__ import annotations

import csv
import logging
import re
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from texlate.textutil import data_root, safe_is_file, safe_resolve

from .placeholders import sort_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

log = logging.getLogger(__name__)

#: 随包分发的种子术语表目录
DEFAULT_TERMS_DIR = Path(__file__).resolve().parent / "terms"
#: 论文级覆盖文件名（优先级介于 user 与 category 之间）
LOCAL_GLOSSARY_NAME = "glossary.local.yaml"


def user_glossary_path() -> Path:
    """用户级术语表缺省位置（优先级最高）：``data_root()/glossary.yaml``。

    调用点现读——``TEXLATE_DATA_DIR`` > ``~/.texlate``（``data_root`` 同口径）；
    ``--data-dir`` 等运行期 env 写入也命中，import 期冻结的常量形会错过。
    """
    return data_root() / "glossary.yaml"


def _default_user_path() -> Path:
    """``Glossary.load`` 缺省 user 层路径：走模块 attr ``USER_GLOSSARY_PATH``。

    setattr 补丁点命中落下的真 attr；未补丁经 ``__getattr__`` 按 env 现算——
    写模块 attr / 钉 ``TEXLATE_DATA_DIR`` 两条补丁通道都有效。
    """
    return sys.modules[__name__].USER_GLOSSARY_PATH

#: 文档级过滤用的词边界正则模板（IGNORECASE|ASCII，照 ieeA `_build_glossary_hints`）
_TERM_BOUNDARY = r"(?<!\w){}(?!\w)"


def _term_pattern(en: str) -> str:
    r"""术语→词边界 pattern：词内空白/``~`` 一律按 ``[~\s]+`` 折缝化。

    源码断行/不断行空格（``computer~vision``、``Maximum\\nLikelihood``）
    会把多词术语劈开——词内逐词 escape 后留缝，边界 lookaround 不动。
    命中语义的正则成文合同——``doc_filter`` 热路径实现走 ``_term_hit``
    扫描（等价口径见各 helper 注）。
    """
    parts = [p for p in re.split(r"[\s~]+", en.strip()) if p]
    return _TERM_BOUNDARY.format("[~\\s]+".join(re.escape(p) for p in parts))


#: ASCII 词字符集——``_term_pattern`` 的 ``\w`` 在 ``re.ASCII`` 旗下口径
_ASCII_WORD = frozenset(string.ascii_letters + string.digits + "_")
#: ws-flex 缝字符集——``_term_pattern`` 的 ``[~\s]+``（``re.ASCII`` 旗下
#: ``\s`` = 六空白符 + 字面 ``~``）
_SEAM = frozenset("~ \t\n\r\f\v")
#: 术语切词——``_term_pattern`` 内 ``re.split(r"[\s~]+")`` 同口径（unicode ``\s``）
_TERM_SPLIT_RX = re.compile(r"[~\s]+")


def _afold(s: str) -> str:
    """ASCII-only 折大小写——``re.IGNORECASE | re.ASCII`` 等价口径。

    非 ASCII 字母不折叠，与 ``str.lower`` 刻意区分。
    """
    return "".join(c.upper() if "a" <= c <= "z" else c for c in s)


def _seam_match(words: list[str], fc: str, i: int) -> int:
    r"""``fc`` 位置 ``i`` 起词序列缝扫——命中返尾位，否则 -1。

    ``[~\s]+`` 贪心吃缝后接字面词；缝字符永不构成词首，故全吃即唯一
    对法（正则回溯无路可退，语义等价）。
    """
    j = i + len(words[0])
    for w in words[1:]:
        k = j
        while k < len(fc) and fc[k] in _SEAM:
            k += 1
        if k == j or not fc.startswith(w, k):
            return -1
        j = k + len(w)
    return j


def _zero_width_hit(fc: str) -> bool:
    r"""空/纯缝 en 的 ``(?<!\w)(?!\w)`` 零宽断言——逐位扫描。"""
    for i in range(len(fc) + 1):
        pre_ok = i == 0 or fc[i - 1] not in _ASCII_WORD
        post_ok = i == len(fc) or fc[i] not in _ASCII_WORD
        if pre_ok and post_ok:
            return True
    return False


def _term_hit(en: str, fc: str) -> bool:
    """折后 corpus ``fc`` 上的 ``_term_pattern`` 命中判定（``doc_filter`` 热路径）。

    逐术语 ``re.search``（O(#terms × corpus 字节)——725 词 × 150KB 实测
    ~1.05s/篇）换成 corpus 一次 ``_afold`` + 首词 ``str.find`` 锚定 +
    ``_seam_match`` 缝扫（~15×）。与 ``tests/test_fuzz_glossary.py`` 的
    ``_oracle_term_hit`` 同算法——``test_fuzz_doc_filter_oracle`` 差分钉。
    空/纯缝 en 退化 ``_zero_width_hit``（旧零宽断言口径保持）。
    """
    words = [_afold(w) for w in _TERM_SPLIT_RX.split(en.strip()) if w]
    if not words:
        return _zero_width_hit(fc)
    first, start = words[0], 0
    while True:
        i = fc.find(first, start)
        if i < 0:
            return False
        j = _seam_match(words, fc, i)
        pre_ok = i == 0 or fc[i - 1] not in _ASCII_WORD
        post_ok = j >= 0 and (j == len(fc) or fc[j] not in _ASCII_WORD)
        if j >= 0 and pre_ok and post_ok:
            return True
        start = i + 1


@dataclass
class TermEntry:
    """一条术语：en→zh + 来源层（provenance 供 term_dict.json 落盘追溯）。"""

    en: str
    zh: str
    source: str  # "user" | "local" | "category:<cat>" | "default" | "placeholder"


@dataclass
class Glossary:
    """合并后的术语表。`terms` 保插入序；渲染时稳定排序见 `doc_filter`。"""

    terms: dict[str, TermEntry] = field(default_factory=dict)

    # ------------------------------------------------------------ 加载

    @classmethod
    def load(  # noqa: PLR0913 -- 五层优先级每层一个 kw-only 参数，spec 形态
        cls,
        *,
        user_path: Path | None = None,
        local_path: Path | None = None,
        categories: Iterable[str] = (),
        terms_dir: Path = DEFAULT_TERMS_DIR,
        include_default: bool = True,
        placeholders: Iterable[str] = (),
    ) -> Glossary:
        """按优先级装载五层。`categories` 为 arXiv category 声明序（先命中先写）。

        加载顺序 = 优先级从高到低，`setdefault` 语义保证先写者胜；
        占位符恒等注入最后执行——优先级最低，绝不覆盖真术语。
        """
        g = cls()
        # ① 用户表（缺省读 数据目录/glossary.yaml；显式 path 优先）
        u = user_path if user_path is not None else _default_user_path()
        if safe_is_file(u):
            g._merge(load_table(u), "user")
        # ② 论文级覆盖
        if local_path is not None and safe_is_file(local_path):
            g._merge(load_table(local_path), "local")
        # ③ category 表（声明序先命中先写）；index 条目 resolve 后须落
        # terms_dir 内——``..``/绝对路径/symlink 外指一律按无文件跳过（D4）
        index = load_index(terms_dir / "index.yaml")
        tdir = safe_resolve(terms_dir)
        for cat in categories:
            for fname in index.get(cat, []):
                cand = safe_resolve(terms_dir / fname)
                if (
                    tdir is None
                    or cand is None
                    or not cand.is_relative_to(tdir)
                    or not safe_is_file(cand)
                ):
                    continue
                g._merge(load_table(cand), f"category:{cat}")
        # ④ 内建默认表
        if include_default:
            default = terms_dir / "default.csv"
            if safe_is_file(default):
                g._merge(load_table(default), "default")
        # ⑤ 占位符恒等注入（最低优先级）；sort_key 非全序，同键按 ph 消歧
        # ——逐字节稳定是前缀缓存命中前提（D7）
        for ph in sorted(set(placeholders), key=lambda p: (sort_key(p), p)):
            g.terms.setdefault(ph, TermEntry(ph, ph, "placeholder"))
        return g

    def _merge(self, table: Mapping[str, str], source: str) -> None:
        for en, zh in table.items():
            self.terms.setdefault(en, TermEntry(en, zh, source))

    # ------------------------------------------------------------ 文档级过滤

    def doc_filter(self, texts: Iterable[str]) -> dict[str, str]:
        r"""扫全部 chunk 源文本，筛出本文实际出现的术语 → `{en: zh}` 有序表。

        命中语义 = `(?<!\\w)term(?!\\w)`（IGNORECASE|ASCII、词内 `[~\\s]+` 缝）
        整篇过滤一次——保证 system prompt 恒定；实现走 `_term_hit` 扫描
        （corpus 只 `_afold` 一次，非逐术语 `re.search`）。渲染排序：真术语按
        en（IGNORECASE）字典序、占位符按 `sort_key` 排尾——逐字节稳定是
        前缀缓存命中前提。
        """
        corpus = _afold("\n".join(texts))
        real: list[TermEntry] = []
        phs: list[TermEntry] = []
        for en, entry in self.terms.items():
            if entry.source == "placeholder":
                phs.append(entry)
                continue
            if _term_hit(en, corpus):
                real.append(entry)
        real.sort(key=lambda e: e.en.lower())
        phs.sort(key=lambda e: (sort_key(e.en), e.en))
        return {e.en: e.zh for e in [*real, *phs]}

    def as_dict(self) -> dict[str, str]:
        """`{en: zh}` 平铺（term_dict.json 落盘用）。"""
        return {e.en: e.zh for e in self.terms.values()}


# ---------------------------------------------------------------- 表文件加载


def load_table(path: Path) -> dict[str, str]:
    """按扩展名分发 CSV/YAML 加载。"""
    if path.suffix == ".csv":
        return load_csv(path)
    if path.suffix in (".yaml", ".yml"):
        return load_yaml(path)
    msg = f"unsupported glossary format: {path} (expect .csv/.yaml)"
    raise ValueError(msg)


def _csv_data_lines(f: Iterable[str]) -> Iterator[str]:
    """``#`` 起头注释行剥除——判定在**原始行**上做（RFC 引号形 ``"#tag"`` 是数据）。

    ``in_quotes`` 跨行近似跟踪：引号字段内嵌换行的 ``#`` 行是字段内容非注释；
    裸 ``"`` 中场出现属畸形输入，跟踪漂移最坏只多收一条注释形术语，不崩。
    """
    in_quotes = False
    for line in f:
        if not in_quotes and line.lstrip().startswith("#"):
            continue
        yield line
        i = 0
        while i < len(line):
            if line[i] == '"':
                if in_quotes and line.startswith('"', i + 1):
                    i += 1  # "" 转义对，不改变引号态
                else:
                    in_quotes = not in_quotes
            i += 1


def load_csv(path: Path) -> dict[str, str]:
    """两列无表头 `en,zh`（LaTeXTrans 语料兼容）。空行/# 注释行跳过。"""
    out: dict[str, str] = {}
    # _csv.field_size_limit 默认 128KiB——单字段超限抛 csv.Error 整表拒载。
    # 抬到平台上限后解析、读完还原（limit 是 _csv 模块全局态）。
    old_limit = csv.field_size_limit()
    new_limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(new_limit)
        except OverflowError:  # win32 C long 上限
            new_limit //= 10
        else:
            break
    try:
        # utf-8-sig：Excel 导出的 BOM 会让首行 en 黏上 U+FEFF 永远查无此词
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(_csv_data_lines(f)):
                if not row:
                    continue
                en = row[0].strip()
                zh = row[1].strip() if len(row) > 1 else ""
                if en:
                    out[en] = zh or en  # 单列行视为"保原语"条目
    finally:
        csv.field_size_limit(old_limit)
    return out


def load_yaml(path: Path) -> dict[str, str]:
    """YAML 术语表：`en: zh` 平表 或 ieeA 结构体 `en: {target, context, ...}`。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return flatten_terms(data, name=str(path))


def load_index(path: Path) -> dict[str, list[str]]:
    """`terms/index.yaml`：cat → 文件名（逗号分隔字符串或单层 list 皆可）。

    不走 `load_yaml`/`flatten_terms`——术语表拒绝 list 值是刻意的，
    但 index 的 list 形态是合法输入（`cat: [a.csv, b.csv]`）。
    """
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"{path}: index must be a mapping, got {type(data).__name__}"
        raise TypeError(msg)
    out: dict[str, list[str]] = {}
    for cat, files in data.items():
        if isinstance(files, str):
            out[str(cat)] = [f.strip() for f in files.split(",") if f.strip()]
        elif isinstance(files, list):
            out[str(cat)] = [str(f).strip() for f in files if str(f).strip()]
        else:
            msg = (
                f"{path}: index entry {cat!r} must be a string or list, "
                f"got {type(files).__name__}"
            )
            raise TypeError(msg)
    return out


def flatten_terms(data: object, *, name: str) -> dict[str, str]:
    """把 yaml/csv 读出的结构归一为 `{en: zh}`。

    接受 `{en: zh}`、`{en: {target: zh, ...}}`、`{"terms": {...}}` 三种形态。
    yaml 空值（``en:``/``~``/``{target: null}``）按保原语处理——``str(None)``
    会把字面 ``"None"`` 注进 prompt。
    """
    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"{name}: glossary must be a mapping, got {type(data).__name__}"
        raise TypeError(msg)
    if "terms" in data and isinstance(data["terms"], dict):
        data = data["terms"]
    out: dict[str, str] = {}
    for k, v in data.items():
        en = str(k).strip()
        if not en:
            continue
        if isinstance(v, dict):
            t = v.get("target")
            zh = en if t is None else (str(t).strip() or en)
        elif isinstance(v, list):
            msg = f"{name}: term {en!r} has list value, expected string or mapping"
            raise TypeError(msg)
        elif v is None:
            zh = en
        else:
            zh = str(v).strip() or en
        out[en] = zh
    return out


def __getattr__(name: str) -> object:
    # ``USER_GLOSSARY_PATH`` 历史常量形的兼容出口——from-import/属性读/
    # setattr 补丁点全兼容；动态求值让 ``TEXLATE_DATA_DIR`` 运行期写入
    # 生效。setattr 落真 attr 后本函数不再被调，补丁语义与旧常量一致。
    if name == "USER_GLOSSARY_PATH":
        return user_glossary_path()
    raise AttributeError(name)
