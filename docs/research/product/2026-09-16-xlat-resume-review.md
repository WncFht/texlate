# xlat 续跑语义评审 + s40 质量信号分诊（2026-09-16）

> 对应 HANDOFF-2026-09-15 §2.5 两条待办 + splice-residue-probe 跟进。改动文件：
> `xlat/{placeholders,retry,prompts,pipeline}.py`、`latex/reconstruct.py`、
> `bench/py/e2e_real_bench.py`、`tests/test_xlat_{placeholders,retry,pipeline}.py`。

## 1. `skipped=completed` 语义评审结论

三层记账面各查一遍：

| 层             | 位置                           | 现状                                                                                           |
| -------------- | ------------------------------ | ---------------------------------------------------------------------------------------------- |
| chunk          | `pipeline.py:_load_resumed`    | **已正确**——`completed` 只认 ok/partial，skipped/fault 续跑重试（注释与实现一致）              |
| 任务（server） | `worker.py:DBStateBridge.load` | **已正确**——`_PIPE_TO_DB` 把 partial 折叠进 `ok`，completed 判定等价                           |
| 论文（bench）  | `e2e_real_bench.py:amain`      | **曾是漏洞**——`results[rel].status` 非空即 cached，draining 窗口里传输级 skip 的论文被永久墓标 |

修复：新增 `_paper_done()` 谓词——`bench_error`、translate.skipped>0、
translate.fault>0 三者任一 → 不算完成，续跑重进（chunk 级 state 只重翻失败块，
成本有界）。s40→s40-r2 的 11→6 fault 收敛本身就是 chunk 级重试有效的实证。

语义边界说明：`fault`（阶梯四段全败）在 pipeline 侧本就进重试集，bench
谓词保持同口径——真·不可译块每轮重烧一段阶梯，率低（11/4365）代价可忽略；
若后续样本量放大可考虑给 fault 加次数上限。

## 2. 质量信号根因与落地防线

### 2a. `[[SL]]` "幻觉占位符"——实为 slots 装配 bug（已修）

全部 11 条 fault 的 warnings 均含 `slots assembled but still invalid:
多余/未识别占位符：[[SL]]`×N。根因不是模型臆造：`_assemble_slots` 对
`("ph", payload)` 项原样回拼**不解码**，编码期产生的 `[[SL]]`/`[[PL]]`
原字面残留进校验文本 → 任何含换行的 chunk 在 slots 段必败
（`test_slots_rescue` 等既有用例全是单行源，恰好绕过）。

修复：`retry.py:_assemble_slots` ph 分支改 `decode_newlines(payload)`
（`[[MATH_n]]` 等 typed token 经 decode 不变，`[[SL]]`→`\n`）。
回归测试 `test_slots_decode_newline_ph`：修复前 fallback_orig、修复后
recovered/slots。

### 2b. `\` 脆弱间距丢失——编码为占位符防线（已落）

E21/E22 硬判据 `脆弱间距命令 '\ ' 丢失`（l0.py `_check_macro`，
FRAGILE_BS 五枚+`~`）：`resp.\ to`、`s.t.\ $x$`、`cf.\ \S` 等高频形态，
模型把 `\` 当可有可无的排版噪声丢弃。阶梯四段接不住是因为模型每次都
犯同一个错——不是校验误报，是生成端真弱点。

防线：placeholders 编解码新增 `[[SP]]`/`[[SP_RAW]]`（SL/PL 同款两级转义），
`encode_newlines` 把 `\`→`[[SP]]`、`decode_newlines` 还原。模型侧看到的
是 C9 条款保护的占位符（echo 可靠性远高于裸 `\`）；校验侧 decode 后仍是
`\` 计数口径，判据不动。C9 示例列加 `[[SP]]`，PROMPT_VERSION → v3
（正确失效段级缓存）。`\,`/`\;`/`\:`/`\!`/`~` 同族未编码——无实测失败
信号，扩展点已在代码注释标明。

### 2c. 遗留观察（未动）

- `\_`/`\_end` 类 verbatim 残余 token 曾在 `_ListSource.skip_past` 注释
  出现——segmenter 侧事务，不在本次面。
- fault 块若持续失败可考虑记录 fault_count 上限——见 §1 边界说明。

## 3. splice 残留防线（2026-09-16 补，`splice-residue-probe` 跟进）

n100 实测 1524 例 leftover_ph 的根因：续跑按位置 chunk_id `{fidx}:{c.id}`
命中旧记录**不校验 source**，parse 漂移下同 id 指向不同内容，旧译文的
`[[X_n]]` 在新 ph_map 缺席 → splice 留字面残留。三处修复：

- `pipeline.py:_route_chunks` 命中前比 `prev.source == c.content`
  （state 存的 `rec.source` 是**原始 content**，编码前形态——`\`→`[[SP]]`
  编码在更下游，不会全量假 miss）。漂移即 warning + 重翻 + 丢出
  `done_map`（防异常路径把旧译文当结果返回）。
- `reconstruct.py:reconstruct` `expand()` 查无实体的 ph token 不再静默
  留字面——记入 `dangling` 集合，结尾 `log.warning` 报种类数 + 样例。
- `e2e_real_bench.py` summary 的 splice 残留行升级为 gate：
  `PASS` 或 `**FAIL** {论文: 残留数}` 逐篇点名。

回归测试 `test_resume_source_drift_retranslates`（同 chunk_id 不同
content → 旧记录不命中、真实重翻）。
