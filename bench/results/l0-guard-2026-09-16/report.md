# l0-guard — 协议回显交付守卫 + COMMENT ph 行锚定

> 2026-09-16。入库 `bb3ecc0`：`src/texlate/validate/l0.py`（+135/-7）、`tests/test_validate_l0_echo.py`（36 用例）、`validate/__init__.py` docstring 七→九。依据 repro-2410b §4b/§4c。

## Guard 1 — `_check_protocol_echo`（第九条检查，validate_pair 末尾注册）

error 级 → `report.feedback()` 非空 → 阶梯 corrector 重试 → 三振 `fallback_orig` 回退原文——与 `_intercept_leftover_ph` 同层既有 fault 路径，pipeline 零改动。

签名两档，全部 src↔zh 净差判定（src 自带同形 = 忠实翻译豁免）：

- `_ECHO_LITERALS` 子串：`占位符缺失:`、`多余/未识别占位符:`、`占位符疑似拼错`、`结构占位符`、`注释区内臆造占位符`、`slot_validation_failures`、`[compile_error]`（pipeline.py:627 L2 回灌标——与 harness `DIRTY_SIGS` 对齐收尾时补入）
- `_ECHO_LINE_RX` 独立成行：`^[ \t]*\[(Original|Translation|Error|previous_validation_error)\][ \t]*\r?$`（MULTILINE 含 CRLF）——`[这是译文]` 独行、`[Error]` 行内用法均不报

## Guard 2 — `_check_ph_anchor` 扩 COMMENT 类（l0.py:361）

- BIBITEM 原逻辑不变。
- `cmt_anchored` = src 中整行纯 `[[COMMENT_n]]` 的 token → zh 中所在行必须整行纯注释 ph（前缀=splice 残留垃圾、后缀=被 `%` 吃掉的死字节），否则 error。
- 非 anchored（src 行中 ph，恒处行尾因注释吃到换行）只查尾段——`Title [[COMMENT_1]]` 忠实保留不误伤；zh 自加后缀 `…[[COMMENT_1]] 尾巴` 仍拦。
- **对字面 spec 的一处有意偏离**：spec 原写「zh 行必须纯注释行」无条件执行——会 FP 掉 src 行中形态。按 BIBITEM 同款 src 锚定门 + 尾段规则实现，语义等价 spec 意图且零新增 FP。

## 验证

`ruff check`/`format --check` 净；echo 测试 36 绿；全量 2148 passed + 2 failed（test_server_l2 TestL2Repair——A/B 验证与本改动无关：摘掉 echo 调用同炸，MINI_TEX 无 `%` 注释两守卫均不触发；e2e.py/texlog.py 为 worker-followup #78 在飞破坏）。

## 残余（留痕）

- `_ECHO_LITERALS` 当前 = placeholder 族 + 重试协议全量（与 `DIRTY_SIGS` 对齐）。其余 L0 error 文案（`引用/标签 key 丢失:`、`多余 \end{}:`、`'$' 计数不同:`）同为可回显字面——扩常量即加宽。
- 门槛联动：本守卫把 echo 交付转 fault→原文回退；harness `dirty` 计数（`29c196f`）应随本守卫生效显著回落——下次 Mode-B 复跑即验证两层闭环。
