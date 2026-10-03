# 安全政策

## 支持版本

| 版本     | 状态        |
| -------- | ----------- |
| 最新 tag | ✅ 接收修复 |
| 更旧版本 | ❌ 不再维护 |

项目处于 0.x 阶段，只维护最新发布版。

## 报告漏洞

走 GitHub 私密渠道：[Security → Advisories → Report a vulnerability](https://github.com/WncFht/texlate/security/advisories/new)。

**不要开公开 issue 报安全问题。** 收到报告后我们会在确认可复现后修复并发布 advisory；如需署名致谢请在报告里注明。

## 值得报告的面

- 上传解包路径穿越（`zip`/`tar` 成员逃逸任务目录）
- local 形态鉴权绕过（Host 白名单 / Origin 检查 / loopback peer 闸）
- server 形态（`TEXLATE_MODE=server`）下 `X-Texlate-Key` 校验缺陷
- API key / BYOK 凭据泄漏（日志未脱敏、错误面回显、跨租户读）
- prompt/占位符注入导致的译文完整性破坏
- 依赖供应链问题（先查 `deps-audit.yml` 的周期扫描是否已捕获）

## 不视为漏洞的面

- 本机 loopback 服务对本机其他进程开放——local 形态的设计前提（多用户部署请用 `TEXLATE_MODE=server` + `X-Texlate-Key`）
- `babeldoc` sidecar 的自身缺陷——归上游 [funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC)
- 用户自备端点（`TEXLATE_BASE_URL`）的不可信行为
