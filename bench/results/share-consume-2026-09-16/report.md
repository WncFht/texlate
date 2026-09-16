# share-consume — kind=share 消费侧 live 冒烟（零网关 mock）

> 2026-09-16。双实例跨进程共享同一 `TEXLATE_SHARE_DIR`：consumer :8817（`/tmp/share-consume-data`）、producer :8818（`/tmp/share-prod-data`）。consume 路径 = `POST /api/share/import`（multipart）→ `unpack_share` 机械校验 → `kind=share` 任务 → worker `_run_share`（fetch→parse→`_share_apply` 对账→`_stage_compile(share=True)`）。src-cache 预热 cond-mat/0408438v1 零网络。

## 四臂判决

**A1 正臂（异码包，share-live2 存货）→ partial**：matched=59/60、missed=1、extra=1 → 本地全链重跑 verdict clean → zh.pdf 本地重编（hash 与包内不同）→ partial（1 块 fallback_orig，`error.share` 带对账统计）。唯一未中块 = 作者列表前导空格差异——包产出于 20:31、消费跑于 latex/ 在飞漂移期（segmenter/gullet/reconstruct/tables 均有改动），**双端代码漂移实证，非管线不确定性**（A2 证）。

**A2 正臂（同码包，真跨实例）→ done**：producer opt-in 产新包 + index 第 2 行 → consumer 命中 → matched=60/60 → done。断言全过：kind=share、model 取 manifest 值、`tokens=0` + task_usage 无行 + 零 `chunk` 事件（三重零 token 证据）、六件产物齐、本地 dual.json zh 与包内 60/60 逐条一致、本地 zh.pdf ≠ 包内（重编实证）、options.share 审计载荷由端点强制覆盖。

**B 负臂（篡改）→ 端点 400**：zh.pdf 成员翻 1 字节 → `sha256 mismatch for artifact: zh.pdf` / `code=share_invalid`，不建行不入队。

**C 负臂（index miss）→ 正常自译 done**：bogus key → 正常 arxiv 任务，tokens=6955 + chunk 事件——与 share 臂零 token 形成干净对照。

零扰动核验：原 index 行与包 sha256 全程不变；consumer server.log 零 error/warning/traceback。

## 契约观察（已由 leader 对齐）

1. **spec §5「回退自译」措辞与 v1 实现漂移**：实现永不自译回退（端点 400 / partial+reject_at=share_verify / 块级 fallback_orig）——零 token 结构承诺。shared-cache.md §0/§5 已按实现改词（同 commit）。
2. **pipeline_ver 不覆盖脏树代码漂移**：七组分相同而双端代码不同（A1 missed=1 实证）——发布态靠 pipeline_ver bump 兜住；对账层行为正确（miss→fallback→partial，无坏 PDF、零 token），信任模型按设计工作。

## 证据

事件流 `/tmp/share-consume-events-t_*.json` ×3；日志 `/tmp/share-consume-server.log`、`/tmp/share-prod-server.log`；driver `/tmp/share_consume_smoke.py`；现场 `/tmp/share-consume-{data,share}`、`/tmp/share-prod-data`；:8817/:8818 已停。
