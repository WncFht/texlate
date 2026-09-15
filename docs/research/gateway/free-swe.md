# gateway-3003 免费 SWE 系横评（en→zh LaTeX 段落翻译）

日期：2026-09-14 深夜。探针 `tmp/exp/gwbench/gateway_swe_probe.py` + 复测 `tmp/exp/gwbench/gateway_swe_confirm.py`，原始数据 `tmp/exp/gwbench/gateway_xlat_swe.json`（含全部 src/zh/usage/reasoning_len）。样例/契约/校验同 `gateway-3003-xlat.md`（A=chunk#15，B=#21，C=#58，D=手写压力样例，`tmp/exp/rule_validator.validate_pair`）。全程串行 + ≥1.2s 间隔，timeout 180s，max_tokens 8192。

## TL;DR

1. **低档能守住契约且把延迟压下来，但要挑型号**：`swe-1-7-lightning-medium`（avg 2.2s/chunk，4/4 PASS）与 `swe-2-medium`（avg 6.6s，4/4 PASS，reasoning 仅 ~100 字符、out 128–186 tok 比 sonnet 还省）是免费档里可用的两档；`swe-1-7-lightning`（3.0s，4/4）次之。**`swe-1-6-fast` 和 `swe-1-7-medium` 各在 D 样例丢了行首 `[[BIBITEM_1]]`（3/4）**——低思考变体在"占位符紧贴句首人名"场景有翻车模式。`swe-1-7` 裸档契约 4/4 但延迟是地雷：D 样例 reasoning 爆了 12 万字符/31.7k out token/125s。
2. **思考基本关不掉，真正的 effort 旋钮是模型名后缀**。对 swe-2-medium 所有关思考字段（`reasoning_effort` low/none/minimal、`thinking.disabled`、`reasoning.effort`、/v1/responses）rlen 恒 ~147、延迟不变——它本已在最低档。对 swe-1-7 只有 `reasoning_effort:"none"` 三次复测稳定在 ~3.4–3.9k 字符（vs 基线 12k–120k 剧烈波动），延迟落回 ~5s；`"minimal"` 4 次里 3 次低；`"low"`、`thinking:{type:disabled}`、`reasoning:{effort:low}`、/v1/responses 的 effort 均落在基线方差内，判定**透传但上游不认/效果不稳定**。网关对所有未知字段不报错（HTTP 200 原样返回），属"静默忽略"而非校验失败。
3. **契约存活总计 30/32**（6 模型全 4/4 + 2 模型 3/4），失败均为同一模式：丢行首 `[[BIBITEM_1]]`。占位符契约在主力推荐档 100%。
4. **延迟排序**（4 样例均值）：swe-1-7-lightning-medium 2.2s < swe-1-6-fast 2.4s < swe-1-7-medium 2.7s < swe-1-7-lightning 3.0s < swe-2-medium 6.6s < swe-1-6 8.0s < swe-2-high 10.5s ≪ swe-1-7 37.9s ≪ swe-2-max 63–124s。
5. **vs sonnet-5-medium 基线**（~3.2s/chunk、out 170–277 tok、4/4）：`swe-1-7-lightning-medium` 延迟已打平甚至略胜，token 账单相近；`swe-2-medium` 慢一倍但输出 token 更省且思考开销几乎为零。免费档可作 sonnet 的平替/降级链，但仍建议生产前跑 `bench/fixtures/` 大样本回归（本批仅 4 样例 × n=1）。

## 全矩阵（POST /v1/chat/completions，temp=0.2，max_tokens=8192）

| 模型                     | A         | B           | C          | D               | PASS    | avg 延迟 | out tok (A–D)          | reasoning_len (字符，A–D)  | in tok   |
| ------------------------ | --------- | ----------- | ---------- | --------------- | ------- | -------- | ---------------------- | -------------------------- | -------- |
| swe-1-6                  | PASS 4.9s | PASS⚠1 4.3s | PASS 10.3s | PASS 12.7s      | **4/4** | 8.0s     | 1509/1336/3303/3416    | 4.3k/3.7k/9.0k/11.1k       | ~155–227 |
| swe-1-6-fast             | PASS 4.6s | PASS 1.5s   | PASS 2.7s  | **FAIL** 1.0s   | 3/4     | 2.4s     | 638/588/1098/366       | 2.0k/1.9k/3.0k/0.9k        | ~493–567 |
| swe-1-7                  | PASS 4.0s | PASS 2.5s   | PASS 19.7s | PASS **125.3s** | 4/4     | 37.9s    | 828/532/4951/**31732** | 2.7k/1.5k/15.1k/**119.7k** | ~161–235 |
| swe-1-7-medium           | PASS 2.0s | PASS⚠1 2.8s | PASS 3.2s  | **FAIL** 2.9s   | 3/4     | 2.7s     | 337/584/581/378        | 0.7k/1.6k/1.5k/0.9k        | ~497–571 |
| swe-1-7-lightning        | PASS 1.6s | PASS 2.4s   | PASS 3.7s  | PASS 4.2s       | **4/4** | 3.0s     | 567/995/1822/1822      | 1.6k/3.3k/5.4k/6.3k        | ~161–235 |
| swe-1-7-lightning-medium | PASS 1.3s | PASS⚠1 1.2s | PASS 1.6s  | PASS 4.8s       | **4/4** | **2.2s** | 398/450/698/2010       | 1.1k/1.2k/1.9k/7.1k        | ~493–567 |
| swe-2-medium             | PASS 7.0s | PASS 6.2s   | PASS 5.0s  | PASS 8.4s       | **4/4** | 6.6s     | 128/154/186/130        | **98/98/98/144**           | ~249–323 |
| swe-2-high               | PASS 9.2s | PASS 8.3s   | PASS 12.5s | PASS 12.1s      | **4/4** | 10.5s    | 387/158/576/545        | 298/124/498/598            | ~249–323 |

- 全部 HTTP 200、finish_reason=stop，无 length+empty、无 4xx/5xx——8 个模型全在清单且全授权。
- B 的 3 个 warn 全是 zh/src 长度比 0.29–0.30 压线（同 sonnet 上次情况，校验器下界问题，非契约问题）。
- D 两处 FAIL 均为 `占位符缺失: [[BIBITEM_1]]`（error，validator 抓到）。swe-1-6-fast 还顺带丢了 `\` 控制空格。
- **隐藏系统提示开销分档**：裸 swe-1-7/lightning in_tok≈160–235，-fast/-medium/lightning-medium ≈500，swe-2 系 ≈250–320——不同变体注入的上游 harness 提示不同，计费要按档分开估。
- **swe-1-7 裸档的 reasoning 长度方差极大**（D 复测 12k/120k 都出现过），机理像思考循环失控；`-medium`/`-lightning` 后缀是出厂固定的 effort 档，比运行时参数可靠。

## 参数实验（样例 D，chat/completions 逐字段加；rlen=reasoning_content 字符数）

### swe-2-medium（基线 rlen=144 / 8.38s / out=130）

| 变体                                     | 延迟  | rlen             | out tok | 契约 | 判定                                                           |
| ---------------------------------------- | ----- | ---------------- | ------- | ---- | -------------------------------------------------------------- |
| `reasoning_effort:"low"`                 | 8.6s  | 147              | 130     | PASS | 无变化                                                         |
| `reasoning_effort:"none"`                | 8.9s  | 147              | 129     | PASS | 无变化                                                         |
| `reasoning_effort:"minimal"`             | 10.8s | 147              | 130     | PASS | 无变化                                                         |
| `thinking:{"type":"disabled"}`           | 11.7s | 147              | 129     | PASS | 无变化                                                         |
| `reasoning:{"effort":"low"}`             | 11.7s | 147              | 130     | PASS | 无变化                                                         |
| `/v1/responses` + `reasoning.effort=low` | 11.1s | 60（仅 summary） | 127     | PASS | 端点可用；思考摘要不回传正文，且**译文丢了 `\`（变普通空格）** |

结论：swe-2-medium 本已运行在思考地板（~100 字符），所有字段无观测效果——无法区分"忽略"还是"已是最低"。延迟地板 ~5–12s 与字段无关。

### swe-1-7（基线 rlen 两轮：119729/125.3s、11996/12.2s —— 方差极大）

| 变体                                     | rlen / 延迟（多轮）                 | 契约   | 判定                                                              |
| ---------------------------------------- | ----------------------------------- | ------ | ----------------------------------------------------------------- |
| 基线                                     | 119.7k/125s、12.0k/12.2s            | PASS   | 思考失控区间 12k–120k                                             |
| `reasoning_effort:"low"`                 | 107.9k/109s、3.9k/7.1s、11.5k/11.8s | PASS×3 | **判忽略**：落在基线方差内                                        |
| `reasoning_effort:"none"`                | **3.6k/5.6s、3.9k/4.4s、3.4k/4.6s** | PASS×3 | **疑似生效**：3/3 稳定 ≤3.9k；C 样例验证 15.1k→1.6k（19.7s→2.3s） |
| `reasoning_effort:"minimal"`             | 3.6k/4.5s、17.0k/15.6s、2.0k/2.8s   | PASS×3 | 大体压低，1 次 17k 离群；C 样例 →1.4k/2.3s                        |
| `thinking:{"type":"disabled"}`           | 11.1k/11.1s、6.8k/7.0s              | PASS×2 | 中位区，判忽略/弱效                                               |
| `reasoning:{"effort":"low"}`             | 18.8k/18.0s、3.7k/4.3s              | PASS×2 | 方差内，判忽略                                                    |
| `/v1/responses` + `reasoning.effort=low` | 1.5k/2.2s、**53.0k/48.3s**          | PASS×2 | 不稳定，不优于 chat+none                                          |

- 未知字段全部 HTTP 200 静默透传（无 400/校验报错），响应结构不变——只能靠效果反推是否被上游识别。
- 即便 `none` 生效也只是压到 ~3.5k 字符（≈1k tok），**不能完全关思考**；想零思考请直接用 `-lightning`/`-medium` 后缀档或 swe-2-medium。
- 参数实验 12+9 次请求契约全 PASS——关思考参数不破坏占位符契约。

## 质量一句话点评（D/C 抽查）

- **swe-1-6**：`\` 全保；术语"膨胀卷积/逐点前馈层"稳；思考量大（3–11k 字符）但没转化成明显质量优势。
- **swe-1-6-fast**：D 丢 `[[BIBITEM_1]]`+`\`；C 用"空洞卷积"质量在线——快但契约不可信。
- **swe-1-7**：D 全保（`\` 在，"提出了 Transformer" 少个空格属排版瑕疵）；思考爆炸但译文并未更好。
- **swe-1-7-medium**：D 丢 `[[BIBITEM_1]]`（`\` 倒保住了）；其余样例行文干净。
- **swe-1-7-lightning**：D 全保含 `\`，保留 "Vaswani et al." 原文（可接受）；C 把 point-wise 括注英文，小加词。
- **swe-1-7-lightning-medium**：D 全保含 `\`，"先期工作"等措辞自然；D 延迟 4.8s 明显高于其 A–C（~1.4s），压力样例仍会触发较多思考。
- **swe-2-medium**：D 全保含 `\`，行文最贴 sonnet；思考恒定 ~100 字符，行为最可预测。
- **swe-2-high**：契约全保，但 D 把 "et al." 译成 "Vaswani 等.\" 留了个游离句点；延迟比 medium 高约 60% 无质量收益。

## 接入建议

- 免费档首选 **`swe-1-7-lightning-medium`**（2.2s、4/4、D 压力样例 `\` 全保）；保守选 **`swe-2-medium`**（慢至 6.6s 但思考开销≈0、输出 token 最省、行为方差最小）。二者构成 sonnet-5-medium 之外的零成本降级链。
- 避免：`swe-1-6-fast`/`swe-1-7-medium`（BIBITEM 前缀占位符会丢）、`swe-1-7` 裸档（reasoning 失控风险，单 chunk 可 125s/32k tok）、`swe-2-max/-high`（贵/慢无收益）。
- 若必须用 swe-1-7：`reasoning_effort:"none"` 是当前唯一有稳定观测效果的压思考参数（~5s/chunk）；但后缀档位才是可靠机制。
- 遗留：各档 n=1/样例（D 的失败模式需 fixtures 级回归确认是概率还是确定性）；流式、并发限流、`seed`/`response_format` 未测；`-medium` 后缀档是否等价于 `reasoning_effort:"medium"` 透传未验证（现象一致但无直接证据）。
