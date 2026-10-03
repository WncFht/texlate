# Changelog

格式遵 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 首个公开发布：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译双语 PDF 全链。
- 分发三通道：PyPI wheel（内置 SPA，`uv tool install texlate` 即用）、ghcr 双架构镜像、Zotero xpi（Releases + update feed 自更新）。
- CLI 九命令：`fetch`/`parse`/`run`/`web`/`export`/`share`/`doctor`/`version`/`tools`。
- `run --server` 瘦客户端、`share pack/unpack` 内容寻址译文共享包、`export` EPUB/DOCX 双语插译。
- fixloop 编译修复引擎：262 条规则 / 121 类错误。
- Web 阅读器：双语对照句级对位、滚动同步、引用悬浮卡、暗色图元级改色。
- `TEXLATE_MODE=server` 多用户部署形态（`X-Texlate-Key` 鉴权 + 配额 + 保留期清扫）。

### Notes

- server 依赖（fastapi/uvicorn/sse-starlette/python-multipart）在 core——无 extras 面，`uvx texlate web` 裸装即用。
- BabelDOC sidecar 不随发布物分发（AGPL 进程边界），PDF 上传通路需另行 `pipx install babeldoc`。
