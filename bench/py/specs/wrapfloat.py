r"""wrapfloat — wrapfig 绕排碰撞评测（``wrapfloat_bench.py`` 的 spec 化, Wave-B）。

检出语义原样平移：tectonic 编译 → ``pdftohtml -xml`` 逐页 image/text
bbox 成对交集（绝对面积 + 占小盒比双阈）→ ``pdftotext`` caption 片段
探针 → verdict。合成 fixture 字节钉死（分页可复现全靠 ``_DOC``/``_FILL``
与负 ``\vspace`` 收区 hack 逐字节保真——本文件 fixture 区禁 reformat）。

两族 item（``items()`` 零参物化）：

- **synth 族**（常驻 6 格 = 3 fixture × orig/demoted 两臂）：
  ``id="wf-{fixture}"``、``stage="wf_case"``、``arm=orig|demoted``、
  ``params={fixture,expect}``。``expect="collision"`` 的格检出碰撞才算
  ok——碰撞检出能力本身就是被测断言（2609.19101 亚型复刻）。
- **corpus 族**（``bench/nominations/wrapfloat_ids.jsonl`` 在场才枚
  举）：每格 ``stage="wf_pair"`` 单 cell 内双臂对照（原子性约束——
  needs 键钉 arm，跨 arm 依赖不可表达）。nominations 是已水化湖格
  的 wrapfig 检出清单（2026-09-23 扫 2585 complete cell 得 237；
  Wave-E 应改由 build_corpus_v3 flag 通道再生）。文件缺席时 corpus
  族自然空——synth-only spec 是合法形态。

``arm`` 轴载 orig|demoted；``variant`` 轴载测量代际：模块常量
``EPOCH`` 即 variant 值，换代重测 = bump EPOCH 出新 cell 键（内核跨
run dedup 无 --recode/--rerun——Wave-B 统一约定，同 epoch 内
dedup/resume 语义正确）。

旧 verdict 词表原样驻 ``metrics.verdict``（synth:
clean/collision/compile-fail/skip；corpus: ok/regression/en-broken/skip），
status 轴只做终态/可重试分类：

- ``wf_case``：verdict==expect→ok、≠→fail（compile-fail 计入分母）、
  demote 手术缺席→skip、基建炸（引擎/poppler/xml 缺）→error。
- ``wf_pair``：双臂 ok→ok、regression→fail、en-broken→partial（移出
  回归分母）、demote 缺席→skip、湖格不可得→skip(cell_absent)、
  copy/编译基建炸→error。

移植修正（对拍豁免项， dossier 明列）：旧码 pdftohtml 未产 xml 时
``overlaps=[]`` 静默落 clean——假阴陷阱，本版 xml 缺席→status=error。
旧码同 run 全量重测无 dedup——新码同 epoch 二次 run 全 dedup 为设计
行为，区分口径看 records.status 而非 verdict。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

from kernel import fsutil
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

ROOT = Path(__file__).resolve().parents[3]
NOMINATIONS = ROOT / "bench" / "nominations" / "wrapfloat_ids.jsonl"

#: 测量代际——variant 值本身。bump 即全族重测（dedup 键改）。
EPOCH = "v1"

WRAP_RX = re.compile(rb"\\begin\s*\{wrap(?:figure|table|float)\*?\}")

CAPTION_FRAG = "Steering along our probe direction"
#: bbox 交集阈值：绝对下限 + 占小盒面积比下限（kerning 边贴/行盒紧邻误报闸）
OVERLAP_MIN_AREA = 150.0
OVERLAP_MIN_FRAC = 0.05
_PDFTOHTML = shutil.which("pdftohtml") or "pdftohtml"
_PDFTOTEXT = shutil.which("pdftotext") or "pdftotext"

# ------------------------------------------------------------ fixture 生成（字节钉死区）

_LONG = (
    "Before applying our probes for monitoring purposes, we conduct a few analyses "
    "to better understand what the probes encode. Despite being generated on data "
    "that does not explicitly mention hacking or cheating, we find that these "
    "vectors represent these concepts coherently and consistently across a wide "
    "range of model families and training regimes. "
)
_SHORT = "我们发现这些向量连贯地表示了这些概念。 "
_FILL = (_LONG * 8) + "\n\n" + (_LONG * 8)

_DOC = r"""\documentclass{article}
\usepackage{graphicx,wrapfig,booktabs}
\begin{document}
\section{Intro}
FILLER

\begin{table}[TABLESPEC]
\centering\footnotesize
\begin{tabular}{@{}lll@{}}
\toprule
Contrast & Layer & Top-5 promoted tokens \\
\midrule
Delete failing tests & 60 & cheating, sabot, deleting \\
Exploit a fixture & 60 & cheating, cheat, disgu, hack \\
Read hidden tests & 46 & illicit, doubled, sneak \\
Honest outcome control & 44 & inconsistent, disappointing \\
Fabricate a report & 57 & joking, wrong, actually \\
Exploit a fixture & 53 & unethical, trol, dishonest \\
\bottomrule
\end{tabular}
\caption{Logit-lens readout of each probe direction.}
\label{tab:lens}
\end{table}

\subsection{Probe Vectors}
\begin{wrapfigure}{r}{0.5\textwidth}
  \centering
  \vspace{-10pt}
  \includegraphics[width=0.98\linewidth]{fig.png}
  \caption{Steering along our probe direction elicits cheating.
  We plant a honeypot and observe how often the model invokes
  the function with vs. without steering.
  \vspace{-24pt}
  }
  \label{fig:honeypot}
\end{wrapfigure}
PARAS
\end{document}
"""

#: fixture 名 → (table 浮体位, 绕排后段落体, 期望 verdict)。分母子口径——
#: 三格期望分布 = 旧 cases 矩阵的 [collision, collision, clean]。
_SYNTH = {
    "tableB_short": ("b", _SHORT * 4, "collision"),
    "tableB_long": ("b", _LONG * 45, "collision"),
    "tableT_long": ("t", _LONG * 45, "clean"),
}


def _png(path: Path, w: int = 400, h: int = 300, rgb=(70, 110, 180)) -> None:
    """stdlib PNG（蓝块占位图——includegraphics 的 raster 载荷）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        head = struct.pack(">I", len(data)) + tag + data
        return head + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(blob)


def synth_doc(table_spec: str, paras: str) -> str:
    return (
        _DOC.replace("TABLESPEC", table_spec)
        .replace("FILLER", _FILL)
        .replace("PARAS", paras)
    )


# ------------------------------------------------------------ 检出（原样平移）


def _boxes(xml_path: Path) -> list[dict]:
    """pdftohtml -xml → 逐页 image/text bbox 平铺 [{page,kind,top,left,w,h}]。"""
    import xml.etree.ElementTree as ET

    boxes: list[dict] = []
    root = ET.parse(xml_path).getroot()  # noqa: S314 — pdftohtml 自产 XML 非不可信输入
    for page in root.iter("page"):
        pno = int(page.get("number", "0"))
        for el in page:
            if el.tag not in ("image", "text"):
                continue
            boxes.append(
                {
                    "page": pno,
                    "kind": el.tag,
                    "top": float(el.get("top", "0")),
                    "left": float(el.get("left", "0")),
                    "w": float(el.get("width", "0")),
                    "h": float(el.get("height", "0")),
                }
            )
    return boxes


def _inter(a: dict, b: dict) -> float:
    x = min(a["left"] + a["w"], b["left"] + b["w"]) - max(a["left"], b["left"])
    y = min(a["top"] + a["h"], b["top"] + b["h"]) - max(a["top"], b["top"])
    return x * y if x > 0 and y > 0 else 0.0


def detect_overlap(xml_path: Path) -> list[dict]:
    """image∩text + text∩text 超阈交集对清单（命中即重叠排版）。"""
    boxes = _boxes(xml_path)
    hits: list[dict] = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a["page"] != b["page"]:
                continue
            if a["kind"] == "image" and b["kind"] == "image":
                continue
            area = _inter(a, b)
            small = min(a["w"] * a["h"], b["w"] * b["h"]) or 1.0
            if area > OVERLAP_MIN_AREA and area / small > OVERLAP_MIN_FRAC:
                pair = f"{a['kind']}∩{b['kind']}"
                hits.append({"page": a["page"], "pair": pair, "area": round(area)})
    return hits


def caption_present(pdf: Path, frag: str) -> bool:
    out = subprocess.run(
        [_PDFTOTEXT, str(pdf), "-"], capture_output=True, text=True
    ).stdout
    return frag in re.sub(r"\s+", " ", out)


# ------------------------------------------------------------ 编译臂


def _engine():
    from texlate.compile.engine import engine_for

    return engine_for("tectonic")


def _demote(root: Path) -> int | None:
    """lazy-import zh 侧降级手术——函数缺席（fix 未落）返 None 记 skip。"""
    try:
        from texlate.compile.inject import demote_wrapfloats
    except ImportError:
        return None
    return demote_wrapfloats(root)


def _find_main(root: Path) -> str:
    from texlate.compile.inject import find_main_tex

    m = find_main_tex(root)
    return m.relative_to(root).as_posix() if m else "main.tex"


def _detect(case_dir: Path, pdf: Path) -> dict:
    """pdftohtml+xml 检出段——xml 缺席是基建故障（旧码静默 clean 假阴已修）。"""
    xml_prefix = case_dir / "xml"
    subprocess.run(
        [_PDFTOHTML, "-xml", "-nodrm", str(pdf), str(xml_prefix)],
        capture_output=True,
        cwd=case_dir,
    )
    xml = xml_prefix.with_suffix(".xml")
    if not xml.exists():
        return {"infra_error": "pdftohtml produced no xml"}
    return {
        "overlaps": detect_overlap(xml),
        "caption_present": caption_present(pdf, CAPTION_FRAG),
    }


# ------------------------------------------------------------ items / select


def _items() -> list[dict]:
    """synth 常驻 6 格 + nominations 湖格族（文件缺席=语料族空）。

    synth ``fp_input`` = 钉死 fixture 字节 sha——fixture 任何改动（含
    空白）换指纹标 stale；corpus ``fp_input`` = 生成期全树内容 sha
    （nominations 文件行自带，湖字节漂移由 eviction/重写自然反映）。
    """
    items: list[dict] = []
    for name, (tspec, paras, expect) in _SYNTH.items():
        tex = synth_doc(tspec, paras)
        fp = hashlib.sha256(tex.encode("utf-8")).hexdigest()[:16]
        items.extend(
            {
                "id": f"wf-{name}",
                "stage": "wf_case",
                "arm": arm,
                "variant": EPOCH,
                "fp_input": fp,
                # 期望随 (fixture,arm) 逐格定：orig 臂吃 _SYNTH 期望，
                # demoted 臂恒期望 clean（降级手术的本职断言）。
                "params": {
                    "fixture": name,
                    "expect": "clean" if arm == "demoted" else expect,
                },
            }
            for arm in ("orig", "demoted")
        )
    if NOMINATIONS.is_file():
        try:
            for raw_line in NOMINATIONS.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line) if line.startswith("{") else {"id": line}
                pid = str(row.get("id") or "").strip()
                if not pid:
                    continue
                items.append(
                    {
                        "id": pid,
                        "stage": "wf_pair",
                        "variant": EPOCH,
                        "fp_input": row.get("fp_input"),
                    }
                )
        except (OSError, ValueError):
            pass  # 坏清单 = 空语料族——synth 族不受影响
    return items


def _corpus_sample(ids: list[str], n: int, seed: int) -> set[str]:
    """corpus 族 seeded 抽 n（benchlib.pick_sample 同口径：排序池 + Random 抽）。"""
    pool = sorted(set(ids))
    rng = random.Random(seed)
    return set(rng.sample(pool, min(n, len(pool))))


def _select(item: dict, rp: dict) -> bool:
    """ids 直选（两族通吃，bypass n）→ synth 族 fixture/only 过滤 →
    corpus 族 n>0 才入场（旧 --corpus 缺省 0 = synth-only 的口径守恒）。"""
    ids_p = str(rp.get("ids") or "").strip()
    raw = str(item.get("id") or "")
    if ids_p:
        want = {t.strip() for t in ids_p.split(",") if t.strip()}
        return raw in want
    if item.get("stage") == "wf_case":
        fixture = str(rp.get("fixture") or "").strip()
        if fixture and str(item.get("params", {}).get("fixture")) != fixture:
            return False
        only = str(rp.get("only") or "").strip()
        return not only or only in raw
    # wf_pair：corpus 族须 n>0 显式开门（237 格双臂编译非默认面）
    only = str(rp.get("only") or "").strip()
    if only and only not in raw:
        return False
    n = int(rp.get("n") or 0)
    if n <= 0:
        return False
    seed = int(rp.get("seed") or 20260919)
    pool = _corpus_pool()
    return raw in _corpus_sample(pool, n, seed)


_CORPUS_POOL: list[str] | None = None


def _corpus_pool() -> list[str]:
    """nominations idc 清单（惰性物化一次——select 逐格调用不能每格重读盘）。"""
    global _CORPUS_POOL  # noqa: PLW0603
    if _CORPUS_POOL is None:
        _CORPUS_POOL = sorted(
            str(i["id"]) for i in _items() if i.get("stage") == "wf_pair"
        )
    return _CORPUS_POOL


# ------------------------------------------------------------ stage: wf_case


def _wf_case(ctx) -> dict:
    """单臂合成格：落 tex+png →（demoted 臂手术）→ tectonic → 三件套检出。"""
    fixture = str(ctx.params.get("fixture") or "")
    expect = str(ctx.params.get("expect") or "")
    entry = _SYNTH.get(fixture)
    if entry is None:
        return {
            "status": "fail",
            "errors": [{"cat": "fixture", "msg": f"unknown fixture {fixture!r}"}],
            "metrics": {"verdict": "compile-fail", "expect": expect},
        }
    demote = ctx.arm == "demoted"
    tex = synth_doc(entry[0], entry[1])
    case_dir = ctx.workspace() / ctx.arm
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    (case_dir / "main.tex").write_text(tex, encoding="utf-8")
    _png(case_dir / "fig.png")

    metrics: dict = {"fixture": fixture, "expect": expect, "demoted": demote}
    if demote:
        n = _demote(case_dir)
        metrics["demote_n"] = n
        if n is None:
            metrics["verdict"] = "skip"
            return {
                "status": "skip",
                "metrics": metrics,
                "errors": [
                    {"cat": "demote_absent", "msg": "demote_wrapfloats not available"}
                ],
            }
        metrics["still_wrapfig"] = bool(
            WRAP_RX.search((case_dir / "main.tex").read_bytes())
        )

    eng = _engine()
    res = eng.compile(case_dir, "main.tex", timeout=240, sandbox=False)
    metrics["compile_ok"] = bool(res.ok and res.pdf)
    if not metrics["compile_ok"]:
        metrics["verdict"] = "compile-fail"
        metrics["note"] = (res.stdout_tail or "")[-200:]
        return {"status": "fail", "metrics": metrics}

    det = _detect(case_dir, res.pdf)
    if "infra_error" in det:
        return {
            "status": "error",
            "metrics": metrics,
            "errors": [{"cat": "infra", "msg": det["infra_error"]}],
        }
    metrics["overlaps"] = det["overlaps"]
    metrics["caption_present"] = det["caption_present"]
    metrics["verdict"] = (
        "collision" if (det["overlaps"] or not det["caption_present"]) else "clean"
    )
    return {
        "status": "ok" if metrics["verdict"] == expect else "fail",
        "metrics": metrics,
    }


# ------------------------------------------------------------ stage: wf_pair


def _wf_pair(ctx) -> dict:
    """真实论文双臂回归：orig 能编 ∧ demoted 挂 = regression（fail）。"""
    src = ctx.src_path()
    if src is None:
        return {
            "status": "skip",
            "errors": [{"cat": "cell_absent", "msg": "lake cannot provide cell bytes"}],
            "metrics": {"verdict": "skip", "reason": "cell_absent"},
        }
    ws = ctx.workspace()
    metrics: dict = {"verdict": None}
    for arm in ("orig", "demoted"):
        dest = ws / arm
        if dest.exists():
            shutil.rmtree(dest)
        try:
            fsutil.copy_mutating(src, dest)  # 剥 0444——mutating 树必须可写
        except OSError as exc:
            return {
                "status": "error",
                "metrics": metrics,
                "errors": [{"cat": "infra", "msg": f"copy_mutating {arm}: {exc}"}],
            }
        if arm == "demoted":
            n = _demote(dest)
            metrics["demote_n"] = n
            if n is None:
                metrics["verdict"] = "skip"
                return {
                    "status": "skip",
                    "metrics": metrics,
                    "errors": [
                        {
                            "cat": "demote_absent",
                            "msg": "demote_wrapfloats not available",
                        }
                    ],
                }
        main_rel = _find_main(dest)
        eng = _engine()
        try:
            res = eng.compile(dest, main_rel, timeout=240, sandbox=False)
        except Exception as exc:  # 引擎层异常=基建故障非论文回归
            return {
                "status": "error",
                "metrics": metrics,
                "errors": [{"cat": "infra", "msg": f"compile {arm} raised {exc!r}"}],
            }
        metrics[arm] = {
            "ok": bool(res.ok and res.pdf),
            "demote_n": metrics.get("demote_n", 0),
        }
    if not metrics["orig"]["ok"]:
        metrics["verdict"] = "en-broken"
        status = "partial"
    elif not metrics["demoted"]["ok"]:
        metrics["verdict"] = "regression"
        status = "fail"
    else:
        metrics["verdict"] = "ok"
        status = "ok"
    return {"status": status, "metrics": metrics}


# ------------------------------------------------------------ spec


spec = Spec(
    kind="wrapfloat",
    params={
        "ids": Param(type=str, default="", fp=False),
        "only": Param(type=str, default="", fp=False),
        "fixture": Param(type=str, default="", fp=False),
        "n": Param(type=int, default=0),
        "seed": Param(type=int, default=20260919),
    },
    items=_items,
    select=_select,
    stages=[
        Stage(
            "wf_case",
            _wf_case,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
            eval=True,
        ),
        Stage(
            "wf_pair",
            _wf_pair,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "partial": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
            eval=True,
        ),
    ],
    eval=True,
    lake=True,
    env_probes=["python", "tectonic", "xelatex", "pdftohtml", "pdftotext"],
    code_deps=[
        "src/texlate/compile/inject.py",
        "src/texlate/compile/layout.py",
        "src/texlate/compile/mainfile.py",
        "src/texlate/compile/engine",
    ],
)
