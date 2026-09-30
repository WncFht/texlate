"""运行上下文 dataclass 域（自 ``_common`` 出叶）：``Secrets``/``TaskCtx``。

``Secrets`` 是 BYOK 运行时凭证（只在内存里活过任务生命周期，绝不入库）；
``TaskCtx`` 是单次 run 的工作上下文——任务行快照 + 目录布局 +
各段内存态（fetch/parse/translate/compile 字段按段分节）+ 运行态旗标
（取消/排空/终态/日志合批/阶段计时/备忘袋）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from texlate.server.store import row_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.arxiv.html import HtmlDoc
    from texlate.latex.model import ScanResult
    from texlate.server.events import EventBus
    from texlate.server.settings import AuthContext
    from texlate.server.store import Store


@dataclass(slots=True)
class Secrets:
    """BYOK 运行时凭证（只在内存里活过任务生命周期，绝不入库）。"""

    api_key: str = field(default="", repr=False)
    base_url: str = ""
    model: str = ""
    dialect: str = "auto"
    source: str = "none"

    @classmethod
    def from_auth(cls, auth: AuthContext, *, model: str = "") -> Secrets:
        """``AuthContext`` → 运行时 ``Secrets``——``model`` 由任务行/请求面覆盖。"""
        return cls(
            api_key=auth.api_key,
            base_url=auth.base_url,
            model=model,
            dialect=auth.dialect,
            source=auth.source,
        )


@dataclass(slots=True)
class TaskCtx:
    """单次 run 的工作上下文：任务行快照 + 目录布局 + 内存态（字段按段分节）。"""

    # ---- 装配面：dispatcher 注入（全段共用） ----
    store: Store
    bus: EventBus
    task_id: str
    row: dict[str, Any]
    secrets: Secrets
    root: Path  # tasks/{id}/

    # ---- fetch 段 ----
    #: #74 post-resolve dedup 命中行（钉版键二次 ``find_reusable``）——
    #: ``_stage_fetch`` 物化其产物后任务直接终态，parse/translate 不跑
    reuse_hit: dict[str, Any] | None = None
    #: reuse 命中零物化的熔断——hit 行被并发删干净时回退自跑，重跑
    #: fetch 不得再撞同一腐行（``find_reusable`` 返回的还是它）
    reuse_dead: bool = False
    #: arxiv_html 链的 DOM 块模型（fetch/parse 建、emit 用 ph_map 回插）——
    #: tex 链恒 None；resume 路径由 ``_html_doc`` 从 src/index.html 重解析
    html_doc: HtmlDoc | None = None

    # ---- parse 段 ----
    scans: dict[str, ScanResult] = field(default_factory=dict)
    main_rel: str = ""
    engine_name: str = "tectonic"
    #: 散文门分流出的 support 文件（.code.tex 机制件/无散文宏件转储）——
    #: 按原文保留不进翻译集，送译即腐蚀（同 e2e._scan_tree 三级分流）；
    #: _stats 审计面消费
    support_files: list[str] = field(default_factory=list)
    #: _parse_all 单文件解析崩的记名单（e2e ``fault_files`` 同位）——
    #: 此前只有 log 行无结构化面，_stats 落账
    fault_files: list[str] = field(default_factory=list)

    # ---- translate 段（share 对账是同段替代臂） ----
    tokens_est: int = 0
    #: share 导入对账统计（matched/dropped/missed/extra）——done stats 与
    #: partial error_json 的审计载荷；None = 非 share 任务
    share: dict[str, Any] | None = None
    #: ``all_chunks`` 全量行的 run 内物化缓存（``_all_chunks`` 惰性填）——
    #: 每任务曾 5~7 次 ``SELECT *`` 全扫全在 loop 线程；chunk 写点
    #: （insert/flush 调用侧）置 None 失效
    chunks_cache: list[dict[str, Any]] | None = None

    # ---- compile 段 ----
    #: fixloop 跑过的压缩摘要（verdict/trace/installed）——_stage_compile
    #: 终态写 error_json / done 事件载荷用；None = 未跑
    fixloop: dict[str, Any] | None = None
    #: 第 0 招预检摘要（verdict/installed/engine_flags）——同上进
    #: error_json/done 载荷；None = 未跑（fixloop 关闭或首编 clean）
    precheck: dict[str, Any] | None = None
    #: L2 回灌报告（归因 hits/重译/回落名单）——同上进 error_json/done 载荷
    l2: dict[str, Any] | None = None
    #: judge 的 expect_cjk：0-chunk 主文档（includepdf 壳等）cjk_chars=0
    #: 是正确终态。``_stage_compile`` 在 loop 线程算好——store conn
    #: 有线程亲和，编译线程内不可查
    expect_cjk: bool = True
    #: splice 译文里的残余占位符计数（e2e ``leftover_ph`` 同位）——
    #: _build_zh 逐文件累计
    leftover_ph: int = 0
    #: _probe_target 探出的引擎 flags（-shell-escape 类）——首编经
    #: ``rep.flags`` 直连；L2 重编/cross-engine 重试经此续传（e2e
    #: ``job.probe_flags`` 同式，缺了重试臂在另一套条件下编译）
    probe_flags: list[str] = field(default_factory=list)
    #: en 首编错误签名集（``repair_l2.err_signatures``）——L2 归因
    #: 基线：原文已出现的错误签名判源生（译文不可能造成），不归块
    en_err_sigs: set[str] = field(default_factory=set)

    # ---- 运行态：取消/排空/终态旗标/日志合批/阶段计时/备忘 ----
    #: 线程级取消旗标：``cancel_running``/``stop``/``run()`` 取消臂置位。
    #: coroutine cancel 递不进在跑的 ``to_thread`` 工作线程——长段内
    #: 轮询本旗标尽快放弃（``_abort_if_cancelled``/``should_cancel``），
    #: 段边界照旧 ``_check_cancelled`` 读库收口
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    #: 在飞 ``_to_thread`` 段的完成事件集——``run()`` 收尾据此有界等
    #: 排空，retry 进入时孤儿线程已死，消除目录写交错窗口
    in_flight: set[threading.Event] = field(default_factory=set)
    #: 本地终态旗标（终态 status 字符串，空=未终态）——worker 自迁的
    #: 终态点自置；事件写路径守卫先查它短路，空旗才 ``store.get`` 兜底
    #: （外部 cancel 不立旗，库读仍是权威）
    terminal: str = ""
    #: ``_log`` 行缓冲（日志合批）：``_LOG_FLUSH_N``/``_LOG_FLUSH_S``
    #: 阈值或 ``_stage``/``_warning``/终态边界排空；``log_last`` 记上次
    #: 排空 monotonic——突发行（fixloop/babeldoc 逐行扇出）合并成单事件
    log_buf: list[str] = field(default_factory=list)
    log_last: float = 0.0
    #: ``_stage`` 首次进入点的 monotonic——done 载荷 ``stage_seconds``
    #: 由相邻 mark 差值推导（末段计到 ``_stats`` 构建时）
    stage_marks: dict[str, float] = field(default_factory=dict)
    #: 每任务备忘袋：``_make_glossary``/``_make_cache`` 这类每任务重复
    #: 构造的段内复用位（键由消费点自取，如 ``"glossary"``）
    memo: dict[str, Any] = field(default_factory=dict)

    @property
    def src_dir(self) -> Path:
        """原始源树（fetching 产物，只读）。"""
        return self.root / "src"

    @property
    def base_dir(self) -> Path:
        """Normalize 后树（parsing/translating 输入）。"""
        return self.root / "base"

    @property
    def zh_dir(self) -> Path:
        """译文工程树（splice + ctex 注入产物）。"""
        return self.root / "zh"

    def options(self) -> dict[str, Any]:
        """任务 ``options_json`` 反序列化。"""
        return row_json(self.row, "options_json")

    def config(self) -> dict[str, Any]:
        """任务 ``config_json`` 反序列化（``options()`` 同口径容错读）。"""
        return row_json(self.row, "config_json")

    def update_options(self, fn: Callable[[dict[str, Any]], None]) -> str:
        """options「读 - 改 - 序列化 - 同步 row 快照」单点；返回新 options_json。

        ``fn`` 拿到反序列化 dict 原地改键。**写库留给调用点**——多站点
        捎带 ``main_tex`` 等合并字段一笔 ``update_fields``，收口进这里
        反而拆事务/多写一次。
        """
        opts = self.options()
        fn(opts)
        self.row["options_json"] = json.dumps(opts, ensure_ascii=False)
        return self.row["options_json"]

    def set_option(self, key: str, value: Any) -> str:  # noqa: ANN401 -- options 值面天然 Any
        """``update_options`` 的单键便捷形。"""
        return self.update_options(lambda opts: opts.update({key: value}))
