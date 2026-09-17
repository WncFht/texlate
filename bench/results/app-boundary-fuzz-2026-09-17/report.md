# app-boundary-fuzz — server/app.py HTTP 边界对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_app_boundary.py`（107 用例，commit `f25e50a`）：**91 passed + 16 xfailed(strict，零 xpass)**，ruff check/format 双净。全离线 TestClient，无随机量。

## 覆盖面

`_read_body`/`_parse_multipart` 闸后解析（巨 int/深嵌套/畸形 boundary/字段重名/1MB part 闸/1000 字段闸/CL 谎报/魔数-vs-声明 CT）、settings 并发 churn（6 线程 save+load + HTTP 4 线程 PUT/GET 完整性+0600）、share_pack 索引敌意行（真 share_key 经 `runner.worker.share_pack_manifest` 派生，首次真正打到 flat-name 闸）、SSE Last-Event-ID/Accept 形态、task_id/arxiv_id/kind 路径变形、reader position 值宽容度。

## 确认缺陷（实证，strict xfail 钉）

| # | 缺陷 | 位置 | 复现/影响 | 修法 |
|---|------|------|-----------|------|
| D1 | `json.loads` 漏捕非 JSONDecodeError | app.py:637-639 `_read_body`，同型 :941 `_upload_fields` options、~:1055 share_import options | `{"options":{"k":<5000位int>}}`→ValueError→500；`[`*200k→RecursionError→500。loopback 无鉴权面 5KB 体即可 500 任一 JSON 端点 | 三处 except 扩 `(JSONDecodeError, ValueError, RecursionError)` |
| D2 | `concurrency` 非数值 500 | settings.py:223 `int()` 抛 TypeError；app.py settings_put 只捕 ValueError | `PUT /api/settings {"concurrency":null\|{}\|[]}`→500；对照 `quota_max_tasks:null`→400（`_check_quota` 双捕） | 端点 except 加 TypeError |
| D3 | python-multipart 引擎错逃逸 | `request.form()` 只包 MultiPartException | boundary 声明不符/part 体内伪 `--X` 行/`boundary=X; boundary=Y` 重复参/裸 boundary 无值 全 500 | `_parse_multipart` 补捕 FormParserError→400 |
| D4 | `Last-Event-ID` ≥2^63 → SQLite 绑参 OverflowError | app.py:836 int() 无界 | snapshot 帧已发后流中道崩断（客户端拿截断流） | int() 后夹 int64 上界或超界按 0/全量重放 |
| D5 | 媒体类型大小写敏感 | app.py:831 子串判；starlette content_type 字节等 | `Accept: TEXT/EVENT-STREAM` 退成 JSON 快照；`MULTIPART/FORM-DATA` 上传 400 | accept 先 `.lower()`；multipart CT 规范化或容忍（文档钉） |

## 备注

`test_accept_media_type_case`/`test_huge_last_event_id_graceful` 做成修复后也不挂的形态（终态任务+done 事件），XPASS 即修复信号。
