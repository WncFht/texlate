# docs-ledger — 规格勘误 + 扫荡波台账收口

> 2026-09-17。scope：docs/06、docs/08（spec-vs-impl 勘误注记）+ docs/research/2026-09-16-loop1-status-and-next.md（§4 勾掉项 + §7 扫荡波 28 行台账）。loop1 台账部分已由 overseer 线 `f489c72` 入库；docs/06/08 勘误随本批入库。

## docs/06 勘误

- §4.1 product tier 产物名：`term_dict.json` 与中间产物五表（chunks_map/placeholders_map/glossary/state/errors_report）——规格面以 docs/08 §1.4/§1.6 为准（原行 glossary.json/report.json 与 08 不一致）。

## docs/08 勘误（5 处）

- C9 占位符列举补 `[[SP]]`（post-spec 新 token，保护 `\ ` 强制空格，`placeholders.py:62`）。
- §1.3 换行编码：补 impl 两枚防御 token `[[PL]]`（`\n\n+` 空段保底）+`[[SP]]`（`placeholders.py:51-64/95-149`）。
- §1.5 重试阶梯：`fallback_orig` 在 impl 落块级 `status=fault`+`skipped`；`partial` 是论文级终态语义，块级 `partial` 另有出处=阶梯 recovered。
- §1.7 默认后端：impl 实为 tailscale `http://100.105.212.52:3003`（settings.py:40/cli.py:672），`127.0.0.1` 仅 client.py docstring 残留；禁用表 impl 精确两枚 `{"swe-1-7","swe-1-7-medium"}` 非通配（新 swe-1-7-* 变体会逃逸）；付费对照 impl 偏好表第 4 位 `glm-5-2` 非 `glm-5-3-low`。
- §6 状态矩阵：块态补第四值 `partial`（阶梯 recovered，`pipeline.py:107/614-630`）。

## loop1-status §7（随 f489c72 入库）

扫荡波 28 行交付台账 + 留存 open 项路由表（spec-xlat 10 项归属、texlog-popped 消费侧、scout-e2ereal 9 风险、scout-pf2fails 签名残余、no-main-tex P-B/P-D、utf8 P-E、app-contracts 未修面、server-deep 取证、scripts-ci 漂移、2f/catscope 在飞、deferred 清单）。leader 复核：realpostfix2 数字三处以重算 union 口径修正（后又被 scout-pf2final 纯管线口径 95/85 精化——见该行勘误注）。
