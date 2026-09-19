import { defineConfig, type Plugin } from "vitest/config";
import solid from "vite-plugin-solid";
import { cpSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mockApiPlugin, pdfjsAssetsMiddleware } from "./dev/mock-api.ts";

const require = createRequire(import.meta.url);
const rootDir = path.dirname(fileURLToPath(import.meta.url));
const pdfjsDir = path.dirname(require.resolve("pdfjs-dist/package.json"));

// 默认 mock ON（无后端也能起 demo）；VITE_MOCK_API=0 → 走 §5.5 的 /api 代理
const useMock = process.env.VITE_MOCK_API !== "0";

/** build 收尾：pdfjs 静态资源进 dist/pdfjs/ + 依赖许可证汇总（texglot 模式） */
function pdfjsAssetsPlugin(): Plugin {
    return {
        name: "texlate-pdfjs-assets",
        apply: "build",
        closeBundle() {
            const out = path.join(rootDir, "dist/pdfjs");
            for (const dir of ["cmaps", "standard_fonts", "wasm"]) {
                cpSync(path.join(pdfjsDir, dir), path.join(out, dir), {
                    recursive: true,
                });
            }
            writeFileSync(
                path.join(rootDir, "dist/THIRD_PARTY_LICENSES.txt"),
                collectLicenses(),
            );
        },
    };
}

function collectLicenses(): string {
    const pkg = JSON.parse(
        readFileSync(path.join(rootDir, "package.json"), "utf8"),
    ) as {
        dependencies?: Record<string, string>;
    };
    let out =
        "TeXlate Web — Third-Party Licenses\n==================================\n";
    for (const name of new Set(Object.keys(pkg.dependencies ?? {}))) {
        try {
            const dir = path.dirname(require.resolve(`${name}/package.json`));
            const meta = JSON.parse(
                readFileSync(path.join(dir, "package.json"), "utf8"),
            ) as {
                version: string;
                license?: string;
            };
            const licFile = readdirSync(dir).find((f) =>
                /^licen[sc]e/i.test(f),
            );
            out += `\n## ${name}@${meta.version} — ${meta.license ?? "unknown"}\n\n`;
            if (licFile)
                out +=
                    readFileSync(path.join(dir, licFile), "utf8").trim() + "\n";
        } catch {
            /* 解析不到就跳过该依赖 */
        }
    }
    return out;
}

function pdfjsDevAssets(): Plugin {
    return {
        name: "texlate-pdfjs-dev-assets",
        apply: "serve",
        configureServer(server) {
            server.middlewares.use(pdfjsAssetsMiddleware(pdfjsDir));
        },
    };
}

/**
 * @pdfslick/core 的 dist 在模块顶层写了
 * `workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url)`——
 * 指向其 vendored 副本，build 时被静态分析产出第二份 ~1.26MB worker 资产。
 * 运行时 PdfPane 挂载即 ensurePdfjsWorker() 覆盖为顶层 pdfjs-dist 版
 * （见 src/pdfjs.ts），vendored 引用纯死重：把该表达式改写为 ""，
 * 切断静态引用，产物里少一份 worker。
 */
function pdfslickWorkerDedup(): Plugin {
    const WORKER_URL =
        /new URL\(['"]pdfjs-dist\/build\/pdf\.worker\.min\.mjs['"],\s*import\.meta\.url\)\.toString\(\)/;
    return {
        name: "texlate-pdfslick-worker-dedup",
        transform(code, id) {
            if (!id.includes("@pdfslick") || !WORKER_URL.test(code))
                return null;
            return { code: code.replace(WORKER_URL, '""'), map: null };
        },
    };
}

/**
 * KaTeX 字体只留 woff2：katex.min.css 的 @font-face src 三格式并列且
 * woff2 居首——现代浏览器命中即停，ttf/woff 两份资产从未被请求（~4MB
 * dist 死重）。旧浏览器拿不到回退格式，但 es2022 目标本就放弃了它们。
 */
function katexWoff2Only(): Plugin {
    return {
        name: "texlate-katex-woff2-only",
        apply: "build",
        generateBundle(_opts, bundle) {
            for (const key of Object.keys(bundle)) {
                if (/KaTeX_.*\.(?:ttf|woff)$/.test(key)) delete bundle[key];
            }
        },
    };
}

export default defineConfig({
    plugins: [
        solid(),
        pdfjsDevAssets(),
        pdfslickWorkerDedup(),
        katexWoff2Only(),
        ...(useMock ? [mockApiPlugin()] : []),
        pdfjsAssetsPlugin(),
    ],
    server: useMock
        ? // strictPort：smoke.mjs 等外部脚本按 5199 直连——漂移必须显式失败而非静默换口
          { port: 5199, strictPort: true }
        : {
              port: 5199,
              strictPort: true,
              proxy: {
                  "/api": {
                      target: "http://127.0.0.1:8765",
                      changeOrigin: true,
                      // 后端同源闸比 Origin netloc vs Host——浏览器 Origin
                      // 带 vite 端口，不改写则 mutating API 一律 403。
                      // headers 选项不覆盖已存在的 Origin——须走 proxyReq
                      // 钩子在出向请求上 setHeader
                      configure(proxy) {
                          proxy.on("proxyReq", (req) => {
                              req.setHeader(
                                  "origin",
                                  "http://127.0.0.1:8765",
                              );
                          });
                      },
                  },
              },
          },
    build: {
        target: "es2022",
        // Reader 分包后最大块是 reader-*.js（pdfjs 全家桶 ~1MB）——
        // 阈值压到刚好看住它，壳层 chunk 异常膨胀会告警
        chunkSizeWarningLimit: 1100,
    },
    test: {
        environment: "node",
        include: ["src/**/*.test.ts"],
    },
});
