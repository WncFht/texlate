# Dockerfile 实构建冒烟报告（2026-09-16）

对象：根目录 `Dockerfile`（三阶段：node:22-bookworm-slim 构建 SPA → python:3.12-slim 取 tectonic 0.17.0 musl 二进制 sha256 钉死 → runtime + uv sync + fonts-noto-cjk）。构建日志留档 `build.log`。

## 结论

**实构建成功、冒烟全绿**。镜像 `texlate-smoke:latest` 655MB，端到端构建 127s（含基础镜像拉取；daemon 走 127.0.0.1:7890 代理）。Dockerfile 零 bug，未改任何文件。

## 构建过程

- `web` 阶段：`npm ci` 装 256 包 6.3s（package-lock 与 package.json 同步），`vite build` 9.2s 出 `dist/`（含 pdfjsAssetsPlugin 拷入的 cmaps/standard_fonts/wasm + THIRD_PARTY_LICENSES.txt）。
- `tectonic` 阶段：GitHub release musl 二进制下载后 `sha256sum -c` 通过（amd64 pin `8533d07f…` 正确），`Tectonic 0.17.0` 自验打印。阶段耗时 12.3s。
- `runtime` 阶段：apt 装 `ca-certificates + fonts-noto-cjk`；`COPY --from=ghcr.io/astral-sh/uv:0.11.29` 取 uv；`uv sync --frozen --extra server` 5.1s，装出 `texlate==0.1.0` editable（`_editable_impl_texlate.pth` → `/app/src`，与 Dockerfile 注释所述一致）。

## 冒烟结果

- `docker run --rm texlate-smoke --help` → typer 全命令面正常；`version` → `texlate 0.1.0`。
- `docker run -d -p 18877:8765 texlate-smoke`（宿主 8765 被常驻 dev 实例占用，换端口）：uvicorn 起在 0.0.0.0:8765，`/api/health` → `{"ok":true,"version":"0.1.0","compilers":{"tectonic":true,"xelatex":false,"babeldoc":false},"data_dir":"/data"}`（TEXLATE_DATA_DIR 生效；xelatex 缺位符合预期——tectonic 变体本就如此）。
- `GET /` → 200 `index.html`（745B）；`/assets/index-*.js`（1.05MB）、`*.css`（282KB）、`/pdfjs/cmaps/*.bcmap` 均 200。SPA 是手写 hash 路由（App.tsx `#/` `#/reader/:id` `#/settings`），`StaticFiles(html=True)` 无 history-fallback 需求，深链 404 不是问题。
- **产品 e2e**：容器内 `texlate run /tmp/proj --engine tectonic`（手写最小 article）全链跑通——normalize → mock 翻译 → ctex fandol 注入 → tectonic 编译 4.13s → verdict `clean`，出 PDF 4419B。verdict notes 带 `cjk_unverified(pdftotext absent)`。
- 镜像内核查：`/app/src/texlate/server/static/index.html` + assets + pdfjs 在位；`tectonic` 在 `/usr/local/bin`；`User=texlate`、`ENTRYPOINT=["texlate"]`、`CMD web --host 0.0.0.0 --port 8765`、`EXPOSE 8765`、`VOLUME /data` 均正确。

## 发现清单

### Dockerfile 层（建议级，非 bug）

1. `uv sync --frozen --extra server` 把 dev group（pytest/pytest-asyncio）装进了运行时镜像（`.venv/bin/pytest` 在位）。加 `--no-dev` 可剔除，省几 MB 并收面。
2. `fonts-noto-cjk` 没带 `fontconfig`/`libfontconfig1`（`--no-install-recommends`）：镜像内无 `fc-list`、无 `/etc/fonts/fonts.conf`、无 `libfontconfig.so`。实测影响是**装饰性的**——tectonic 静态 musl 内置 fontconfig，打 `Fontconfig error: Cannot load default config file` 噪音后走内置默认扫描目录，`/usr/share/fonts/opentype/noto/` 的 4 个 ttc 仍被按名解析（`\setCJKmainfont{Noto Sans CJK SC}` 实测出 PDF，Regular+Bold 都命中）。产品代码无任何 `fc-list` 调用。若想让日志干净+保 fc-* 调试工具，加 `fontconfig` 包（~2MB）。
3. 无 `poppler-utils` → judge 的 pdftotext CJK 字数核验降级为 `cjk_unverified` note（不判错，但核验闸弱化）。若交付形态要保证 zh.pdf 字数断言，考虑加装（~5MB）；这是「是否要补」的产品判断，现状可降级运行。
4. texlive 变体注释（第 12–14 行）：`apt-get install texlive-xetex …` 这段若照字面**追加到文件末尾**会以 `USER texlate` 身份跑而失败——追加位置必须在 `USER texlate` 之前（或临时 `USER root`）。包名对 debian trixie 合法，未实构建。

### 环境/工具链层（非 Dockerfile 问题）

5. 本机 docker 29.8.0 未装 buildx 插件 → 默认 legacy builder，不支持 `--progress` 与 `COPY --from=<外部镜像>`。装 `extra/docker-buildx 0.37.1-1` 后走 BuildKit 正常。**`COPY --from=ghcr.io/…/uv` 是 BuildKit-only 语法**，无 buildx 的环境必挂——CI/文档应声明要求。
6. RUN 步骤网络：docker CLI 会把 shell 的 `HTTP(S)_PROXY=http://127.0.0.1:7890` 自动转成 build-arg 注入 RUN env，但 bridge 网络下容器内 127.0.0.1 是容器自身 → 需 `--network=host`（本次用法）或改指宿主网关。文档里「docker build -t texlate .」裸命令在代理宿主上会失败，值得一行备注。
7. 宿主 8765 被常驻 dev 实例占用（live-smoke 在用）→ 冒烟改 18877；非问题。

### 运行时观察（ops 提示）

8. tectonic 首次编译要联网拉 bundle（缓存在 texlate 用户 `~/.cache/Tectonic`，即 `/home/texlate`，不在 `/data` volume）。离线/气隙部署需预热缓存；容器重建后 bundle 需重拉（可把 cache 也挂卷）。
9. `web/dev/` 被 .dockerignore 保留是必需的——`vite.config.ts` 顶层静态 `import { mockApiPlugin } from "./dev/mock-api.ts"`，删掉会让镜像内 build 挂。当前写法正确，仅备注此耦合。

## 复核命令

```sh
docker buildx build --load --network=host -t texlate-smoke .   # 代理宿主
docker run -d -p 18877:8765 texlate-smoke                      # 8765 被占时换端口
curl localhost:18877/api/health
```

镜像 `texlate-smoke:latest` 留在本机 docker，容器已清理。
