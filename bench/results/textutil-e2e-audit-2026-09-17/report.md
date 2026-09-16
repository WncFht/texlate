# textutil-e2e-audit — textutil.py 全修 + e2e 限修交付

> 2026-09-17 收口。落地 `7d943ae`（textutil.py + e2e.py 一行 + 新 test_textutil.py + test_e2e_wiring.py，+208/-27）。自验 `-k "textutil or e2e"` 79 绿、ruff 双净。探针现场 tmp/textutil-e2e-audit/（probe1-6 + corpus_scan 654 非 UTF-8 件回归）。

## 修复清单（5 项，全部实证先行）

1. **数学定界配对机重写**（textutil.py `_cs_events_spans`/`_math_spans`，:151-215）：旧实现事件收集期把相邻 `$$` 预并 display 定界子——`text $a\alpha$$b\beta$$ end` 中「inline 闭 `$`+下一开 `$`」被错并 `$$` 开区间、配对挂起 → spans=[] → `bare_cs_net` 误报文本域裸 cs（restore 臂 CJK/裸 cs 计数面失真）。新实现状态机：文本态相邻对开 `$$` 否则开 `$`；inline 单 `$` 闭；display 仅相邻对闭；`\(`/`\[` 严格配对、裸闭子忽略。
2. **`_declared_name` 遮盖面**（:429 附近）：旧对 raw bytes 扫描，注释行伪声明带偏解码方向。现对 `mask_tex(view)` 后 active 区扫描；`% !TEX encoding`/SWP `CodePage:` 注释形态声明按设计仍扫 raw（测试钉两侧口径）。
3. **utf-16 无 BOM 奇数字节截断兜底**（:802-804）：le/be strict 皆败时旧落 strict-utf8 产 NUL 夹心乱文。现按 NUL 奇偶位选端 + `errors="replace"` 打捞，note `nul-dense,bad-tail`。
4. **`lev_capped` 契约压顶**（:985）：终格可无行越界而超 cap（实证 `aaab`/`babbbbb` cap=3 旧回 5）。现恒回 ≤cap+1。
5. **`_env_judge_one` 解析纳入重试域**（e2e.py:154）：`parse_env_judge_answer` 移进 try——非 str 应答/解析器异常走 3 次重试后 fail-open `True`（worker `_env_judge_filter` 复用同函数，同受益于口径一致）。

## 新测试

test_textutil.py（新，14 例）：lev_capped 契约界、数学配对 7 例、declared 遮盖 4 例、utf-16 奇字节尾两端。test_e2e_wiring.py：`_JudgeBadReturn` 违约 translator + fail-open 断言。

## 未修（理由） / 外部路由

- cyrillic-veto 族不调参：任何方向扩面都回归真实 GBK，需标注 fixture 语料专项。
- `decode_tex_with` 双 `_decode_mixed` 幂等 perf nit；`_CJK_DECLARED` cp54936 死项（5 位过不了 `cp\d{3,4}`）；`_declared_name` last-match-wins 自洽仅记档。
- **→1d（e2e 受限面）**：`_scan_tree` 缺 dotfile/is_file/`file_has_prose`/`.code.tex`→support 四门（worker `_parse_all` b71ca7e 起有）；`_run_fixloop` 未传 `ruleset=`（**leader 注：已裁——e2e 从源起步后段腐蚀不累积，builtin fail-safe no-op 是正确终态，1d 已确认**）；`_slim_cell` 未拆 salvage/setup 轮（worker `_fixloop_summary` 已拆）。
- **产品裁决**：L2 `fallback_unverified`+fixloop disabled 时 resplice 源与已交付 PDF 不一致（文档化取舍记档）。
- `route_project` reject 分支 dead-ish：engine.py 恒回非空 engines+reject=None；若恢复 reject 逻辑需回核。
