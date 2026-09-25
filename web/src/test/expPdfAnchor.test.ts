// @vitest-environment node
// Exp-C：真实 zh.pdf/en.pdf 的 pdf.js textLayer 抽取 × pdfSeqsForText 命中率实测。
// 流程：dual.json chunk.zh → 清洗(去 [[PH]]/\\) → 在抽取全文里定位(ground truth)
//       → 取真实抽取子串当"用户选区"喂产线 pdfSeqsForText → 看是否命中正确 seq。
// 跑法：cd web && npx vitest run src/test/expPdfAnchor.test.ts
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { it } from "vitest";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { pdfSeqsForText } from "../reader/copylatex";

const TASKS = join(homedir(), ".texlate/tasks");
const CMAPS = join(process.cwd(), "node_modules/pdfjs-dist/cmaps/");

interface Chunk { seq: number; src_file?: string; en?: string; zh?: string; kind?: string; status?: string }

async function pdfText(pdfPath: string): Promise<{ text: string; pages: string[] }> {
    const data = new Uint8Array(readFileSync(pdfPath));
    const doc = await getDocument({
        data, cMapUrl: CMAPS, cMapPacked: true,
        disableFontFace: true, verbosity: 0,
    }).promise;
    const pages: string[] = [];
    for (let i = 1; i <= doc.numPages; i++) {
        const p = await doc.getPage(i);
        const tc = await p.getTextContent();
        pages.push(
            (tc.items as { str?: string; hasEOL?: boolean }[])
                .map((it) => (it.str ?? "") + (it.hasEOL ? "\n" : ""))
                .join(""),
        );
    }
    return { text: pages.join("\n"), pages };
}

// 清洗 chunk 文本：去占位符 [[X_n]]、去 \\ 换行符（PDF 里这些已渲成公式/真换行）
const clean = (s: string) =>
    s.replace(/\[\[[A-Z]+_\d+\]\]/g, " ").replace(/\\\\/g, " ");

// LaTeX 源文本 → 渲染态近似：命令名/花括号/数学/~/转义符全抹（对齐 PDF 字形层）
const texStrip = (s: string) =>
    s.replace(/\[\[[A-Z]+_\d+\]\]/g, " ")
        .replace(/\$[^$]*\$|\\\([^)]*\\\)|\\\[[^\]]*\\\]/g, " ")
        .replace(/\\[a-zA-Z]+\*?(\[[^\]]*\])?/g, " ")
        .replace(/[{}]/g, " ")
        .replace(/~/g, " ")
        .replace(/\\([%&#_])/g, "$1")
        .replace(/\\+/g, " ");

// strip 全部空白得 needle，并保留 stripped→raw 索引映射
function stripMap(raw: string): { stripped: string; map: number[] } {
    let stripped = "";
    const map: number[] = [];
    for (let i = 0; i < raw.length; i++) {
        const c = raw[i];
        if (!/\s/.test(c)) { stripped += c; map.push(i); }
    }
    return { stripped, map };
}

it("pdf textLayer 抽取 × pdfSeqsForText 命中率", async () => {
    const dirs = readdirSync(TASKS)
        .filter((d) => existsSync(join(TASKS, d, "dual.json")))
        .filter((d) => existsSync(join(TASKS, d, "zh.pdf")) && existsSync(join(TASKS, d, "en.pdf")));
    console.log(`tasks: ${dirs.length}`);

    const agg = {
        chunks: 0, located: 0, hit: 0, tight: 0,
        unlocatable: [] as string[], missed: [] as string[], loose: [] as string[],
        byKind: {} as Record<string, { n: number; loc: number; hit: number }>,
    };
    const out: string[] = [];
    const emit = (s: string) => out.push(s);

    for (const dir of dirs) {
        const dual = JSON.parse(readFileSync(join(TASKS, dir, "dual.json"), "utf8"));
        const chunks: Chunk[] = dual.chunks ?? [];
        for (const side of ["zh", "en"] as const) {
            const pdf = join(TASKS, dir, `${side}.pdf`);
            const { text } = await pdfText(pdf);
            const { stripped, map } = stripMap(text);
            // 文档 token 面（产线同口径归一化 token 化）供第二定位器用
            const docToks = (text.toLowerCase().replace(/[‘’‚‛]/g, "'").replace(/[“”„‟]/g, '"')
                .replace(/[‐‑‒–—−]/g, "-").replace(/\s+/g, " ").replace(/([a-z])- /g, "$1").trim()
                .match(/[a-z0-9]+|[^\sa-z0-9]/giu) ?? []);
            let tLoc = 0, tHit = 0, tN = 0, tLoc2 = 0;
            for (const c of chunks) {
                const raw = clean((side === "zh" ? c.zh : c.en) ?? "");
                const needle = raw.replace(/\s+/g, "");
                if (needle.length < 6) continue; // 太短无意义
                tN++; agg.chunks++;
                const k = (agg.byKind[c.kind ?? "?"] ??= { n: 0, loc: 0, hit: 0 });
                k.n++;
                let sel: string | null = null;
                const at = stripped.indexOf(needle);
                if (at >= 0) {
                    sel = text.slice(map[at], map[at + needle.length - 1] + 1);
                } else {
                    // 第二定位器：texStrip 后 token 级锚——chunk token 流在 doc token 流里的最长连续命中
                    const ct = (texStrip(raw).toLowerCase().match(/[a-z0-9]+|[^\sa-z0-9]/giu) ?? []);
                    if (ct.length >= 6) {
                        const b2j = new Map<string, number[]>();
                        docToks.forEach((tk, j) => {
                            const l = b2j.get(tk);
                            if (l) l.push(j);
                            else b2j.set(tk, [j]);
                        });
                        let best = 0, bestEnd = -1;
                        let prev = new Map<number, number>();
                        for (let i = 0; i < ct.length; i++) {
                            const next = new Map<number, number>();
                            for (const j of b2j.get(ct[i]) ?? []) {
                                const l = (prev.get(j - 1) ?? 0) + 1;
                                next.set(j, l);
                                if (l > best) { best = l; bestEnd = j; }
                            }
                            prev = next;
                        }
                        const cov = best / ct.length;
                        if (cov >= 0.5 && best >= 6) {
                            tLoc2++;
                            // 选区=doc token 窗口还原为文本（近似用户框选该段）
                            sel = docToks.slice(bestEnd - best + 1, bestEnd + 1).join(" ");
                        } else {
                            agg.unlocatable.push(`${dir}#${c.seq}:${c.kind} cov=${cov.toFixed(2)} best=${best}/${ct.length} ${needle.slice(0, 40)}`);
                        }
                    } else {
                        agg.unlocatable.push(`${dir}#${c.seq}:${c.kind} short ${needle.slice(0, 40)}`);
                    }
                }
                if (sel == null) continue;
                if (at >= 0) { tLoc++; agg.located++; k.loc++; }
                const got = pdfSeqsForText(dual, sel, side);
                const hit = got.includes(c.seq);
                if (hit) {
                    tHit++; agg.hit++; k.hit++;
                    const span = got.length ? got[got.length - 1] - got[0] + 1 : 99;
                    if (span <= 3) agg.tight++;
                    else agg.loose.push(`${dir}#${c.seq} span=${span} [${got.slice(0, 6)}]`);
                } else {
                    agg.missed.push(`${dir}#${c.seq}:${c.kind} got[${got.slice(0, 6)}] want=${c.seq} | ${needle.slice(0, 40)}`);
                }
            }
            emit(`${dir} ${side}: n=${tN} verbatim=${tLoc} tokAnchor=${tLoc2} hit=${tHit}`);
        }
    }

    emit("\n===== 汇总 =====");
    emit(`chunks=${agg.chunks} located=${agg.located} (${(100 * agg.located / agg.chunks).toFixed(1)}%) hit=${agg.hit} (${(100 * agg.hit / Math.max(1, agg.located)).toFixed(1)}% of located, ${(100 * agg.hit / agg.chunks).toFixed(1)}% all) tight=${agg.tight}`);
    emit("byKind: " + JSON.stringify(agg.byKind));
    emit("\n--- 定位失败样例(至多15) ---"); agg.unlocatable.slice(0, 15).forEach((s) => emit(s));
    emit("\n--- 匹配失败样例(至多15) ---"); agg.missed.slice(0, 15).forEach((s) => emit(s));
    emit("\n--- 命中但过宽样例(至多10) ---"); agg.loose.slice(0, 10).forEach((s) => emit(s));
    writeFileSync("/home/fanghaotian/src/texlate/tmp/pdf-anchoring-20260923/exp/expC-report.txt", out.join("\n"));
}, 1_800_000);
