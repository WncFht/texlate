// Shared helpers for the LaTeX parser benchmark.
"use strict";
const fs = require("fs");
const path = require("path");

const BENCH = path.resolve(__dirname, "..");
const CORPUS = path.join(BENCH, "corpus");
const FIXTURES = path.join(BENCH, "fixtures");
const RESULTS = path.join(BENCH, "results");

function listTexFiles(dir) {
    const out = [];
    (function walk(d) {
        for (const e of fs.readdirSync(d, { withFileTypes: true })) {
            const p = path.join(d, e.name);
            if (e.isDirectory()) walk(p);
            else if (e.name.endsWith(".tex")) out.push(p);
        }
    })(dir);
    return out.sort();
}

// Extract % @Tnn marker positions (0-based line + byte offset) from a fixture source.
function markerLines(src) {
    const lines = src.split("\n");
    const markers = []; // {id, line}
    let offset = 0;
    const offs = [];
    for (let i = 0; i < lines.length; i++) {
        offs.push(offset);
        offset += lines[i].length + 1;
    }
    lines.forEach((l, i) => {
        for (const m of l.matchAll(/@T(\d+)/g))
            markers.push({ id: "T" + m[1], line: i, offset: offs[i] });
    });
    return { markers, lineOffsets: offs, lines };
}

// Region (byte range) belonging to a trap: from the marker line to the next marker line.
function trapRegions(src) {
    const { markers, lines } = markerLines(src);
    const regions = [];
    for (let i = 0; i < markers.length; i++) {
        const start = markers[i].offset;
        const end = i + 1 < markers.length ? markers[i + 1].offset : src.length;
        const endLine =
            i + 1 < markers.length ? markers[i + 1].line : lines.length;
        regions.push({
            id: markers[i].id,
            start,
            end,
            startLine: markers[i].line,
            endLine,
        });
    }
    return regions;
}

function ensureResults() {
    fs.mkdirSync(RESULTS, { recursive: true });
}

module.exports = {
    BENCH,
    CORPUS,
    FIXTURES,
    RESULTS,
    listTexFiles,
    trapRegions,
    markerLines,
    ensureResults,
};
