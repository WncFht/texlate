// Worker: parse one file with unified-latex, report ok/error/ms.
// Used by ul_corpus.js for isolation (30s timeout per file).
const { workerData, parentPort } = require("worker_threads");
const fs = require("fs");

const { file, mode } = workerData;
const t0 = process.hrtime.bigint();
try {
  const src = fs.readFileSync(file, "utf8");
  let ast;
  if (mode === "minimal") {
    const { parseMinimal } = require("@unified-latex/unified-latex-util-parse/index.cjs");
    ast = parseMinimal(src);
  } else {
    const { parse } = require("@unified-latex/unified-latex-util-parse/index.cjs");
    ast = parse(src);
  }
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  let raw = null;
  try {
    const { printRaw } = require("@unified-latex/unified-latex-util-print-raw/index.cjs");
    raw = printRaw(ast);
  } catch (e) {
    raw = "__PRINTRAW_FAIL__:" + e.message;
  }
  parentPort.postMessage({ ok: true, ms, raw, srcLen: src.length, errName: null });
} catch (e) {
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  parentPort.postMessage({
    ok: false, ms,
    errName: e.name || "Error",
    error: (e.message || String(e)).slice(0, 500),
    loc: e.location ? JSON.stringify(e.location).slice(0, 200) : null,
  });
}
