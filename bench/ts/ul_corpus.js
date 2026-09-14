// Corpus benchmark: parse all .tex under bench/corpus with 30s timeout each
// (worker-thread isolation), then round-trip + leak-rate on successful parses.
const { Worker } = require("worker_threads");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const BENCH = path.resolve(__dirname, "..");
const CORPUS = path.join(BENCH, "corpus");
const RESULTS = path.join(BENCH, "results");
fs.mkdirSync(RESULTS, { recursive: true });

const files = execSync(`find "${CORPUS}" -name "*.tex"`, { encoding: "utf8" })
  .trim().split("\n").sort();

const TIMEOUT_MS = 30000;

function parseInWorker(file, mode) {
  return new Promise((resolve) => {
    const w = new Worker(path.join(__dirname, "ul_worker.js"), {
      workerData: { file, mode },
    });
    const timer = setTimeout(() => {
      w.terminate();
      resolve({ ok: false, ms: TIMEOUT_MS, errName: "Timeout", error: ">30s timeout" });
    }, TIMEOUT_MS);
    w.on("message", (m) => { clearTimeout(timer); w.terminate(); resolve(m); });
    w.on("error", (e) => { clearTimeout(timer); w.terminate();
      resolve({ ok: false, ms: 0, errName: "WorkerError", error: String(e).slice(0, 300) }); });
  });
}

// diff helper: classify round-trip result
function diffClassify(orig, printed) {
  if (orig === printed) return { cls: "identical" };
  // normalized comparison: collapse all whitespace runs to single space,
  // strip leading/trailing per line
  const norm = (s) => s.split("\n").map((l) => l.replace(/\s+/g, " ")).join("\n")
    .replace(/[ \t]+$/gm, "").replace(/\n{3,}/g, "\n\n").trim();
  if (norm(orig) === norm(printed)) return { cls: "normalized" };
  // find first divergence position
  let i = 0;
  const m = Math.min(orig.length, printed.length);
  while (i < m && orig[i] === printed[i]) i++;
  const line = orig.slice(0, i).split("\n").length;
  return {
    cls: "diverged",
    firstDiffPos: i, firstDiffLine: line,
    origLen: orig.length, printedLen: printed.length,
    ctx: JSON.stringify(orig.slice(Math.max(0, i - 40), i + 40)) + " ||VS|| " +
         JSON.stringify(printed.slice(Math.max(0, i - 40), i + 40)),
  };
}

// "main" file of each paper dir for round-trip
const MAIN_FILES = [
  "1412.6980/arxiv.tex", "1511.06432/iclr2016_conference.tex",
  "1512.03385/residual_v1_arxiv_release.tex", "1706.03762/ms.tex",
  "1810.04805/main.tex", "1906.08237/neurips_2019.tex",
  "2005.11401/neurips_2020.tex", "2106.09685/iclr2022_conference.tex",
  "2203.02155/neurips_2021.tex", "2305.14335/main.tex",
  "2501.14787/main.tex", "hep-th/9901001/imamura2.tex",
];

(async () => {
  const results = [];
  const roundtrip = {};
  for (const f of files) {
    const rel = path.relative(CORPUS, f);
    const r = await parseInWorker(f, "full");
    const entry = { file: rel, ok: r.ok, ms: Math.round(r.ms) };
    if (!r.ok) { entry.error = r.errName + ": " + (r.error || ""); if (r.loc) entry.loc = r.loc; }
    results.push(entry);
    process.stderr.write(`${r.ok ? "OK  " : "FAIL"} ${rel} ${entry.ms}ms ${r.ok ? "" : entry.error.slice(0, 120)}\n`);

    // round-trip on main files
    if (r.ok && MAIN_FILES.includes(rel)) {
      const orig = fs.readFileSync(f, "utf8");
      roundtrip[rel] = diffClassify(orig, r.raw);
    }
  }

  fs.writeFileSync(
    path.join(RESULTS, "unified-latex-parse.json"),
    JSON.stringify(results, null, 2)
  );
  const okN = results.filter((x) => x.ok).length;
  console.log(`\nPARSE: ${okN}/${results.length} ok`);
  for (const r of results.filter((x) => !x.ok)) console.log("  FAIL", r.file, "-", (r.error||"").split("\n")[0]);

  // ---- leak rate + detailed stats need ASTs in-process; reparse ok files here
  const { parse } = require("@unified-latex/unified-latex-util-parse/index.cjs");
  const { extractTranslatableBlocks } = require("./ul_common.js");
  const leak = { totalBlocks: 0, leakedBlocks: 0, leakedBy: {}, files: {} };
  for (const r of results) {
    if (!r.ok) continue;
    const f = path.join(CORPUS, r.file);
    let ast;
    try { ast = parse(fs.readFileSync(f, "utf8")); } catch { continue; }
    const blocks = extractTranslatableBlocks(ast);
    const fileStat = { blocks: blocks.length, leaked: 0, samples: [] };
    for (const b of blocks) {
      leak.totalBlocks++; fileStat.blocks === undefined || null;
      const hits = [];
      if (/\$/.test(b.text)) hits.push("$");
      if (/\\cite[a-zA-Z]*/.test(b.text)) hits.push("cite");
      if (/\\(eq)?ref|\\autoref|\\cref|\\Cref|\\nameref|\\pageref/.test(b.text)) hits.push("ref");
      if (/\\begin\{/.test(b.text)) hits.push("begin");
      if (hits.length > 0) {
        leak.leakedBlocks++; fileStat.leaked++;
        for (const h of hits) leak.leakedBy[h] = (leak.leakedBy[h] || 0) + 1;
        if (fileStat.samples.length < 3) fileStat.samples.push(b.text.slice(0, 160));
      }
    }
    leak.files[r.file] = fileStat;
  }
  fs.writeFileSync(
    path.join(RESULTS, "unified-latex-leak.json"),
    JSON.stringify({ ...leak, leakRate: leak.totalBlocks ? leak.leakedBlocks / leak.totalBlocks : 0 }, null, 2)
  );
  fs.writeFileSync(
    path.join(RESULTS, "unified-latex-roundtrip.json"),
    JSON.stringify(roundtrip, null, 2)
  );
  console.log(`\nLEAK: ${leak.leakedBlocks}/${leak.totalBlocks} blocks (${(100 * leak.leakedBlocks / (leak.totalBlocks || 1)).toFixed(1)}%) by=${JSON.stringify(leak.leakedBy)}`);
  console.log("\nROUNDTRIP:");
  for (const [k, v] of Object.entries(roundtrip)) console.log(`  ${v.cls.padEnd(10)} ${k}${v.cls === "diverged" ? " firstDiff@line" + v.firstDiffLine + " len " + v.origLen + "->" + v.printedLen : ""}`);
})();
