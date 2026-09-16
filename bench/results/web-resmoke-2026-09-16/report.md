# web-resmoke-2026-09-16：app-polish（9368872）落地后 web e2e 复验

两臂全绿 + 20 项新契约探针全过，无产品代码改动。

## 臂 1：dev-smoke.sh（vite+mock+playwright）——29/29 PASS

含 doc 契约项：k-doc 徽标、zh.docx/zh.epub 行内下载链、docx 上传 reader_url 缺席不崩、产物面板非 fatal、无 console 错误。截图在 web/scripts/shots/。

## 臂 2：server-smoke.sh（真后端 :8931）——全 PASS

health / SPA 200 text/html / openapi 15 路由 / upload .tex→202 带 reader_url / SSE done 事件 / zh.pdf·dual.json·compile.log·zh-src.zip 四件 sha256 齐 / 端口回收干净。

## 臂 3：扩展契约探针（真后端 :8932，MockTranslator 无 key 配置）

| 探针 | 结果 |
|---|---|
| upload docx/epub `_accepted` | 无 reader_url ✓ |
| upload tex / arxiv translate | 有 reader_url ✓ |
| translate options=string | 400 ✓ |
| x-texlate-base-url 非法 | 400（_auth ValueError）✓ |
| settings PUT 未知键（纯/混） | 400 ✓；已知键 200 ✓ |
| retry done 任务 | 409 invalid_transition ✓ |
| retry fault + {bogus}/{options:string}/{model} | 全 400 ✓ |
| retry fault + {main,options} | 202 queued（docx 响应仍无 reader_url）✓ |
| src.tar mime | tex→octet-stream、docx→docx mime、epub→epub+zip、arxiv→gzip ✓ |
| Content-Disposition | filename 白名单化 ✓ |
| reader done tex → 200；docx → 404「dual.json 未产出」 | ✓ |
| reader 非 dict dual.json/documents | 500 {"code":"internal"} 结构化 ✓ |
| 孤儿清理 | quota 429 入队失败无残留；idempotent 命中 blob 目录被收 ✓ |

## 附带实测

arxiv 任务 2501.14787 意外走了真链路——DEFAULT_BASE_URL 是免 key 网关 100.105.212.52:3003（swe-2-medium）：760 chunks 真翻译完成，终态 partial（14 个 undefined_cs、L2 重译、fixloop tectonic dirty_pdf、retryable:True）。全链 worker 管线真实可用，partial 是该论文编译质量问题非契约问题。reader/partial 任务 200 正常。→ 该 partial 已另派 repro-2501 归因。

## 环境说明

docx/epub fixture 太小导致两任务 fault（最小 zip 缺内部件）——只影响内容层，契约断言不受影响。探针数据在 /tmp/tw-8931、/tmp/tw-8932，进程已全部回收。
