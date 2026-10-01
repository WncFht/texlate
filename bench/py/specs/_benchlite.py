"""benchlib 遗孤收编——benchlib.py 已随删除门退役。

spec 侧通用件单源（verbs 侧对应物是 ``verbs/_vocab.py``——两叶互不
依赖；跨叶共享的状态词表两叶同引 ``kernel.events`` 单源别名）。
jsonl 三件 + ``strip_comments`` 此前在 benchlib 与
``_corpus_common`` 双份 verbatim——本叶收编为正本，
``_corpus_common`` 改作 re-export 转发。

逐字 lift 区（benchlib 原行）：TUNA_TLNET、_IGNORE_BASE/copytree_ignore、
fixloop_attr、fixloop_sig、_strkey/compile_fp、judge_dict/_fixloop_rs/
_taxonomy_of、verdict_sig、MAX_TOTAL_CHARS、misschar_partial——口径/
判决逻辑零改写。STATUS_RANK/TERMINAL_WORDS 转 kernel.events 别名。
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from kernel import events

try:
    import fcntl
except ImportError:  # 无 fcntl 平台 → append_jsonl 退化为无锁
    fcntl = None  # type: ignore[assignment]

TUNA_TLNET = "https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet"

#: copytree 进工作区时剔除的编译副产物/平台垃圾（compilebench_v2/v3、
#: fixloop_bench 三处同源；v3 另剔 "_texmf" 冷 usertree 残留）。
_IGNORE_BASE = (
    "_tect_out",
    "*.aux",
    "*.log",
    "*.out",
    "*.toc",
    "*.lof",
    "*.lot",
    "*.fls",
    "*.fdb_latexmk",
    "*.synctex*",
    "*.blg",
    "texput.*",
    "missfont.log",
    ".DS_Store",
    "__pycache__",
)


def copytree_ignore(*extra: str):
    """编译工作区 copytree 的 ignore 回调；``extra`` 追加库级剔除项。"""
    return shutil.ignore_patterns(*_IGNORE_BASE, *extra)


# ---------------------------------------------------------------- jsonl / 文件 IO
def iter_jsonl(path: Path, *, on_bad="skip", errors: str = "replace"):
    """逐行 yield 解析值；空行跳过，坏 json 行按 ``on_bad`` 处置。

    append 账的 kill 截尾是常态——容忍坏行保住续跑。``on_bad``：
    ``"skip"`` 静默跳（默认）；``"warn"`` 读完向 stderr 汇总一行
    （triage 口径）；callable 逐坏行回调 ``on_bad(raw_line, exc)``。
    ``errors`` 透传 decode——默认 ``"replace"`` 截尾多字节留 U+FFFD
    → 坏行按 ``on_bad`` 跳；``"strict"`` 炸 UnicodeDecodeError（需硬
    失败口径的调用方自钉）。
    """
    bad = 0
    for raw in path.read_text(encoding="utf-8", errors=errors).splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as e:
            bad += 1
            if callable(on_bad):
                on_bad(raw, e)
    if bad and on_bad == "warn":
        print(f"  warn: {path.name} 跳过 {bad} 行坏 json", file=sys.stderr)


def read_jsonl(path: Path) -> list[dict]:
    """jsonl → list[dict]（不存在 → 空表）。"""
    return list(iter_jsonl(path)) if path.exists() else []


def write_jsonl(fh, rec: dict) -> None:
    """持有句柄上写一行 + flush（per-item 落盘粒度）。"""
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()


def append_jsonl(path: Path, rec: dict) -> None:
    """一次性 open-append-close（无长驻句柄的调用点用）；父目录缺席自建。

    写临界区经 ``flock`` 串行化——bench 并行/多 worker 共享同一账文件时
    防行交错；无 fcntl 平台退化为无锁。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def strip_comments(tex: str) -> str:
    r"""去注释：``\X`` 先吃两字符，裸 ``%`` 删到行尾（保留换行）。

    verbatim 内 ``%`` 误剥是既有口径（仅用于主文件定位/路由标签场景），
    勿擅加 verbatim 感知。"""
    out, i, n = [], 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            out.append(tex[i : i + 2])
            i += 2
            continue
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                break
            out.append("\n")
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 状态词汇
#: 单源 kernel/events.py——verbs._vocab 同引同名别名，两叶防漂移。
TERMINAL_WORDS = events.TERMINAL_WORDS
STATUS_RANK = events.STATUS_RANK


def fixloop_attr(rounds, fv=None, final_cat=None):
    """fixloop 归因 (cat, pay) = verdict 所结算的末个正规轮。

    salvage 哨兵 (``"salvage": true``；旧 schema 无标——尾巴 cat 空且
    verdict 非 clean 系即哨兵，因 clean/no_errors_no_pdf 之外的 verdict
    只在非空 cat 轮结算) 不占归因槽。末轮 pay 空不回填旧轮——回填会把
    已修轮的签名贴上来 (2609.19664: r2 latin 已装，r3-r5 ``other:None``
    streak 触 stuck, 回填 latin 成 ``stuck:latin`` 误桶)。
    """
    rds = [rd for rd in (rounds or []) if isinstance(rd, dict)]
    last = rds[-1] if rds else {}
    if len(rds) > 1 and (
        last.get("salvage")
        or (
            not (last.get("category") or last.get("cat"))
            and str(fv or "") not in {"clean", "no_errors_no_pdf"}
        )
    ):
        last = rds[-2]
    fcat = last.get("category") or last.get("cat") or final_cat
    fpay = last.get("pay") or last.get("payload") or ""
    return fcat, fpay


def fixloop_sig(fv, fcat=None, fpay=None) -> str:
    """fixloop verdict → 记录 sig：裸 ``unfixable:``/终态词补 final_cat，
    再拼归因轮 payload（fcat/fpay 口径 ``fixloop_attr``）。"""
    sig = str(fv)
    if sig.startswith("unfixable:"):
        if fcat and str(fcat) not in sig:
            sig = f"{sig}:{fcat}"
    elif sig in TERMINAL_WORDS and fcat:
        # stuck streak 签 {cat}:{pay} 的头半——cat 进桶键分 stuck 机制面
        sig = f"{sig}:{fcat}"
    if fpay:
        sig = f"{sig}:{fpay}"
    return sig


# ---------------------------------------------------------------- 记录指纹
def _strkey(d):
    """dict 键一律 str 化——混合类型键下 ``sort_keys`` 排序即 TypeError。"""
    return {str(k): v for k, v in d.items()} if isinstance(d, dict) else d


def compile_fp(c: dict) -> str:
    """compile 记录身份指纹（sha256[:16]）——verdict 决定字段的稳定摘要。

    fixloop 记录新鲜度校验的比对料单源：写侧落 ``metrics.compile_fp``，
    读侧 ``verbs.gate.pick_final`` 比对——compile 重跑 status 不变但
    sig/first_error 已换（同态陈旧）时，``compile_status_before`` 状态
    等值放行、指纹不等即拦。计时字段（seconds/dur_s）不入——逐跑恒变
    而非 verdict 语义。
    """
    m = c.get("metrics")
    if not isinstance(m, dict):
        m = {}
    comp = m.get("compile")
    if not isinstance(comp, dict):
        comp = {}
    v = m.get("verdict")
    if not isinstance(v, dict):
        v = {}
    blob = json.dumps(
        [
            c.get("status"),
            c.get("sig"),
            c.get("code"),
            comp.get("first_error"),
            v.get("category"),
            v.get("payload"),
            _strkey(v.get("error_cats")),
            _strkey(m.get("taxonomy")),
        ],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 编译判决
def judge_dict(res, *, expect_cjk: bool) -> dict:
    """CompileResult → {compile, verdict, status, l2_attr, taxonomy}——
    ``texlate.pipecore.tail.compile_judge_tail`` 同形状（bench 侧复刻点
    收敛：e2e_real/e2e_mock 共用）。

    ``l2_attr`` = L2 log 归因载荷（canonical 键——``L2Verdict.attribution_dict``
    单源：逐条 ``{kind,file,line,head,log_line}`` hits + ``warn_by_class``），
    落 ``metrics.l2_attr`` / fixloop post 落 ``metrics.post.l2_attr``，
    供 records 离线按类聚类 warning/error。

    ``taxonomy`` = fixloop 内部分类器对本次编译 log 的二级分类
    ``{cat, pay}``（M1 物化，still-manual-audit-2026-09-17）——records 侧
    聚合桶 (other/errors>3/syntax) 由 dossier/triage 直读细分。
    """
    from texlate.compile.judge import judge
    from texlate.repair_l2 import _l2_parse

    v = judge(res, expect_cjk=expect_cjk)
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "killed_signal": res.killed_signal,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "notes": v.notes,
            "n_errors": v.n_errors,
            "category": v.category,
            "payload": v.payload,
            "error_cats": v.error_cats,
            "error_pay": v.error_pay,
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
            "warnings_hit": v.warnings_hit,
        },
        "status": v.status,
        "l2_attr": _l2_parse(res).attribution_dict(),
        "taxonomy": _taxonomy_of(res),
    }


@functools.lru_cache(maxsize=1)
def _fixloop_rs():
    """fixloop Ruleset 懒载单例——taxonomy 物化逐格调，yaml 只解一次。"""
    from texlate.compile.fixloop import Ruleset

    return Ruleset.load()


def _taxonomy_of(res) -> dict:
    """CompileResult → fixloop taxonomy ``{cat, pay}`` (first_error 二级类)。"""
    try:
        from texlate.compile.fixloop.engine import _report_of

        rs = _fixloop_rs()
        rep = _report_of(res, rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(
            rep, timed_out=bool(getattr(res, "timed_out", False))
        )
    except Exception:
        return {"cat": None, "pay": None}  # advisory 字段——分类故障不毁卷宗
    return {"cat": cat, "pay": pay}


_RE_MISSING_FILE = re.compile(r"File `([^']+)' not found")
_RE_MISSING_CHAR = re.compile(r"missing_character[×x](\d+)")


def verdict_sig(verdict: dict, first_error: str | None = None) -> str:
    """compile verdict 块 → 聚类 sig（records 与 triage legacy 降级单源）。

    cat 以 ``verdict.category`` 为准——此时 ``verdict.payload`` 是同字段对配，
    直接拼。cat 模糊（None/clean/other）时退 reasons 头抠 cat；派生 cat 不拼
    ``verdict.payload``（它配的是原 cat，拼上即错配），missing_file /
    missing_character 走正则从 first_error/reasons 回补 payload。

    ``error_cats``（judge 逐错误行构成）在场且众数 cat 错误量**严格大于**
    首错 cat 时 sig 改挂众数——首错遮 bulk 纠偏（quant-ph/9703040:110 错
    108×syntax，category 却是自恢复的 illegal_unit）；平票仍归
    首错（TeX 级联中首错是因果上游）。众数 payload 取 ``error_pay`` 首见值。
    cat 不在构成中（derived meta 词 killed_by_signal/no_pdf 等 verdict 级
    归因）不比众数——构成外恒 0 票会被任意众数顶包洗掉根因。

    裁决 2026-09-17（overseer）：sig 只担 dominant-error 分桶——missing_char
    等 warning 派生信号不并入（混进 error sig 是 phantom-payload 类 bug 温床）；
    misschar 检索走 ``verdict.missing_chars`` / ``warn:missing_chars`` reason。
    """
    vstatus = verdict.get("status")
    if vstatus in ("clean", None):
        return ""
    fe = first_error if isinstance(first_error, str) else ""
    cat = verdict.get("category")
    raw = verdict.get("reasons")
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = []
    reasons = [str(r).strip() for r in raw if str(r).strip()]
    derived = cat in (None, "clean", "other")
    if derived:
        if any(r.startswith("missing_character") for r in reasons):
            cat = "missing_character"
        elif reasons:
            head = reasons[0]
            cat = (
                head.split("=", 1)[1].split(":")[0]
                if head.startswith("first_error=")
                else head.split()[0]
            )
    if not cat:
        return f"verdict:{vstatus}"
    pay = None if derived else verdict.get("payload")
    if not pay:
        if cat == "missing_file":
            m = _RE_MISSING_FILE.search(fe)
            pay = m.group(1) if m else ""
        elif cat == "missing_character":
            m = _RE_MISSING_CHAR.search(" ".join(reasons))
            pay = f"x{m.group(1)}" if m else ""
    cats = verdict.get("error_cats")
    if isinstance(cats, dict):
        bulk = {
            k: n
            for k, n in cats.items()
            if isinstance(k, str)
            and isinstance(n, int)
            and not isinstance(n, bool)
            and n > 0
        }
        dom = max(bulk, key=bulk.get) if bulk else None
        # 构成外 cat（derived meta 词：killed_by_signal/no_pdf/missing_character
        # 等 verdict 级归因）bulk.get 恒 0，不拦则任意众数顶包洗掉根因——只有
        # cat 真在错误行构成中才比（derived first_error=X 的 X 照常参与）。
        if dom is not None and cat in bulk and dom != cat and bulk[dom] > bulk[cat]:
            pays = verdict.get("error_pay")
            dpay = pays.get(dom) if isinstance(pays, dict) else None
            return f"{dom}:{dpay if isinstance(dpay, str) else ''}".rstrip(":")
    return f"{cat}:{pay or ''}".rstrip(":")


MAX_TOTAL_CHARS = 250_000


def misschar_partial(status, verdict: dict) -> bool:
    """缺字窄口：``partial`` ∧ ``missing_chars>0`` —— missing_char_fix 可修子集。

    misschar 判定单源；其余 warning 级 partial 不进 fixloop（partial→fail
    回退教训——fixloop 的 halt_on_error 编译只会丢已有 PDF）。
    """
    return status == "partial" and (verdict.get("missing_chars") or 0) > 0


# ---------------------------------------------------------------- 启动/抓取小件
# （iclr/ 包 defer 六件的 benchlib 存活面——与 benchlib 逐字同形）
def log(msg: str) -> None:
    """stderr 时间戳日志行——脱管批（setsid nohup + run.log）共用形。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


#: paper-search skill 的 ``.env``——OpenAlex/OpenReview 凭据读取口径
#: （iclr.map/iclr.pdf 原各拷一份）。
ENV_FP = Path.home() / ".claude/skills/paper-search/.env"


def load_env(path: Path = ENV_FP) -> dict[str, str]:
    """``.env`` → dict：``K=V`` 行切首等号，无 ``=`` 行跳过。"""
    return dict(
        ln.strip().split("=", 1) for ln in path.read_text().splitlines() if "=" in ln
    )


def rss_preflight(ua: dict[str, str], feed: str = "cs.CL") -> None:
    """rss.arxiv.org 健康探针——不通 ``sys.exit(3)`` 中止，不进 fetch 烧预算。

    iclr.fetch.preflight 同型下沉（原型为已退役 daily_arxiv.preflight）：
    urllib 30s 一发 + ``<rss`` 魔数校验（代理截获会返非 RSS 登录页，
    净连但语义无货同拦）。
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"https://rss.arxiv.org/rss/{feed}", headers=ua)
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 固定 https 端点
            body = r.read(400)
    except (urllib.error.URLError, OSError) as e:
        log(f"preflight FAILED: rss.arxiv.org unreachable ({e}) — 检查代理")
        sys.exit(3)
    if b"<rss" not in body[:400]:
        log("preflight FAILED: rss.arxiv.org 返回非 RSS——检查代理")
        sys.exit(3)


def fetch_done(status_fp: Path, *, id_key: str = "id") -> dict[str, str]:
    """fetch 状态账 jsonl → ``{id: 末条 status}``（仅终态行）——续跑跳过单源。

    iclr.fetch._fetch_done 同型下沉（原型为已退役 daily_arxiv._fetch_done）。
    终态集 =
    ``AcquireStatus`` 的成功/不可修类（error/budget/parked 留可重试）。
    ``id_key`` 适配异名账键（iclr.fetch 账用 ``arxiv_id``）。
    """
    from texlate.arxiv.fetch import AcquireStatus  # 迟绑——模块级零 texlate 约束

    terminal = {
        AcquireStatus.OK.value,
        AcquireStatus.PDF_ONLY.value,
        AcquireStatus.UNKNOWN_FORMAT.value,
        AcquireStatus.NOT_FOUND.value,
        AcquireStatus.TOO_LARGE.value,
        AcquireStatus.UNPACK_ERROR.value,
    }
    done: dict[str, str] = {}
    if not status_fp.exists():
        return done
    for r in iter_jsonl(status_fp):
        if isinstance(r, dict) and r.get(id_key):
            done[str(r[id_key])] = str(r.get("status"))
    return {k: v for k, v in done.items() if v in terminal}


def materialize_entry(entry_dir: Path, dst: Path) -> None:
    """fetch 缓存条目 → ``corpus/{id}``：rmtree 旧树 + copytree ``os.link``。

    硬链接而非拷贝——缓存条目即语料内容，双视图零额外空间；缓存清理后
    语料仍持有数据（原型为已退役 daily_arxiv._materialize；iclr.fetch
    复制时丢落 ``copy_function`` 属回归——此处复原同口径）。
    """
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(entry_dir, dst, copy_function=os.link)
