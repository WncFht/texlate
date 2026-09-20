# syntax=docker/dockerfile:1
# TeXlate 服务端形态（docs/research/product/web-layer.md §6）：
#   阶段 1 node 构建 SPA → 阶段 2 取 tectonic musl 静态二进制（sha256 钉死）
#   → 阶段 3 python:3.12-slim + uv sync + fonts-noto-cjk。
#
#   构建:  docker build -t texlate .   （需 buildx/BuildKit：`COPY --from=<外部镜像>`
#   是 BuildKit-only；代理宿主的 RUN 要走宿主网络：`--network=host`）
#   运行:  docker run -p 8765:8765 -v texlate-data:/data texlate
#   其他子命令: docker run --rm texlate fetch 1706.03762
#
# TeXLive xelatex 变体（texlate:full，高成功率编译档，镜像 ~4GB）：
# 在 runtime 阶段追加——必须加在 `USER texlate` 之前（或临时 USER root）：
#   RUN apt-get update && apt-get install -y --no-install-recommends \
#         texlive-xetex texlive-lang-chinese texlive-latex-extra latexmk \
#       && rm -rf /var/lib/apt/lists/*
# `route_project` 的 [tectonic, xelatex] 双引擎序即自动生效。

ARG NODE_VERSION=22
ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- web SPA
FROM node:${NODE_VERSION}-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ------------------------------------------------------ tectonic 二进制
# 官方 GitHub release musl 静态构建，校验和钉死（linux amd64/arm64 两档；
# 全五平台矩阵见 docs/spec/compile.md 分发规格）。
FROM python:${PYTHON_VERSION}-slim AS tectonic
ARG TECTONIC_VERSION=0.17.0
ARG TECTONIC_SHA256_AMD64=8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7
ARG TECTONIC_SHA256_ARM64=b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && set -eu; \
    case "$(uname -m)" in \
        x86_64) sha="$TECTONIC_SHA256_AMD64"; arch=x86_64 ;; \
        aarch64) sha="$TECTONIC_SHA256_ARM64"; arch=aarch64 ;; \
        *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/tectonic.tar.gz \
        "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${arch}-unknown-linux-musl.tar.gz"; \
    echo "${sha}  /tmp/tectonic.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
    rm /tmp/tectonic.tar.gz; \
    tectonic --version

# ------------------------------------------------------------- 运行时
FROM python:${PYTHON_VERSION}-slim AS runtime

# fontconfig：消 tectonic 内置 fontconfig 的 default-config 噪音（~2MB）；
# poppler-utils：judge 的 pdftotext CJK 字数核验依赖它，缺席降级 cjk_unverified。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates fonts-noto-cjk fontconfig poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tectonic /usr/local/bin/tectonic /usr/local/bin/tectonic
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# web/dist → server/static 约定（web-package 的 wheel force-include 同款落位；
# 镜像内 editable 安装直接以 src 树为包根，static 即装即用）。
COPY --from=web /web/dist ./src/texlate/server/static

RUN uv sync --frozen --no-dev --extra server

# BabelDOC sidecar 未随镜像分发（AGPL 进程边界 + 2GB 体积）——
# 如需 PDF 上传通路，另行 `uv pip install babeldoc` 或挂宿主二进制。

RUN useradd --create-home --uid 10001 texlate \
    && mkdir -p /data \
    && chown -R texlate:texlate /data /app
USER texlate

# TEXLATE_MODE=server：跳过 local_only CSRF 中间件（正式部署应前置反代做
# CORS allowlist）；tenant 按 key 指纹分槽。Redis 队列后端（REDIS_URL）
# 规格留了位但尚未实现——当前为单进程 SQLite 队列。
ENV PATH="/app/.venv/bin:${PATH}" \
    TEXLATE_DATA_DIR=/data \
    TEXLATE_MODE=server

VOLUME /data
EXPOSE 8765

ENTRYPOINT ["texlate"]
CMD ["web", "--host", "0.0.0.0", "--port", "8765"]
