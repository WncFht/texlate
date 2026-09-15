// web/ 独立 ESM 工程的 eslint flat config。刻意用 .cjs：仓库根 eslint
// 把一切 *.{js,mjs,cjs} 当 CommonJS lint，本文件必须能被根链解析。
const js = require("@eslint/js");
const globals = require("globals");
const tseslint = require("typescript-eslint");
const solid = require("eslint-plugin-solid");

module.exports = tseslint.config(
    {
        ignores: ["dist/", "node_modules/"],
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
        // 本文件自身：CJS 配置脚本，能被根链与本链同时解析
        files: ["**/*.cjs"],
        languageOptions: {
            sourceType: "commonjs",
            globals: { ...globals.node },
        },
        rules: {
            "@typescript-eslint/no-require-imports": "off",
        },
    },
    {
        files: ["src/**/*.{ts,tsx}", "dev/**/*.ts", "vite.config.ts"],
        languageOptions: {
            globals: { ...globals.browser, ...globals.node },
        },
        rules: {
            "@typescript-eslint/no-unused-vars": [
                "error",
                { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
            ],
        },
    },
    {
        files: ["src/**/*.{ts,tsx}"],
        ...solid.configs["flat/typescript"],
    },
    {
        // 测试与 dev 中间件放宽 non-null/assertion 纪律
        files: ["src/**/*.test.ts", "dev/**/*.ts", "vite.config.ts"],
        rules: {
            "@typescript-eslint/no-non-null-assertion": "off",
            "@typescript-eslint/no-explicit-any": "off",
        },
    },
);
