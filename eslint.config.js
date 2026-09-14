// ESLint flat config：本仓 js 全是 bench/ts/ 下的 CommonJS bench 脚本。
// 无 ts——tsc --noEmit 对 untyped .js 无意义，不进链。
const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
    js.configs.recommended,
    {
        files: ["**/*.{js,mjs,cjs}"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "commonjs",
            globals: { ...globals.node },
        },
    },
    {
        ignores: [
            "bench/results/", // bench 脚本产出目录
            "bench/work_*/", // bench 重产物（gitignored）
            "bench/corpus/", // arXiv 语料（gitignored 子目录）
            "**/.venv*/", // python venv 内的 js
            ".crossnote/", // 本机软链层，事实源在 ~/.agents
            ".claude/",
            "**/*.min.js",
        ],
    },
];
