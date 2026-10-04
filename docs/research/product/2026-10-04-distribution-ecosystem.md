# 分发渠道与社区生态：v0.1.0 后全景

> **结论**：分发技术面已闭环——PyPI/uvx、Release 三件套、Zotero update feed、ghcr 双架全在线。剩余增量全部在「被发现」面：Zotero 插件两个注册渠道（zotero-addons-scraper、zotero-plugin-registry）+ GitHub Discussions + 样例产出入 README。brew、自建文档站、Docker Hub 均判否。
> **状态**：现行（行动清单第 1/2 项待执行）
> **日期**：2026-10-04

## 1. 已闭环分发面（v0.1.0 实测）

| 渠道                    | 形态                                                   | 状态                          |
| ----------------------- | ------------------------------------------------------ | ----------------------------- |
| PyPI `texlate`          | `uvx texlate` / `uv tool install` / `pipx`             | 在线（0.1.0）                 |
| GitHub Release `v0.1.0` | whl + sdist + `texlate.xpi` 三件套                     | 在线                          |
| Zotero 更新 feed        | floating `release` tag 挂 update.json/update-beta.json | 在线，manifest updateURL 可达 |
| ghcr.io                 | `ghcr.io/wncfht/texlate:{0.1.0,latest}` amd64+arm64    | 在线，CI 内镜像冒烟           |
| 版本一致性              | tag ↔ pyproject ↔ zotero/package.json 三方断言         | release.yml 发布闸前置        |

发布链一处踩坑记录：PyPI trusted publisher 字段逐字节比对 OIDC claims——workflow 名是 `release.yml` 而非 `release.yaml`，environment 必须留空（claims 中 `environment: None`，填任何值即 `invalid-publisher`）。pending publisher 无审核环节，保存即生效。

## 2. 对标：pdf2zh/PDFMathTranslate（37k★，同生态位最近者）

| 面          | pdf2zh 做法                                                         | texlate 现状   | 判断                                                    |
| ----------- | ------------------------------------------------------------------- | -------------- | ------------------------------------------------------- |
| PyPI        | `pdf2zh` 在架                                                       | 已对齐         | —                                                       |
| Docker      | 仓内 Dockerfile+compose，自包含单镜像                               | ghcr 双架      | 已更好                                                  |
| Zotero 插件 | 第三方社区 repo（zotero-pdf2zh，7k★），GitHub Releases+中文商店分发 | 官方一仓维护   | 同渠道可进                                              |
| 文档站      | 自有域名站（JS 渲染）+ 仓内多语言 README                            | README+docs/   | 文档站判否：README 够用；多语言 README 等英文版先稳     |
| 社区        | Discussions 关闭，issue+wiki 模式                                   | Discussions 关 | 中文科研受众 Q&A 会灌 issue——开会话成本低、防污染收益实 |

## 3. Zotero 插件上架生态（格局已变）

- **官方插件列表不存在**。zotero.org/support/plugins 明示 "We don't currently provide a list of available plugins"，官方目录仅 "planned"；惯例渠道是 Zotero Forums 发公告帖。
- **中文商店旧后端已冻结**：`zotero-chinese/zotero-plugins` 2026-06 归档，README 指路新提交去 `syt2/zotero-addons-scraper`。
- **`syt2/zotero-addons-scraper` 是当前中文商店活后端**：PR 加一条 `PluginInfo{repo, releases:[{targetZoteroVersion, tagName}]}` 即上架。texlate 的 versioned release 已挂 `texlate.xpi`，天然契合——中文 Zotero 用户最大流量入口。
- **`zotero-plugin-dev/zotero-plugin-registry` 是下一代国际注册表**：PR 交 `plugins/<id>/meta.json`（id/name/update_json/description/homepage/tags）。floating `release` tag 的 update.json 已在线，提交成本近零——官方目录成型时先入先收。

## 4. Homebrew 判否

`yt-dlp` 证明 pypi app 进 homebrew-core 可行（`Language::Python::Virtualenv` + `pypi_packages` + 逐依赖 `resource` 块）。但 homebrew-core 有知名度门槛（惯例 ≥75★/30 fork），自建 tap 要养 formula+更新自动化。且 `depends_on "tectonic"` 的边际收益已被 `uvx texlate` + `texlate tools install-tectonic` 两步覆盖。stars 起来后 homebrew-core 自然可进，现在投是过度投资。

## 5. 行动清单（按杠杆率）

| #   | 动作                                                                                        | 成本   | 状态         |
| --- | ------------------------------------------------------------------------------------------- | ------ | ------------ |
| 1   | `syt2/zotero-addons-scraper` 上架 PR（PluginInfo 条目）                                     | 半小时 | 备好，待放行 |
| 2   | `zotero-plugin-dev/zotero-plugin-registry` 交 `plugins/texlate/meta.json`                   | 半小时 | 待执行       |
| 3   | 开 GitHub Discussions（Announcements / Q&A / Show and tell 三类）                           | 十分钟 | 待执行       |
| 4   | README 挂 2-3 篇真实双语产出样例（截图 + PDF）——翻译工具的说服力即输出质量                  | 一晌   | 待执行       |
| 5   | Zotero Forums 英文公告帖（v0.1.0 + `uvx texlate` 一行装 + xpi 商店可查）；V2EX/知乎同期一波 | 一晌   | 依赖 #1/#4   |

不做清单：brew（门槛+边际）、自建文档站、Docker Hub（ghcr 已双架）、Zotero 官方列表（不存在）、公共 demo 实例（需托管 LLM key，不现实）。

## 6. 残留技术缺口（非分发面，随下一版排期）

- 升级路径文档只覆盖 `uv tool upgrade`；docker/git 两形态升级命令未写。
- `texlate --version` flag 不存在（只有 `version` 子命令）。
- 未 build-web 的树 `uv build` 静默产无-SPA wheel（release.yml 有断言兜住，本地裸 build 无提示）。
- 上游停滞无看门狗：饱和网关下单请求可挂 10min+（keepalive 字节重置 httpx read 超时），界面只见「翻译中」冻结。
- Zotero 手动拷 xpi 进 extensions/ 踩 sideload 同意闸（userDisabled），文档可补「从文件安装」一句。mac dev-verify 链 Linux-only（xvfb 依赖）。

证据面：pdf2zh/zotero-addons-scraper/zotero-plugin-registry/zotero-chinese 归档声明/yt-dlp formula/Homebrew Python-for-Formula-Authors/zotero.org plugins 页，2026-10-04 逐站核验。
