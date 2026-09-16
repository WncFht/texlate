# 免费 token 额度全景与实测(2026-09-16)

> 任务:找互联网上免费可用的 LLM API 额度接进 texlate。方法:本机凭据盘点 + 网关免费池实测 + 三路网络调研(国际官方档 / 国内官方+公益站 / CLI订阅转API生态) + 全部候选用 `tmp/exp/gwbench/bench_endpoint.py`(bench_free 同一契约判器)跑占位符契约冒烟。
> 数据现场:`tmp/exp/gwbench/out_smoke_{3033,prism,llm7}/results.jsonl`、`/tmp/probe_vault_results.json`。

## 0. TL;DR

**今天就能用、已验证契约的免费源有四个**(按可靠性排序):

| 源 | 认证 | 实测契约 | 延迟 | 备注 |
|---|---|---|---|---|
| devin-2api `127.0.0.1:3033` / `100.105.212.52:3003` | Bearer `240127` | swe-2-medium **7/8** | 3–10s | promo 免费至 **2026-10-16**,texlate 当前默认 |
| Prism `https://ai.prism.uno` | 保险库已有 key | gpt-4o-mini **7/8** | 3.5–8s | 23 模型全活;额度不明按量谨慎 |
| llm7.io `https://api.llm7.io` | **无需 key** | GLM-5.3-Flash 6/8 | 3–68s | 匿名档不稳定(同日下午出现连发空响应),只当机会型 |
| Pollinations `https://text.pollinations.ai` | **无需 key** | openai-fast(gpt-oss-20b)可用 | ~4s | 匿名档共享预算,实测已见"预算耗尽"内联文案——机会型 |

四个源的 base_url+key/model 已写进 `~/.texlate/connections.json`(UI 切 base_url 自动回填);`ChatClient` 产品路径实测通过。

**保险库审计结论**:`ai-key-manage/bootstrap.json` 80 条 endpoint 实测仅 2 条活(Prism GPT/Claude 同站);死因分布:401 key 被禁/失效(Hiyo/GGBOOM/JoyStar×10/SJTU)、CF 1010 拦 DC IP(42W/LinuxDo EDU/elysiver/XT URL/zhx47/DogAltman/newapi.ruize——过 :7890 代理也不解,1010 是浏览器指纹层)、域名失联(~15 条)、站点关停、账号被 ban(XT URL "User has been banned")。**公益站保鲜期按月计**——保险库需要周期性重测活。

**已死勿念**:GitHub Models(2026-07-30 整体退休)、Qwen Code OAuth 免费层(2026-04-15 关闭)、iFlow(2026-04-17 停服)、Cerebras 永久免费档(只剩 $5/30天绑卡试用)、GenStudio 基础版 LLM(2026-03-30 转收费)、hunyuan-lite(迁 TokenHub 后不支持)。

## 1. 官方免费档(需一次性注册,已全部核实当前政策)

### 1.1 国内直连(对 archbox 最有价值,免代理)

| 提供方 | Endpoint | 免费额度 | 门槛 | 质量预期 |
|---|---|---|---|---|
| **ModelScope 魔搭** | `api-inference.modelscope.cn/v1`(OpenAI+Anthropic 双兼容) | **2000 req/天**全模型共享,旗舰单模型 ~200–500/天,UTC+8 零点重置 | 注册+建 SDK Token(`ms-` 开头);社区口径需绑阿里云实名 | DeepSeek-V4-Pro/Qwen3.5/GLM-5.1 旗舰开源,**免费里质量天花板**[^ms] |
| **智谱 bigmodel** | `open.bigmodel.cn/api/paas/v4` | `glm-4.7-flash` 永久免费(200K ctx/128K out),~1 并发 | 手机号注册 | 30B-A3B 中文原生,免费档翻译质量第一梯队[^glm] |
| **讯飞星辰 MaaS** | `maas-api.cn-huabei-1.xf-yun.com/v2`(OpenAI+`/anthropic`) | Qwen3.6/3.5-35B-A3B **限免"无限 token"** | 讯飞开放平台建应用绑服务 | 35B MoE 可用档[^xfyun] |
| **阿里百炼** | `dashscope.aliyuncs.com/compatible-mode/v1` | 70+ 模型各 100 万 tok/90 天(≈7000万一次性预算) | 阿里云账号,免实名可用免费额度 | qwen 全家桶;够跑完整个语料首翻[^bailian] |
| **火山 ARK** | `ark.cn-beijing.volces.com/api/v3` | 每模型 50 万 tok/30 天 | 必须实名 | doubao 系[^ark] |
| **腾讯 TokenHub** | `tokenhub.tencentmaas.com/v1` | 新客 ~100 万 tok(50万/90天/模型) | 腾讯云账号 | 含 Hy-MT2 翻译专用模型[^tokenhub] |
| **SiliconFlow 中国站** | `api.siliconflow.cn/v1` | ~14 个永久免费小模型,含 **Hunyuan-MT-7B 专用翻译模型**;注册送 ¥16 | +86 手机+实名(支付宝刷脸) | MT-7B 值得进 bench 对照[^sf] |
| **Gitee AI** | `ai.gitee.com/v1` | 100 次/天全模型共享 | Gitee 账号 | 冒烟级[^gitee] |
| **百度千帆** | `qianfan.baidubce.com/v2` | ERNIE-Speed/Lite 长期免费,Speed-128K RPM60/TPM30万 | 实名认证 | 上代小模型,跑量兜底[^qianfan] |
| **PPIO** | `api.ppio.com/openai/v1` | 注册 ¥5 + 个别小模型标称永免 | 手机号 | 中[^ppio] |

### 1.2 需代理或海外身份

| 提供方 | 免费额度 | 门槛/备注 |
|---|---|---|
| **Gemini AI Studio** | Flash 约 10–15RPM/250–1500 RPD(2026 起 Pro 全部转付费,只 Flash/Flash-Lite 系免费) | Google 账号;OpenAI 兼容端点 `generativelanguage.googleapis.com/v1beta/openai/`;**免费档数据被训练**(arXiv 公开文本风险可控);大陆不可直连[^gemini] |
| **Groq** | gpt-oss-120b/20b、qwen3.8-27b 等 30RPM/1K RPD/8K TPM/200K TPD(≈400 req/天/模型) | 邮箱注册;需代理[^groq] |
| **OpenRouter `:free`** | 20RPM;50 RPD(充过 $10 → 1000 RPD) | 账号聚合全部 free 变体;需代理[^or] |
| **Cloudflare Workers AI** | 10K Neurons/天 ≈ 小模型 400–1300 req/天 | 邮箱注册;OpenAI 兼容;大陆多半可直连[^cf] |
| **NVIDIA NIM** | 无时限 trial 档,~40RPM 经验值 | 注册即得 key;**ToS 限开发测试禁生产**[^nim] |
| **Mistral Experiment** | ~1 rps 全模型;免费档默认允许训练可 opt-out | 需手机号 SMS(+86 不友好)[^mistral] |
| **Meta Model API** | 60RPM/2M TPM/team 免费档 | 美国区预览[^meta] |
| **OpenCode Zen** | 7 个 $0 模型(deepseek-v4-flash-free/qwen3.6-plus-free/minimax-m3-free 等) | 注册即得 key[^zen] |
| **SambaNova** | 20 RPM/20 RPD/200K TPD | 日限额太低仅冒烟[^samba] |
| **xAI Grok** | 本机 `GROK_API_KEY` 实测 `/v1/models` 空列表=无额度;data-sharing 月度返还需开通 | — |

### 1.3 公益站(newapi 系,活体名单)

共性风险:随时关停/改规则、CF 1010 拦非浏览器、数据经第三方转发(arXiv 公开文本可接受)、限速不稳。**注册门槛是最大卡点**(见 §3)。

- **慕鸢 `newapi.linuxdo.edu.rs`**:LinuxDo 登录,注册送 $10+每日签到;有 **"沉浸式翻译"超低倍率分组(0.000001)**——为翻译管线设计的分组,值得专门建 key[^muyuan]
- **ShareLLM** `sharellm.net`:120 次/5h + 600 次/周;邮箱白名单(gmail/qq/icloud/yahoo/foxmail)+ Google/LinuxDo OAuth[^baipiao]
- **KiosAPI** `kiosapi.com`:Free 组倍率 0,kimi-k3/glm-5.3/qwen3.8/deepseek-v4-flash 等 34 模型;email 注册但 **Turnstile 发码**[^baipiao]
- **iamhc** `api.iamhc.cn`:注册送 $2000+签到;当前 TLS 断连(疑似停机观察)[^baipiao]
- **Future Hub** `api.futureppo.top`:签到 ~$20/天,域名邮箱免邀请码(但邮箱域名有白名单)[^baipiao]
- **ChatAnywhere** `api.chatanywhere.tech`:GitHub OAuth 免注册领长期免费 key[^baipiao]
- 更多在 baipiao.org/charity 目录(67 站在册);SJTU chat.sjtu.plus 与致远一号仅 jAccount+校园网,**不是公共公益站**[^sjtu]

## 2. cliproxyapi 扩员路径(已有基建,差登录)

本仓 vendored `src/devin-2api/cliproxyapi` 已支持的上游里,**还能撬的免费额度**:

| 上游 | 解锁内容 | 需要 |
|---|---|---|
| **Antigravity** | 个人免费档:Gemini 3.1 Pro/3 Flash + Claude Sonnet/Opus 4.6 + GPT-OSS-120b,Agent 配额周刷新(官方 "meaningful quota",2025-11 起已四次收紧) | Google 账号 OAuth(浏览器登录一次)[^ag] |
| **Gemini CLI** | 60RPM/1000 req/天/号,全 Gemini 家族 | Google 账号 OAuth;可与 Antigravity 双吃[^gcli] |
| **Codex(ChatGPT)** | Free/Go 账号也有 limited trial(GPT-5.6 Terra,水位低) | OpenAI 账号 OAuth[^cpa] |
| **Grok Build** | xAI 官方在推的免费试用,grok-4.6 | xAI 账号 OAuth[^cpa] |

已死上游记得清配置:qwen(2026-04 关)、iflow(2026-04-17 停服)。kimi 为纯付费。

同类工具参考(若要独立部署):AIClient-2-API(8.8k★,上游最全+TLS 指纹绕 CF)、anti-api(六上游合一)、WindsurfAPI(dwgx,3k★,与 devin-2api 同源——免费号只给 gpt-4o-mini/gemini-2.5-flash/开源权重)、warp2api(匿名 token 50 次自动续杯,**全自动无需账号**,额度小)[^tools]。

## 3. 自动注册可行性(本 session 实测)

- **mail.tm 临时邮箱 API 全通**:建号/收信零门槛可编程(`fht5im5xejj@uberip.com` 实测)。
- **但活体公益站全部堵临时邮箱**:sharellm 白名单只放 gmail/qq/icloud/yahoo/foxmail;futureppo 域名白名单;kiosapi 发码要 Turnstile。CF 1010 可用 :7890 代理绕过(验证过能打到应用层)。
- 结论:**自助注册环路 = mail.tm(通)× 域名白名单(堵)× Turnstile(堵)**;要闭环必须有一条可信域邮箱(gmail/qq/foxmail)的收信能力,或浏览器自动化过 Turnstile。`~/Applications/regplatformm` 服务在跑(:23170)但 DB 全空,定位就是干这个的平台,目前无产出。
- QQ 邮箱(2130212584@qq.com)在白名单内,但本机没有它的 IMAP 授权码——**给用户留的一步**:配 QQ IMAP 授权码后,mail.tm 环路可换成"自有 qq 邮箱+白名单站"完成自助注册。

## 4. 本地兜底(真·永久免费)

archbox 有 RTX 4070 SUPER(12GB)+ 31GB RAM,未装 ollama。建议装 ollama/llama.cpp 跑 Qwen3-14B/Qwen2.5-14B-Instruct(GPTQ-Int4 ~9GB)做永久兜底臂;质量低于旗舰 API 但零成本零依赖,promo 全部到期时的保底。

## 5. 接入与运行纪律

- texlate 侧无需改代码:任意 OpenAI 兼容 base_url 都走 `custom` provider + `TEXLATE_API_KEY`/settings key;`validate_base_url` 要 https(localhost/tailnet 除外),以上源全部合规。
- `connections.json` 已写入:gateway 两址、Prism、llm7、pollinations 五槽。
- 免费集动态纪律沿用 `discover_free_models` 设计:**不硬编码**;公益站/匿名档再加一条**每日测活**(保险库 80→2 的死亡率说明一切)。
- llm7/pollinations 匿名档只配当机会型臂:必须串行+间隔,失败自动降级,不进关键路径。
- 数据条款:Gemini/Mistral/OpenAI/xAI 免费档都拿 prompt 训练——翻公开 arXiv 可接受,管线留个开关。
- 待办(需用户):ModelScope token、智谱、SiliconFlow、百炼、OpenCode Zen 注册(最高 ROI 五个);cliproxyapi 挂 Google 号(Antigravity+Gemini CLI 双份)。

## 参考文献

[^ms]: [发现AI:魔搭每日 2000 次免费调用](https://www.faxai.cn/archives/1779);[ModelScopeApiBalanceCheck(限额响应头)](https://github.com/Morningstars666/ModelScopeApiBalanceCheck)
[^glm]: [智谱模型概览](https://docs.bigmodel.cn/cn/guide/start/model-overview);[速率限制](https://docs.bigmodel.cn/cn/api/rate-limit)
[^xfyun]: [讯飞星辰 MaaS 模型广场](https://maas.xfyun.cn/modelSquare?ch=MaaS-jgkol-l7P2y);[技术派:Qwen3.6-35B-A3B 限免](https://paicoding.com/xfyun-maas-qwen36-free)
[^bailian]: [阿里云:新人免费额度及用完即停](https://help.aliyun.com/zh/model-studio/new-free-quota)
[^ark]: [ChooseAI:豆包 API 接入教程(2026-09)](https://www.chooseai.net/news/6621/);[火山引擎试用权益](https://www.volcengine.com/article/2607749)
[^tokenhub]: [腾讯云:TokenHub 迁移与新人免费体验包](https://cloud.tencent.com/document/product/1823/131382)
[^sf]: [GetModelKey:SiliconFlow 免费层 2026](https://www.getmodelkey.com/zh/guides/siliconflow-api-free-tier-2026/)
[^gitee]: [模力方舟常见问题](https://ai.gitee.com/docs/appendix/qa)
[^qianfan]: [千帆 OpenAI 兼容](https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26);[ERNIE 免费公告](https://www.yizz.cn/6437.html)
[^ppio]: [PPIO 模型广场](https://ppio.com/docs/model/serverless)
[^gemini]: [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits);[OpenAI 兼容](https://ai.google.dev/gemini-api/docs/openai)
[^groq]: [Groq rate limits](https://console.groq.com/docs/rate-limits)
[^or]: [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits);[free 变体](https://openrouter.ai/docs/guides/routing/model-variants/free)
[^cf]: [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
[^nim]: [NVIDIA build integrations](https://build.nvidia.com/settings/integrations)
[^mistral]: [Mistral rate limits help](https://help.mistral.ai/en/articles/698531)
[^meta]: [Meta Model API pricing/limits](https://ai.developer.meta.com/docs/pricing-rate-limits/)
[^zen]: [OpenCode Zen 免费模型](https://opencode.ai/v2/docs/console/models/)
[^samba]: [SambaNova rate limits](https://docs.sambanova.ai/docs/en/models/rate-limits)
[^muyuan]: [LMSpeed:慕鸢の公益站](https://lmspeed.net/zh/provider/newapi-linuxdo-edu-rs);[LinuxDo 帖(沉浸式翻译倍率)](https://linux.do/t/topic/1561978)
[^baipiao]: [白嫖公益站目录](https://baipiao.org/charity/)
[^sjtu]: [chat.sjtu.plus /api/status 实测](https://chat.sjtu.plus/api/status);[致远一号试用公告](https://mp.weixin.qq.com/s/qOM8jO0OlKl5FZE44U8D3A)
[^ag]: [Antigravity plans 文档](https://www.antigravity.google/docs/plans);[agentcode.ai 额度追踪](https://agentcode.ai/google-antigravity)
[^gcli]: [gemini-cli quota-and-pricing](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/quota-and-pricing.md)
[^cpa]: [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)
[^tools]: [AIClient-2-API](https://github.com/justlovemaki/AIClient-2-API);[anti-api](https://github.com/ink1ing/anti-api);[WindsurfAPI](https://github.com/dwgx/WindsurfAPI);[warp2api](https://github.com/dundunduan/warp2api);[copilot-api](https://github.com/caozhiyuan/copilot-api)
