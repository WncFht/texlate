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
                cpSync(path.join(pdfjsDir, dir), path.join(out, dir), { recursive: true });
            }
            writeFileSync(
                path.join(rootDir, "dist/THIRD_PARTY_LICENSES.txt"),
                collectLicenses(),
            );
        },
    };
}

function collectLicenses(): string {
    const pkg = JSON.parse(readFileSync(path.join(rootDir, "package.json"), "utf8")) as {
        dependencies?: Record<string, string>;
    };
    let out = "TeXlate Web — Third-Party Licenses\n==================================\n";
    for (const name of new Set(Object.keys(pkg.dependencies ?? {}))) {
        try {
            const dir = path.dirname(require.resolve(`${name}/package.json`));
            const meta = JSON.parse(readFileSync(path.join(dir, "package.json"), "utf8")) as {
                version: string;
                license?: string;
            };
            const licFile = readdirSync(dir).find((f) => /^licen[sc]e/i.test(f));
            out += `\n## ${name}@${meta.version} — ${meta.license ?? "unknown"}\n\n`;
            if (licFile) out += readFileSync(path.join(dir, licFile), "utf8").trim() + "\n";
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

export default defineConfig({
    plugins: [solid(), pdfjsDevAssets(), ...(useMock ? [mockApiPlugin()] : []), pdfjsAssetsPlugin()],
    server: useMock
        ? { port: 5173 }
        : { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
    build: {
        target: "es2022",
        chunkSizeWarningLimit: 3200, // pdfjs 单包 ~3MB，属预期
    },
    test: {
        environment: "node",
        include: ["src/**/*.test.ts"],
    },
});
