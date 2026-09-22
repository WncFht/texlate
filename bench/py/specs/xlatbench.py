"""xlatbench — B4a 翻译硬契约回归 (kernel spec port, eval-paid lane).

对 devin-2api 网关模型集跑分层抽样 LaTeX 段中译，格内过 l0 validator +
E22 硬契约判定，逐格落 metrics。旧驱动的 report/rejudge/samples 三子命令
是读 eval_records 的分析动词（Wave-D 边界），不在本 spec。

样例帧（spec 常量 = bench 定义本身——旧 --where/--docs/--per-kind/--seed/
--models/--runs 沉为模块常量，items() 零参在 spec load 物化，run params
不可达；改常量=改 bench 定义，code_sha/spec_hash 自动换版）:

  非 holdout 切片 union（行记 _slice、canon 去重；holdout=留出评测层
  不进回归烧录面）× WHERE 等值过滤 → 湖格 eligible 预过滤（is_complete
  ∨ raw 层在——旧世界 "manifest ∩ 已物化 corpus 目录" 的湖版等价；
  skeleton 永不产样，不占轮转槽）→ 切片:簇轮转取 DOCS 篇（SEED 定簇
  内序；m1k 切片无簇字段时 cat_group 兜底分层）→ lake.hydrate
  (fetch_fn=None：hydrated 直用、raw_only 免费重抽——湖外抓取归
  corpus builder，非 spec 职责)
  → locate 主 tex → parse_file 切块 → 300≤len≤1200 ∧ 含占位符 → kind 分桶
    等距取 PER_KIND 个 → 尾部挂 S1–S4 合成压力样（与 xlat-traps.tex @Xn
    byte-exact，_fixture_matrix.assert_xlat 钉死）。
  items = samples × MODELS × REPS：id=样例名，arm=模型，variant=r{n}@EPOCH，
  fp_input=sha256(src)。帧=湖化人口（deliberate delta：旧 corpus 目录
  是静态物化；湖水位升则帧自动扩）。

付费格（attempted-unpaid 铁律）:
  测量落地行恒 ok|partial——契约败是 metrics.hard_ok=False 的数据不是格态；
  映成 fail/reject 会让 oracle 判 absent 下个 run 静默重烧（paid stage 跳过
  done 检查腿）。http≠200/空正文/异常 → error（retriable，resume 重烧——
  等价旧 resume 谓词 http==200∧content）。dedup_key=(idc,arm,variant)
  显式声明（paid stage 编译闸；同 (sample,model,rep) 键跨 run dedup——旧
  --runs 每 run 全烧，新世界命中格只烧缺失 rep）。

线桥（eval 纯度）:
  session.request(_wire_call) 直驱 GatewayChat 泵上的 ChatClient._chat_once
  ——chat() 的免费集降级臂整段绕过：429/5xx 换模型是评测毒化，而本网关
  loopback 恰落在 is_free_gateway_url 发现面内，降级臂不是惰性默认。唯一
  保留的补发是 _stream_rescuable 时 _chat_via_stream（2026-09-19 非流式
  全模型 502、stream 独活的事故形），via_stream=True 记 metrics；模型永不换。
  格内重试逐字平移：429 → ≤3 次 gap*2^(n+1) 退避（retry_429）；finish=length
  ∧ 空正文 → 单次 retry_max_tokens 重试（retried_32k）；length 带正文 →
  旧口径测量行（截断译文照样判）。例外路径首请求用量不进 meter（内核设计：
  异常不载 usage）——unmetered=True 标记。
"""
from __future__ import annotations

import hashlib
import random
import re
import sys
import time
from pathlib import Path

import benchlib
import httpx
from kernel import idnorm, lake
from kernel import paid as paidmod
from kernel.spec import Param, Spec, Stage

from specs._shared import devin_factory
from texlate.arxiv.locate import locate
from texlate.latex import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.validate.l0 import (
    FRAGILE_BS,
    FRAGILE_CHARS,
    Severity,
    validate_pair,
)
from texlate.xlat._dialects import ChatOptions
from texlate.xlat._errors import (
    ChatError,
    LengthTruncatedError,
    _stream_rescuable,
)

REPO = Path(__file__).resolve().parents[3]

EPOCH = "v1"

# --- spec 常量（bench 定义本体；旧 CLI 采样/模型旋钮沉这里） ---------------------

# 样例池 = 非 holdout 全部语料切片的 union（holdout=留出评测层，不进
# 回归烧录面）；eligible 预过滤后进轮转，明细见 _load_manifests/_eligible。
MANIFESTS = [
    REPO / "bench" / "corpus" / "manifest.jsonl",
    REPO / "bench" / "corpus" / "manifest_dev_recent.jsonl",
    REPO / "bench" / "corpus" / "manifest_hot.jsonl",
    REPO / "bench" / "corpus" / "manifest_m1k-axhot.jsonl",
    REPO / "bench" / "corpus" / "manifest_m1k-iclr.jsonl",
    REPO / "bench" / "corpus" / "manifest_m1k-recent.jsonl",
]
WHERE: dict = {}               # 行级等值过滤（旧 --where k=v；{}=union 全量）
DOCS = 24                      # cluster 轮转取篇上限（旧 --docs；0=过滤后全部）
PER_KIND = 8                   # 每 context-kind 等距抽样上限（旧 --per-kind）
SEED = 0                       # 簇内选篇种子（旧 --seed）
SAMPLES_LIMIT = 0              # 总样例上限（旧 --samples；0=不限，只砍 real）
MODELS = ["swe-2-medium"]      # 旧 --models；加臂=spec 编辑=新版本
REPS = 2                       # 旧 --runs

GAP_S = 1.0
TIMEOUT_S = 240
MAX_TOKENS = 8192
RETRY_MAX_TOKENS = 32768
TEMPERATURE = 0.2

SYSTEM = (
    "You are a LaTeX academic translator. Translate prose to Chinese. "
    "Tokens like [[MATH_1]] are opaque placeholders — keep them verbatim "
    "in output, never translate or invent new ones. Preserve all LaTeX "
    "commands. Output only the translation."
)
PROMPT_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]

# 脆弱命令字符级投影——判定同源 l0.FRAGILE_BS|FRAGILE_CHARS；逐 token 丢失
# 以 rep.issues 为准（judge），本计数仅展示旁证（\<newline>/\<tab> 归一差）。
FRAGILE_CS_RX = re.compile(
    "|".join(re.escape(t) for t in sorted(FRAGILE_BS | FRAGILE_CHARS))
)
EN_WORD_RX = re.compile(r"[A-Za-z]{4,}")
CS_RX = re.compile(r"\\[a-zA-Z]+")

# 合成压力样例：与 bench/fixtures/xlat-traps.tex @X1–@X4 遮蔽输出逐字一致，
# specs._fixture_matrix.assert_xlat 钉住产品口径；改任一边先跑该测试对拍。
SYNTHETIC = [
    {
        "name": "S1-bibitem-lead",
        "src": (
            "[[BIB_1]] Vaswani et al.\\ \\href[[HREF_2]]{introduced the "
            "Transformer}, demonstrating that attention alone suffices when "
            "the hidden dimension satisfies [[MATH_3]]; earlier work by "
            "Bahdanau, Cho, and Bengio [[CITE_4]] and the survey of Luong "
            "and Manning [[CITE_5]] had already hinted at this."
        ),
    },
    {
        "name": "S2-multikey-cite",
        "src": (
            "Subsequent analyses [[CITE_6]] refined this bound using "
            "[[MATH_7]] and argued, following the framework of [[CITE_8]], "
            "that the variance term dominates in the small-sample regime "
            "[[MATH_9]]."
        ),
    },
    {
        "name": "S3-verbatim-pct",
        "src": (
            "The implementation is available at [[URL_10]] and reproduces "
            "the baseline of [[CITE_11]] within [[MATH_12]] relative error, "
            "using the estimator described in [[REF_13]]."
        ),
    },
    {
        "name": "S4-dense-math",
        "src": (
            "Setting [[MATH_14]] yields [[MATH_15]], and substituting "
            "[[MATH_16]] into [[MATH_17]] gives the desired contraction "
            "whenever [[MATH_18]] holds [[CITE_19]]."
        ),
    },
]


# --- 样例帧（items() 零参，spec load 物化） --------------------------------------


def _load_manifests(paths: list[Path], where: dict) -> list[dict]:
    """切片 union → doc 行：``_slice`` 记源、``_idc`` 记 canon，canon 去重。

    ``where`` 逐项等值过滤（值一律按 str 比）。同一篇跨切片重复时首见
    胜（MANIFESTS 序即优先序）——不去重则同 doc 进多个轮转池可被重复
    选中，样例名 ``raw#i`` 撞键。
    """
    docs: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            # 缺席切片静默给空池会把帧退化仍出完整报告——喊出来。
            print(f"  [warn] manifest {path} 不存在——跳过该切片", file=sys.stderr)
            continue
        tag = path.stem.removeprefix("manifest_")
        if tag == "manifest":
            tag = "core"
        for d in benchlib.read_jsonl(path):
            if any(str(d.get(k)) != v for k, v in where.items()):
                continue
            raw = str(d.get("id") or "")
            cres = idnorm.canon_id(raw)
            if cres.state != "ok":
                print(f"  [skip] {raw} canon fail: {cres.reason}", file=sys.stderr)
                continue
            if cres.idc in seen:
                continue
            seen.add(cres.idc)
            d["_slice"] = tag
            d["_idc"] = cres.idc
            docs.append(d)
    if not docs:
        print(
            f"  [warn] manifest union 过滤后无 doc 行 (where={where})"
            "——语料样例为空 (仅 S1–S4 合成样例)",
            file=sys.stderr,
        )
    return docs


def _eligible(d: dict) -> bool:
    """湖格可产样：hydrated 直用 / raw_only 免费重抽；skeleton 不占轮转槽。"""
    idc = d["_idc"]
    return lake.is_complete(idc) or (lake.cell_dir(idc) / "raw").is_dir()


def _pick_docs(docs: list[dict], n: int, seed: int) -> list[dict]:
    """跨 cluster 轮转取 n 篇（seed 定簇内序）——覆盖优先于簇内重复。"""
    if n <= 0 or n >= len(docs):
        return docs
    rng = random.Random(seed)
    pools: list[list[dict]] = []
    by_cluster: dict[str, list[dict]] = {}
    for d in docs:
        # 轮转键 = 切片:簇/层格/类目组——m1k 切片无簇字段时 cat_group 仍给
        # 主题分层；_slice 前缀防止跨切片同名键（'?'、HOT 等）并池。
        key = (
            f"{d.get('_slice', '?')}:"
            f"{d.get('cluster_id') or d.get('stratum_cell') or d.get('cat_group') or '?'}"
        )
        by_cluster.setdefault(key, []).append(d)
    for key in sorted(by_cluster):
        pool = by_cluster[key]
        rng.shuffle(pool)
        pools.append(pool)
    out: list[dict] = []
    while len(out) < n:
        progressed = False
        for pool in pools:
            if pool and len(out) < n:
                out.append(pool.pop())
                progressed = True
        if not progressed:
            break
    return out


def _main_tex(ext: Path, arxiv_id: str) -> Path | None:
    """lake cell extracted/ → 主 tex 绝对路径（locate 定位，失败回退首个 .tex）。"""
    if not ext.is_dir():
        return None
    res = locate(ext, arxiv_id=arxiv_id)
    if res.main:
        return ext / res.main
    texs = sorted(ext.rglob("*.tex"))
    return texs[0] if texs else None


def _samples() -> list[dict]:
    """切片 union → eligible 过滤 → 跨簇选篇 → 湖格水化 → 分桶等距 + 合成。"""
    docs = _pick_docs(
        [d for d in _load_manifests(MANIFESTS, WHERE) if _eligible(d)],
        DOCS, SEED)
    by_kind: dict[str, list[dict]] = {}
    for d in docs:
        raw = str(d.get("id") or "")
        idc = d["_idc"]
        cell = lake.hydrate(idc)
        if cell is None:
            # skeleton/失败格无本地 payload——湖外抓取归 corpus builder
            print(f"  [skip] {idc} 湖格不可水化", file=sys.stderr)
            continue
        main = _main_tex(cell / "extracted", idc)
        if main is None:
            print(f"  [skip] {idc} 无主 tex", file=sys.stderr)
            continue
        try:
            parsed = parse_file(main, flatten=True)
        except Exception as e:
            print(f"  [skip] {idc} parse fail: {e}", file=sys.stderr)
            continue
        i = 0
        for c in parsed.chunks:
            if 300 <= len(c.content) <= 1200 and PH_RX.search(c.content):
                kind = c.context or "para"
                by_kind.setdefault(kind, []).append(
                    {
                        "name": f"{raw}#{i}",
                        "doc": raw,
                        "kind": kind,
                        "src": c.content,
                        "synthetic": False,
                    }
                )
                i += 1
    if not by_kind:
        print(
            "  [warn] 语料桶为空 (doc 不可水化/无主 tex/parse 失败或无候选 "
            "chunk)——输出仅 S1–S4 合成样例",
            file=sys.stderr,
        )
    out: list[dict] = []
    for kind in sorted(by_kind):
        pool = by_kind[kind]
        step = max(1, len(pool) // PER_KIND)
        out.extend(pool[::step][:PER_KIND])
    out.extend(
        {**s, "synthetic": True, "doc": "synthetic", "kind": "stress"}
        for s in SYNTHETIC
    )
    if SAMPLES_LIMIT and len(out) > SAMPLES_LIMIT:
        real = [s for s in out if not s["synthetic"]]
        syn = [s for s in out if s["synthetic"]]
        keep_real = max(1, SAMPLES_LIMIT - len(syn))
        step = max(1, len(real) // keep_real)
        out = real[::step][:keep_real] + syn
        out = out[:SAMPLES_LIMIT]
    return out


def _items() -> list[dict]:
    """samples × MODELS × REPS —— id=样例名，arm=模型，variant=r{n}@EPOCH。"""
    samples = _samples()
    return [
        {
            "id": s["name"],
            "arm": model,
            "up": "-",
            "variant": f"r{rep}@{EPOCH}",
            "params": {
                "src": s["src"],
                "kind": s["kind"],
                "doc": s["doc"],
                "synthetic": bool(s["synthetic"]),
            },
            "fp_input": hashlib.sha256(s["src"].encode()).hexdigest(),
        }
        for model in MODELS
        for rep in range(REPS)
        for s in samples
    ]


# --- 判定（E22 逐字口径） --------------------------------------------------------


def _judge(src: str, zh: str) -> dict:
    """契约判定。hard_ok 按 E22: validator 无 error ∧ ph 无丢/造 ∧ cs 无丢失。"""
    rep = validate_pair(src, zh)
    ph_src = PH_RX.findall(src)
    ph_zh = PH_RX.findall(zh)
    ph_missing = sorted(set(ph_src) - set(ph_zh))
    ph_invented = sorted(set(ph_zh) - set(ph_src))
    ph_order = ph_src == ph_zh  # 序守恒——软信号，不计硬失败
    fragile_src = len(FRAGILE_CS_RX.findall(src))
    fragile_zh = len(FRAGILE_CS_RX.findall(zh))
    # 判定与 validator 同源——逐 token 丢失是 L0 error (message 带 cs_dropped
    # 标记)；上面总量计数只是近似旁证，不与 validator_issues 相矛盾。
    cs_dropped = any(
        i.severity == Severity.ERROR and "cs_dropped" in i.message
        for i in rep.issues
    )
    validator_ok = rep.ok
    hard_ok = validator_ok and not ph_missing and not ph_invented and not cs_dropped
    zh_clean = CS_RX.sub(" ", PH_RX.sub(" ", zh))
    en_residue = len(EN_WORD_RX.findall(zh_clean))
    return {
        "hard_ok": hard_ok,
        "validator_ok": validator_ok,
        "validator_issues": [
            f"{i.severity}:{i.rule}:{i.message}" for i in rep.issues
        ],
        "ph_missing": ph_missing,
        "ph_invented": ph_invented,
        "ph_order_ok": ph_order,
        "cs_dropped": cs_dropped,
        "fragile_src": fragile_src,
        "fragile_zh": fragile_zh,
        "en_residue_words": en_residue,
        "zh_len": len(zh),
    }


# --- 付费格 --------------------------------------------------------------------


_PAID_GATES = (
    paidmod.PaidPause,
    paidmod.PaidAbortRun,
    paidmod.PaidAbortCell,
    paidmod.BudgetExceeded,
    paidmod.AuthError,
)


def _wire_call(cli, model, messages, *, options=None, timeout_s=None):
    """一次被测请求——GatewayChat 泵上直驱 ``ChatClient._chat_once``。

    ``chat()`` 的免费集降级臂整段绕过（换模型=评测毒化）；仅
    ``_stream_rescuable``（传输族/5xx 非流式路由死亡形）时经
    ``_chat_via_stream`` 原地补一发——换协议路径不换模型。
    ``session.request`` 的 callable-method 通道把 cli 注入首参。
    """
    timeout = (
        httpx.Timeout(float(timeout_s), connect=10.0)
        if timeout_s
        else None
    )

    async def go():
        c = cli._cli()
        try:
            return await c._chat_once(
                model, messages, options, req_timeout=timeout
            ), False
        except ChatError as e:
            if not _stream_rescuable(e):
                raise
            return await c._chat_via_stream(model, messages, options), True

    res, via_stream = cli._pump.run(go())
    return {
        "text": res.content,
        "reasoning": res.reasoning or "",
        "model": res.model,
        "finish_reason": res.finish_reason,
        "latency_s": res.latency_s,
        "via_stream": via_stream,
        "usage": {
            "in_tok": res.usage.prompt_tokens,
            "out_tok": res.usage.completion_tokens,
            "cached": res.usage.cached_tokens,
        },
    }


def _xlat(ctx):
    """单格 = 一次 (sample,model,rep) 测量。测量落地→ok|partial，否则 error。"""
    it = ctx.cell
    p = it.get("params") or {}
    src = str(p.get("src") or "")
    model = ctx.arm
    gap = float(ctx.params.get("gap_s", GAP_S))
    temperature = float(ctx.params.get("temperature", TEMPERATURE))
    max_tokens = int(ctx.params.get("max_tokens", MAX_TOKENS))
    retry_max = int(ctx.params.get("retry_max_tokens", RETRY_MAX_TOKENS))
    timeout_s = float(ctx.params.get("timeout_s", TIMEOUT_S))
    rep = int(str(ctx.variant).split("@", 1)[0].lstrip("r") or 0)

    row_base = {
        "metric": "xlat_call",
        "sample": ctx.idc,
        "model": model,
        "rep": rep,
        "doc": p.get("doc"),
        "kind": p.get("kind"),
        "synthetic": bool(p.get("synthetic")),
        "prompt_sha": PROMPT_SHA,
    }
    if not src:
        return {
            "status": "error",
            "errors": [{"code": "empty_src", "payload": ctx.idc}],
        }

    session = ctx.gateway()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": src},
    ]

    def attempt(max_tok: int):
        return session.request(
            _wire_call,
            model,
            messages,
            options=ChatOptions(temperature=temperature, max_tokens=max_tok),
            timeout_s=timeout_s,
        )

    t0 = time.time()
    res = None
    err = None
    retry_429 = False
    retried_32k = False

    try:
        res = attempt(max_tokens)
    except _PAID_GATES:
        raise
    except Exception as e:  # 传输/HTTP/合同违约等同旧 http=-1/err 行
        err = e

    if isinstance(err, ChatError) and getattr(err, "status", None) == 429:
        # 网关本地限流：至多额外等 3 次指数退避补一枪（旧格内策逐字平移）
        retry_429 = True
        for n in range(3):
            time.sleep(gap * (2 ** (n + 1)))
            try:
                res = attempt(max_tokens)
                err = None
                break
            except _PAID_GATES:
                raise
            except Exception as e:
                err = e
                if not isinstance(e, ChatError) or e.status != 429:
                    break

    if isinstance(err, LengthTruncatedError) and not err.partial_content:
        # finish=length ∧ 空正文 → 单次 32k 放大重试（旧格内策逐字平移）
        time.sleep(gap)
        retried_32k = True
        try:
            res = attempt(retry_max)
            err = None
        except _PAID_GATES:
            raise
        except Exception as e:
            err = e

    if isinstance(err, LengthTruncatedError) and err.partial_content:
        # finish=length 带正文——旧世界照样判截断译文（测量行）
        res = {
            "text": err.partial_content,
            "reasoning": "",
            "model": model,
            "finish_reason": "length",
            "latency_s": round(time.time() - t0, 2),
            "via_stream": False,
            "usage": {"in_tok": 0, "out_tok": 0, "cached": 0},
            "unmetered": True,
        }
        err = None

    if err is not None or res is None or not res.get("text"):
        status = getattr(err, "status", None)
        ctx.emit(
            {
                **row_base,
                "http": status if isinstance(status, int) else -1,
                "seconds": round(time.time() - t0, 2),
                "error": (str(err)[:500] if err else "empty content"),
                "retry_429": retry_429,
                "retried_32k": retried_32k,
            }
        )
        return {
            "status": "error",
            "errors": [
                {
                    "code": "chat_error",
                    "payload": (
                        f"http={status} {str(err)[:200]}"
                        if err
                        else "empty content"
                    ),
                }
            ],
        }

    zh = res["text"]
    j = _judge(src, zh)
    u = res.get("usage") or {}
    ctx.emit(
        {
            **row_base,
            "http": 200,
            "seconds": res.get("latency_s") or round(time.time() - t0, 2),
            "finish": res.get("finish_reason"),
            "reasoning_len": len(res.get("reasoning") or ""),
            "tok_in": u.get("in_tok"),
            "tok_out": u.get("out_tok"),
            "tok_cached": u.get("cached"),
            "via_stream": bool(res.get("via_stream")),
            "unmetered": bool(res.get("unmetered")),
            "retry_429": retry_429,
            "retried_32k": retried_32k,
            "src": src,
            "zh": zh,
            **j,
        }
    )
    return "ok" if j["hard_ok"] else "partial"


spec = Spec(
    kind="xlatbench",
    eval=True,  # 样例名非 arXiv id——canon 门旁路 + 终态行镜像 eval_records
    params={
        "gap_s": Param(float, default=GAP_S, fp=False),
        "timeout_s": Param(int, default=TIMEOUT_S, fp=False),
        "max_tokens": Param(int, default=MAX_TOKENS, fp=True),
        "retry_max_tokens": Param(int, default=RETRY_MAX_TOKENS, fp=True),
        "temperature": Param(float, default=TEMPERATURE, fp=True),
    },
    items=_items,
    stages=[
        Stage(
            "xlat",
            _xlat,
            paid=True,
            dedup_key=("idc", "arm", "variant"),
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "error": "retriable",
                "skip": "retriable",
            },
        ),
    ],
    gateway_factory=devin_factory(),
    lake=True,
    prefetch=False,  # 测量 run 零湖写——语料读全在 items() load 时刻
    same_id_serial=True,
    env_probes=["python"],
    code_deps=[
        "src/texlate/validate/l0.py",
        "src/texlate/latex",
        "src/texlate/arxiv/locate.py",
        "src/texlate/xlat",
        "bench/py/specs/_shared.py",
    ],
)
