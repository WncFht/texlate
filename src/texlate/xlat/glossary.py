"""三级术语表 + ph→ph 恒等注入 + 文档级过滤烤进稳定 system prompt（docs/08 §1.4）。

层级（高→低优先级，先写者胜）：

    ① 用户表     ~/.texlate/glossary.yaml | --glossary user.csv   独占覆盖
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .placeholders import sort_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

log = logging.getLogger(__name__)

#: 随包分发的种子术语表目录
DEFAULT_TERMS_DIR = Path(__file__).resolve().parent / "terms"
#: 用户级术语表默认位置（优先级最高）
USER_GLOSSARY_PATH = Path.home() / ".texlate" / "glossary.yaml"
#: 论文级覆盖文件名（优先级介于 user 与 category 之间）
LOCAL_GLOSSARY_NAME = "glossary.local.yaml"

#: 文档级过滤用的词边界正则模板（IGNORECASE|ASCII，照 ieeA `_build_glossary_hints`）
_TERM_BOUNDARY = r"(?<!\w){}(?!\w)"


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
        # ① 用户表（缺省读 ~/.texlate/glossary.yaml；显式 path 优先）
        u = user_path if user_path is not None else USER_GLOSSARY_PATH
        if u.exists():
            g._merge(load_table(u), "user")
        # ② 论文级覆盖
        if local_path is not None and local_path.exists():
            g._merge(load_table(local_path), "local")
        # ③ category 表（声明序先命中先写）
        index = load_index(terms_dir / "index.yaml")
        for cat in categories:
            for fname in index.get(cat, []):
                path = terms_dir / fname
                if path.exists():
                    g._merge(load_table(path), f"category:{cat}")
        # ④ 内建默认表
        if include_default:
            default = terms_dir / "default.csv"
            if default.exists():
                g._merge(load_table(default), "default")
        # ⑤ 占位符恒等注入（最低优先级）
        for ph in sorted(set(placeholders), key=sort_key):
            g.terms.setdefault(ph, TermEntry(ph, ph, "placeholder"))
        return g

    def _merge(self, table: Mapping[str, str], source: str) -> None:
        for en, zh in table.items():
            self.terms.setdefault(en, TermEntry(en, zh, source))

    # ------------------------------------------------------------ 文档级过滤

    def doc_filter(self, texts: Iterable[str]) -> dict[str, str]:
        r"""扫全部 chunk 源文本，筛出本文实际出现的术语 → `{en: zh}` 有序表。

        正则 `(?<!\\w)term(?!\\w)`（IGNORECASE|ASCII）整篇过滤一次——保证 system
        prompt 恒定。渲染排序：真术语按 en（IGNORECASE）字典序、占位符按
        `sort_key` 排尾——逐字节稳定是前缀缓存命中前提。
        """
        corpus = "\n".join(texts)
        real: list[TermEntry] = []
        phs: list[TermEntry] = []
        for en, entry in self.terms.items():
            if entry.source == "placeholder":
                phs.append(entry)
                continue
            if re.search(
                _TERM_BOUNDARY.format(re.escape(en)), corpus, re.IGNORECASE | re.ASCII
            ):
                real.append(entry)
        real.sort(key=lambda e: e.en.lower())
        phs.sort(key=lambda e: sort_key(e.en))
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


def load_csv(path: Path) -> dict[str, str]:
    """两列无表头 `en,zh`（LaTeXTrans 语料兼容）。空行/# 注释行跳过。"""
    out: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row or (row[0].strip().startswith("#")):
                continue
            en = row[0].strip()
            zh = row[1].strip() if len(row) > 1 else ""
            if en:
                out[en] = zh or en  # 单列行视为"保原语"条目
    return out


def load_yaml(path: Path) -> dict[str, str]:
    """YAML 术语表：`en: zh` 平表 或 ieeA 结构体 `en: {target, context, ...}`。

    优先用 PyYAML（装了的话）；没有就走内置迷你解析——只支持平表与一层嵌套
    映射，覆盖 glossary.yaml/glossary.local.yaml/index.yaml 的全部形态。
    """
    try:
        import yaml  # noqa: PLC0415 -- PyYAML 是可选依赖，缺失时走 mini_yaml
    except ImportError:
        data = mini_yaml(path.read_text(encoding="utf-8"), name=str(path))
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return flatten_terms(data, name=str(path))


def load_index(path: Path) -> dict[str, list[str]]:
    """`terms/index.yaml`：cat → 文件名（逗号分隔或单层 list）。"""
    if not path.exists():
        return {}
    raw = load_yaml(path)
    return {
        cat: [f.strip() for f in files.split(",") if f.strip()]
        for cat, files in raw.items()
    }


def flatten_terms(data: object, *, name: str) -> dict[str, str]:
    """把 yaml/csv 读出的结构归一为 `{en: zh}`。

    接受 `{en: zh}`、`{en: {target: zh, ...}}`、`{"terms": {...}}` 三种形态。
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
            zh = str(v.get("target", en)).strip() or en
        else:
            zh = str(v).strip() or en
        out[en] = zh
    return out


def mini_yaml(text: str, *, name: str) -> dict[str, object]:
    r"""无 PyYAML 时的迷你解析：`k: v` 平表 + 一层 `k:\n  sub: v` 嵌套。

    刻意不支持 list/多行字符串/锚点——命中即报 ValueError 指到文件，
    宁可拒载也不静默读歪（术语表错了会系统性地错译）。
    """
    out: dict[str, object] = {}
    cur_key: str | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # 去行尾注释（仅在 `#` 前是空白时——`a: b#c` 的 `#` 属值的一部分）
        line = re.sub(r"\s+#.*$", "", line)
        indent = len(raw) - len(raw.lstrip())
        if ":" not in line:
            msg = f"{name}:{lineno}: unsupported yaml line: {line!r}"
            raise ValueError(msg)
        key, _, val = line.partition(":")
        key = key.strip().strip("'\"")
        val = val.strip()
        if indent == 0:
            if val == "":
                cur_key = key
                out[key] = {}
            else:
                cur_key = None
                out[key] = val.strip("'\"")
        elif cur_key is not None:
            sub_map = out.get(cur_key)
            if not isinstance(sub_map, dict):
                msg = f"{name}:{lineno}: unexpected indent: {line!r}"
                raise ValueError(msg)
            sub_map[key] = val.strip("'\"")
        else:
            msg = f"{name}:{lineno}: unexpected indent: {line!r}"
            raise ValueError(msg)
    return out
