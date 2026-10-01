# 导出电子书与共享译文包

两个相邻功能：`texlate export` 把 EPUB/DOCX 整本书翻成双语版；`texlate share` 把 arXiv 任务的译文打成可互传的 `.share.zip` 包。

## EPUB/DOCX 双语插译

```bash
texlate export 书.epub
texlate export 书.docx -o 输出.docx
```

产出同格式的新文件：每个原文段落后紧跟译文段落，书名缺省取 `{原名}_bilingual{原后缀}`。格式按文件内容嗅探——改后缀无效；带 DRM 声明、fixed-layout 版式或包体损坏的文档在翻译开始前即拒绝。

跑之前先配好 BYOK（见 `byok.md`）：没配 key 会自动回落成 mock 干跑（占位译文），stderr 有提示；`--mock` 显式干跑不触网，`TEXLATE_TRANSLATOR=gateway` 则反过来强制要求 key 在场。`--model` 覆盖默认模型，`--glossary` 挂自定义术语表（`.yaml` 或 `.csv`，叠加在内置默认表之上）。

翻几十万字的书是长任务：中断（Ctrl-C、断网、机器重启）不影响进度——现场留在 `{输出}.state/` 目录，同一条命令再跑一次自动从断点续翻，已翻部分不重复消耗配额。跑完打一行统计：插译了多少单元、多少未变/跳过/失败。

同一能力在网页里也有：上传 `.docx`/`.epub` 文件会建双语插译任务，走任务队列、断点续跑与产物下载面板（`web.md`）。

## 共享包

`.share.zip` 是「一篇论文的一次翻译」的可移植封装：`manifest.json`（自描述清单）+ 逐块译文源码包 `zh-src.zip` + 对照数据 `dual.json` + 可选的中文 PDF。包名里的 `share_key` 是内容寻址哈希——由论文 id、版本、模型、目标语言、提示词版本、管线版本、术语表哈希七组分算出，同一论文同一套配置打出来的包永远同名同键，自动去重。

用途是两个：把自己翻好的译文给别人，对方导入后无需消耗 token 就有产物；以及给公共缓存供稿——包放到任何静态托管/对象存储上就是共享源。

## 打包：`share pack`

```bash
texlate share pack t_9f3c...            # 任务 id 或 <数据目录>/tasks/t_... 目录都行
texlate share pack t_9f3c... -o out/    # 落 out/{share_key}.share.zip
```

只有终态任务能打包；七组分任一取不到（比如任务没钉版）会显式报错拒绝打包。`--contributor` 给自己署名，缺省是匿名随机标识。

网页侧等价物是阅读器/结果面板里的「分享本译文」按钮——打出的包落在 `TEXLATE_SHARE_DIR`（缺省 `<数据目录>/share/`）并附 `index.jsonl` 索引，把这个目录指到静态托管就完成了发布。首页高级选项的「完成后打共享包」可以在建任务时就把这一步挂上。

## 解包：`share unpack`

```bash
texlate share unpack xxx.share.zip
texlate share unpack xxx.share.zip -o 解到/
```

做全量机械校验：包格式、manifest 字段、share_key 与七组分自洽、逐产物 sha256 对账，任何不符报 `share_invalid` 拒绝。manifest 限 1MB、产物限 64 件、声明总量限 300MB——超限按坏包处理。

校验范围限于「包没坏、确实是它声称的那篇那次翻译」；译文可信度由导入后的消费端流程保证。

## 导入：网页上传 `.share.zip`

把共享包拖进首页上传框（或走 `POST /api/share/import`）会建一个 `share` 类任务：服务端先跑上面的全套校验，然后**在本地重跑拼译文→校验→编译的全链**——不调模型、不耗配额，但产物是真实编译出来的——坏译文在这一步即暴露。导入完成的任务同时登记进缓存键：之后任何人同配置请求同一篇论文，直接命中这份产物。
