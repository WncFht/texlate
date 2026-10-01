#!/usr/bin/env node
// TeXlate cst 译文结构校验 worker —— tree-sitter-latex CST + 占位符契约 diff。
// 随 wheel 作 package data 分发（texlate.validate/ts/）。
//
// 协议（stdin/stdout JSONL，每行一 record）：
//   {"id":"...", "tex":"<latex 源码>"}                 内联源码
//   {"id":"...", "path":"/abs/file.tex"}               文件源码
//   可选 "expect":["MATH_1","MATH_2",...]              scanner 侧占位符契约
//   可选 "baseline":{"parse_errors":N,"env_mismatches":N,"unclosed_math":N,"brace_balance":N}
//         → 译前源文件签名，启用相对判定 ok_relative（真实语料 73.7% 带
//           grammar 空隙 baseline ERROR，绝对判定不可用）
// stdout: 每行一个 JSON 结果（字段见 validate() 返回）。
//
// IPC 双模：
//   默认        读完全部 stdin 批处理（spawn-per-batch，spawn 37ms 摊薄 <1ms/块）
//   --repl      常驻模式：逐行读入即时回一行（readline 循环，配合 python 常驻通道）
//   兜底        stdin 整体非 JSONL 时按单个裸 .tex 处理
//
// 依赖解析：require("tree-sitter") / require("@pfoerster/tree-sitter-latex") —
// 由 python 侧注入 NODE_PATH（包内 node_modules 或 TEXLATE_TS_NODE_PATH）。
"use strict";
const fs = require("fs");
const Parser = require("tree-sitter");
const Latex = require("@pfoerster/tree-sitter-latex");

const parser = new Parser();
parser.setLanguage(Latex);

// 单遍抓取: ERROR + env 事件(begin/end/generic_command/裸\begin裸\end) + 定界符叶
// token \( 在 query 语法里写 "\\(" (再经 JS 字符串转义 → '\\\\(')
const QUERY = new Parser.Query(
    Latex,
    [
        "(ERROR) @err",
        "(begin) @begin",
        "(end) @end",
        "(generic_command) @gc",
        '("{") @ob',
        '("}") @cb',
        '("$") @d',
        '("$$") @dd',
        '("\\\\[") @db',
        '("\\\\]") @de',
        '("\\\\(") @pb',
        '("\\\\)") @pe',
        '("\\\\begin") @rawb',
        '("\\\\end") @rawe',
    ].join("\n"),
);

function envNameOf(node) {
    // begin/end/generic_command 节点: 找 curly_group_text 或 curly_group 子节点,剥 {} 取环境名
    for (let i = 0; i < node.childCount; i++) {
        const c = node.child(i);
        if (c.type === "curly_group_text" || c.type === "curly_group") {
            const t = c.text;
            return t.length >= 2 && t[0] === "{" ? t.slice(1, -1) : t;
        }
    }
    return null;
}

// ERROR 内退化形态: \end{X} 碎成 \end 叶 + { X } 兄弟节点 → 从 sibling 链重建环境名
function rawNameOf(leafNode) {
    const sib = leafNode.nextSibling;
    if (!sib || sib.type !== "{") return null;
    let name = "";
    for (let c = sib.nextSibling; c && c.type !== "}"; c = c.nextSibling)
        name += c.text;
    return name;
}

function levenshtein(a, b) {
    const m = a.length,
        n = b.length;
    if (Math.abs(m - n) > 2) return 3; // 短路:>2 不关心
    const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
    for (let j = 1; j <= n; j++) d[0][j] = j;
    for (let i = 1; i <= m; i++)
        for (let j = 1; j <= n; j++)
            d[i][j] = Math.min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
            );
    return d[m][n];
}

function validate(src, rec) {
    const t0 = process.hrtime.bigint();
    const tree = parser.parse(src); // tree-sitter 永不抛异常
    const parse_ms = Number(process.hrtime.bigint() - t0) / 1e6;

    // 1) ERROR / MISSING 节点: hasError 剪枝 —— 只进含错子树,干净文件一步不进
    const parse_errors = [];
    if (tree.rootNode.hasError) {
        (function w(n) {
            if (n.isMissing) {
                parse_errors.push({
                    type: "MISSING",
                    node_type: n.type,
                    startByte: n.startIndex,
                    endByte: n.endIndex,
                    row: n.startPosition.row + 1,
                    snippet: "",
                });
            } else if (n.type === "ERROR") {
                parse_errors.push({
                    type: "ERROR",
                    startByte: n.startIndex,
                    endByte: n.endIndex,
                    row: n.startPosition.row + 1,
                    snippet: src
                        .slice(
                            n.startIndex,
                            Math.min(n.endIndex, n.startIndex + 60),
                        )
                        .replace(/\n/g, "\\n"),
                });
                return; // ERROR 内部不展开(碎片 token 无信息量)
            }
            if (!n.hasError) return;
            for (let i = 0; i < n.childCount; i++) w(n.child(i));
        })(tree.rootNode);
    }

    // 2) 单遍 Query: env 配对栈 + 定界符叶计数(missing 叶不计)
    const leaf = {
        "{": 0,
        "}": 0,
        $: 0,
        $$: 0,
        "\\[": 0,
        "\\]": 0,
        "\\(": 0,
        "\\)": 0,
    };
    const stack = [];
    const env_mismatches = [];
    const endEvent = (name, row) => {
        if (stack.length === 0) {
            env_mismatches.push({
                begin_env: null,
                end_env: name,
                line: row,
                kind: "dangling_end",
            });
            return;
        }
        if (stack[stack.length - 1].name === name) {
            stack.pop();
            return;
        }
        let idx = -1;
        for (let i = stack.length - 1; i >= 0; i--)
            if (stack[i].name === name) {
                idx = i;
                break;
            }
        env_mismatches.push({
            begin_env: stack[stack.length - 1].name,
            end_env: name,
            line: row,
            kind: "name_mismatch",
        });
        if (idx >= 0)
            stack.length = idx; // 弹到匹配项(其上 begin 视同未闭合)
        else stack.pop(); // 栈内无此名:弹栈顶恢复
    };
    const caps = QUERY.captures(tree.rootNode);
    caps.sort((a, b) => a.node.startIndex - b.node.startIndex);
    for (const c of caps) {
        const n = c.node;
        switch (c.name) {
            case "err": // 已由剪枝遍历收集
                break;
            case "ob":
            case "cb":
            case "d":
            case "dd":
            case "db":
            case "de":
            case "pb":
            case "pe":
                if (!n.isMissing) leaf[n.type]++; // missing 定界符已入 parse_errors,不计
                break;
            case "begin":
                if (!n.isMissing)
                    stack.push({
                        name: envNameOf(n),
                        row: n.startPosition.row + 1,
                    });
                break;
            case "end":
                if (!n.isMissing)
                    endEvent(envNameOf(n), n.startPosition.row + 1);
                break;
            case "gc": {
                if (n.isMissing) break;
                const cn = n.child(0);
                if (cn && cn.type === "command_name") {
                    if (cn.text === "\\end")
                        endEvent(envNameOf(n), n.startPosition.row + 1);
                    else if (cn.text === "\\begin")
                        stack.push({
                            name: envNameOf(n),
                            row: n.startPosition.row + 1,
                        });
                }
                break;
            }
            case "rawb": // ERROR 内裸 \begin(begin 节点的 \begin 叶子排除)
                if (n.parent.type !== "begin")
                    stack.push({
                        name: rawNameOf(n),
                        row: n.startPosition.row + 1,
                    });
                break;
            case "rawe": // ERROR 内裸 \end(end 节点的 \end 叶子排除)
                if (n.parent.type !== "end")
                    endEvent(rawNameOf(n), n.startPosition.row + 1);
                break;
        }
    }
    for (const b of stack)
        env_mismatches.push({
            begin_env: b.name,
            end_env: null,
            line: b.row,
            kind: "unclosed_begin",
        });

    const brace_balance = leaf["{"] - leaf["}"];
    const unclosed_math =
        (leaf["$"] % 2) +
        (leaf["$$"] % 2) +
        Math.abs(leaf["\\["] - leaf["\\]"]) +
        Math.abs(leaf["\\("] - leaf["\\)"]);

    // 3) 占位符契约:scanner 发出的 [[TYPE_n]] 集合 vs 译文实际集合
    const found = {};
    for (const m of src.matchAll(/\[\[\s*([A-Za-z]{2,10})_(\d{1,4})\s*\]\]/g)) {
        const k = `${m[1].toUpperCase()}_${m[2]}`;
        found[k] = (found[k] || 0) + 1;
    }
    const ph = {
        expected: 0,
        found: Object.values(found).reduce((a, b) => a + b, 0),
        missing: [],
        unexpected: [],
        typos: [],
    };
    const expect = {};
    if (Array.isArray(rec.expect)) {
        for (const e of rec.expect) {
            expect[e] = (expect[e] || 0) + 1;
            ph.expected++;
        }
        const f = { ...found };
        for (const [k, c] of Object.entries(expect)) {
            const have = f[k] || 0;
            if (have < c) for (let i = have; i < c; i++) ph.missing.push(k);
            if (have > 0) f[k] = Math.max(0, have - c);
        }
        for (const [k, c] of Object.entries(f))
            for (let i = 0; i < c; i++) ph.unexpected.push(k);
        // typo 配对: unexpected ↔ missing Levenshtein ≤ 2 → 可自动修复
        for (let i = ph.unexpected.length - 1; i >= 0; i--) {
            let best = -1,
                bestD = 3;
            for (let j = 0; j < ph.missing.length; j++) {
                const d = levenshtein(ph.unexpected[i], ph.missing[j]);
                if (d < bestD) {
                    bestD = d;
                    best = j;
                }
            }
            if (best >= 0 && bestD <= 2) {
                ph.typos.push({
                    found: ph.unexpected[i],
                    expected: ph.missing[best],
                });
                ph.unexpected.splice(i, 1);
                ph.missing.splice(best, 1);
            }
        }
    }

    const structural_bad =
        parse_errors.length > 0 ||
        env_mismatches.length > 0 ||
        unclosed_math > 0 ||
        brace_balance !== 0;
    const placeholder_bad =
        ph.missing.length + ph.unexpected.length + ph.typos.length > 0;
    const out = {
        id: rec.id || null,
        bytes: src.length,
        parse_ms: Math.round(parse_ms * 1000) / 1000,
        parse_errors,
        env_mismatches,
        unclosed_math,
        brace_balance,
        placeholders: ph,
        ok: !structural_bad && !placeholder_bad,
    };
    if (rec.baseline) {
        const b = rec.baseline;
        out.ok_relative =
            parse_errors.length <= (b.parse_errors || 0) &&
            env_mismatches.length <= (b.env_mismatches || 0) &&
            unclosed_math <= (b.unclosed_math || 0) &&
            Math.abs(brace_balance) <= Math.abs(b.brace_balance || 0) &&
            !placeholder_bad;
    }
    return out;
}

module.exports = { validate };

// ---------- IPC ----------
function handle(rec) {
    let src = rec.tex;
    if (src === undefined && rec.path) {
        try {
            src = fs.readFileSync(rec.path, "utf8");
        } catch (e) {
            return { id: rec.id || null, error: String(e), ok: false };
        }
    }
    try {
        return validate(String(src ?? ""), rec);
    } catch (e) {
        return { id: rec.id || null, error: String(e), ok: false };
    }
}

if (require.main === module) {
    if (process.argv.includes("--repl")) {
        // 常驻模式: 逐行读入即时回一行（python TsValidator.open() 对应通道）
        const readline = require("readline");
        const rl = readline.createInterface({
            input: process.stdin,
            terminal: false,
        });
        rl.on("line", (line) => {
            if (line.trim() === "") return;
            let rec;
            try {
                rec = JSON.parse(line);
            } catch (e) {
                process.stdout.write(
                    JSON.stringify({ id: null, error: String(e), ok: false }) +
                        "\n",
                );
                return;
            }
            process.stdout.write(JSON.stringify(handle(rec)) + "\n");
        });
    } else {
        // 批处理模式: 读完全部 stdin 再处理；非 JSONL 兜底按裸 .tex
        const input = fs.readFileSync(0, "utf8");
        let records = null;
        const lines = input.split("\n").filter((l) => l.trim() !== "");
        if (lines.length > 0) {
            const parsed = [];
            let allJson = true;
            for (const l of lines) {
                try {
                    const o = JSON.parse(l);
                    if (
                        o &&
                        typeof o === "object" &&
                        (o.tex !== undefined || o.path !== undefined)
                    )
                        parsed.push(o);
                    else {
                        allJson = false;
                        break;
                    }
                } catch {
                    allJson = false;
                    break;
                }
            }
            if (allJson) records = parsed;
        }
        if (!records) records = [{ id: null, tex: input }];
        for (const rec of records)
            process.stdout.write(JSON.stringify(handle(rec)) + "\n");
    }
}
