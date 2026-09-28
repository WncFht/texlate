// features/copylatex —— copy-latex lane 的命令注册面（Wave C 挂载契约）。
// registerCopyLatex(reg, opts) 注册三项 + 挂 document 级 math 点击委托：
//   math.copyTex   when=math.tex||math.mathml —— 三级提取（alttext →
//                  katex annotation → mathml-to-latex 懒载 approx）+ 复制 +
//                  toast 字符数；不上 FloatBar（bar 否）。
//   chunk.copyTex  when=chunk.intSeq && view!='dom' —— 命中块 seq 集 POST
//                  /api/task/{id}/latex 整段档（whole）。
//   sel.copyTex    when=sel.text && view!='dom' && (sel.inChunk || view=='pdf')
//                  sec='sel' bar:true —— 选区 → seqs 闭区间 + 首尾 anchor
//                  → POST sent 档；zh 侧铁律 paneSide=='zh'（或选区起点落
//                  zh 侧 body——live-pane 无 .pane 壳致 paneSide=null 的盲
//                  区也兜住）恒发 whole 不下发 head/tail；pdf 侧 difflib
//                  段级锚定后恒整段档。
// 点击行为：pane bodyEl 内 click 命中 math/.katex/mjx-container → 开
// LatexCard；Alt+click 跳过卡直接复制 + toast。委托在 document 上对
// opts.panes() 现查 bodyEl 归属——pane 重挂/增删零成本（委托不绑元素）。
//
// 返回 {dispose, cardOpen, closeCard}——整合期把 cardOpen/closeCard 挂进
// ReaderView layerOpen/closeLayer（Esc 层栈 'cite' 序位同层）、FloatBar
// suppressed 名单与句游标让路名单（见 selsys 落地注释同款）。

import { createSignal } from "solid-js";

import type { Command, Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import { ApiError, errText } from "../../api/client";
import { toast } from "../../stores/toastStore";
import { fmt } from "../../i18n";
import {
    clText,
    copyLatexMode,
    copyText,
    mathIsInline,
    mathTexFrom,
    mathTexSync,
    pdfSeqsForText,
    selChunks,
    type PdfDualLike,
} from "../cite/copylatex";
import { openLatexCard, type LatexCardHandle } from "../cards/LatexCard";
import { paneSide } from "../logic/paneUtils";

// ------------------------------------------------------------------ 契约面

export interface CopyLatexPane {
    /** pane 类：'dom' | 'html' | 'pdf' | 'live'（宿主自定词表——只用 bodyEl/side） */
    kind: string;
    bodyEl?: HTMLElement;
    /** 'en'|'original' → en 侧；'zh'|'translated' → zh 侧；缺省按 en */
    side?: string;
}

export interface LatexRequest {
    seqs: number[];
    head?: string;
    tail?: string;
    mode?: "sent" | "whole";
    gaps?: boolean;
}

export interface LatexResponse {
    latex: string;
    chunks: number;
    files?: string[];
    mode_used?: "sent" | "whole";
    approx?: boolean;
    truncated?: boolean;
}

export interface CopyLatexOpts {
    taskId(): string | undefined;
    panes(): readonly CopyLatexPane[];
    /** dual.json 快照（pdf 侧 difflib 锚定的语料源）；缺席 → pdf 臂不可用 */
    dual?(): PdfDualLike | null | undefined;
    /** 端点出口可注入（vitest/联调桩）；缺省走内置 fetch POST */
    post?(taskId: string, body: LatexRequest): Promise<LatexResponse>;
    /** 剪贴板出口可注入；缺省 copyText（clipboard + execCommand 兜底） */
    writeText?(s: string): boolean | Promise<boolean>;
    toastOk?(msg: string): void;
    toastErr?(msg: string): void;
}

export interface CopyLatexHandle {
    /** 摘三命令 + 点击委托 + 收卡（组件卸载路径调） */
    dispose(): void;
    /** 公式源卡开否——ReaderView layerOpen('cite') 同层归并用 */
    cardOpen(): boolean;
    closeCard(): void;
}

// ------------------------------------------------------------------ 端点

/** POST /api/task/{id}/latex——rest.ts 是禁碰面，端点调用在本模块内自闭。 */
async function defaultPost(
    taskId: string,
    body: LatexRequest,
): Promise<LatexResponse> {
    const res = await fetch(`/api/task/${encodeURIComponent(taskId)}/latex`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout?.(15_000) ?? null,
    });
    if (!res.ok) {
        let detail = res.statusText;
        let code: string | undefined;
        try {
            const b: unknown = await res.json();
            if (b && typeof b === "object") {
                const r = b as Record<string, unknown>;
                if (typeof r.detail === "string") detail = r.detail;
                if (typeof r.code === "string") code = r.code;
            }
        } catch {
            /* 非 JSON 错误体——statusText 兜底 */
        }
        throw new ApiError(res.status, detail, code);
    }
    return (await res.json()) as LatexResponse;
}

// ------------------------------------------------------------------ 内部件

const MATH_SEL = "math, .katex, mjx-container";

export function registerCopyLatex(
    reg: Registry<CmdCtx>,
    opts: CopyLatexOpts,
): CopyLatexHandle {
    const post = opts.post ?? defaultPost;
    const ok = opts.toastOk ?? ((m: string) => toast.ok(m));
    const err = opts.toastErr ?? ((m: string) => toast.err(m));
    const copy = async (s: string): Promise<boolean> =>
        opts.writeText ? !!(await opts.writeText(s)) : copyText(s);

    const failToast = (e: unknown) => err(errText(e));
    const copiedChars = (n: number, approx: boolean) =>
        fmt(clText("reader.copyLatex.copiedChars", "已复制 {n} 字符"), {
            n,
        }) +
        (approx ? clText("reader.copyLatex.approxTag", "（近似重构）") : "");
    const copiedChunks = (chunks: number, chars: number, approx: boolean) =>
        fmt(
            clText("reader.copyLatex.copiedChunks", "已复制 {n} 段 · {m} 字符"),
            { n: chunks, m: chars },
        ) +
        (approx ? clText("reader.copyLatex.approxTag", "（近似重构）") : "");

    /** 复制结果 → toast；res.chunks 缺席按请求 seqs 长度兜底 */
    const finishRes = async (
        res: LatexResponse,
        reqSeqs: number[],
    ): Promise<void> => {
        const okc = await copy(res.latex);
        if (!okc)
            return err(
                clText("reader.copyLatex.failed", "复制失败——剪贴板不可用"),
            );
        ok(
            copiedChunks(
                typeof res.chunks === "number" ? res.chunks : reqSeqs.length,
                res.latex.length,
                !!res.approx,
            ),
        );
    };

    // ------------------------------------------------------------ 公式源卡

    const [card, setCard] = createSignal<LatexCardHandle | null>(null);
    const closeCard = () => {
        card()?.close();
        setCard(null);
    };

    const copyMath = async (el: Element): Promise<void> => {
        const r = await mathTexFrom(el);
        if (!r)
            return err(clText("reader.copyLatex.noSrc", "该公式无 LaTeX 源"));
        const okc = await copy(r.tex);
        if (!okc)
            return err(
                clText("reader.copyLatex.failed", "复制失败——剪贴板不可用"),
            );
        ok(copiedChars(r.tex.length, r.approx));
    };

    const openMathCard = (el: Element) => {
        closeCard();
        const rect = el.getClientRects()[0] ?? el.getBoundingClientRect();
        const sync = mathTexSync(el);
        setCard(
            openLatexCard({
                rect,
                tex: sync,
                inline: mathIsInline(el),
                // 卡内自管 load→setSrc 补灌——本层无需中转 signal
                load: sync ? undefined : () => mathTexFrom(el),
                onClose: () => setCard(null),
                onCopied: (n, approx) => ok(copiedChars(n, approx)),
                onCopyFail: () =>
                    err(
                        clText(
                            "reader.copyLatex.failed",
                            "复制失败——剪贴板不可用",
                        ),
                    ),
            }),
        );
    };

    /** pane bodyEl 内 click 委托：命中 math → 卡；Alt+click → 直复制。 */
    const onDocClick = (e: MouseEvent) => {
        const target = e.target as Element | null;
        if (!target?.closest) return;
        const el = target.closest(MATH_SEL);
        if (!el) return;
        const host = opts
            .panes()
            .find((p) => p.bodyEl && p.bodyEl.contains(el));
        if (!host) return; // 非阅读面 math（导读/帮助等）不接管
        if (e.altKey) {
            void copyMath(el).catch(failToast);
            return;
        }
        openMathCard(el);
    };
    document.addEventListener("click", onDocClick);

    // ------------------------------------------------------------ 选区 → POST

    /** 选区起点所在 pane（head 侧判定源；live-pane 无 .pane 壳的盲区补） */
    const paneOfNode = (n: Node | null): CopyLatexPane | undefined => {
        const el = n
            ? n.nodeType === 3
                ? n.parentElement
                : (n as Element)
            : null;
        if (!el) return undefined;
        return opts.panes().find((p) => p.bodyEl && p.bodyEl.contains(el));
    };

    const runSel = async (c: CmdCtx): Promise<void> => {
        const id = opts.taskId();
        if (!id)
            return err(
                clText("reader.copyLatex.failed", "复制失败——剪贴板不可用"),
            );
        const hit = c.hit;
        const req: LatexRequest = { seqs: [] };

        if (hit.view === "pdf") {
            const side: "en" | "zh" =
                hit.paneSide === "zh" ||
                paneOfNode(hit.sel.range?.startContainer ?? null)?.side ===
                    "zh" ||
                paneOfNode(hit.sel.range?.startContainer ?? null)?.side ===
                    "translated"
                    ? "zh"
                    : "en";
            // B 路 marked-content 锚：sel.chunks 已载数值 seq（hitctx 的
            // .textLayer resolver 产出）——精确直用；空集 → C 路模糊兜底
            const marked = (hit.sel.chunks ?? [])
                .map((k) => Number(k))
                .filter((n) => Number.isInteger(n));
            req.seqs = marked.length
                ? [...new Set(marked)].sort((a, b) => a - b)
                : pdfSeqsForText(opts.dual?.(), hit.sel.text, side);
            req.mode = "whole";
        } else {
            const range = hit.sel.range;
            if (!range)
                return err(clText("reader.copyLatex.noSel", "没有可用选区"));
            const seqSet = new Set<number>();
            const headSide = paneOfNode(range.startContainer);
            const tailSide = paneOfNode(range.endContainer);
            let head: string | undefined;
            let tail: string | undefined;
            for (const p of opts.panes()) {
                if (!p.bodyEl) continue;
                const r = selChunks(p.bodyEl, range);
                for (const s of r.seqs) seqSet.add(s);
                // anchor 只收 en 侧——zh 文本在 en 源切片里无锚可定
                if (paneSide(p) !== "en") continue;
                if (p === headSide && r.head) head = r.head;
                if (p === tailSide && r.tail) tail = r.tail;
            }
            req.seqs = [...seqSet].sort((a, b) => a - b);
            const zhSide =
                hit.paneSide === "zh" ||
                (headSide != null && paneSide(headSide) === "zh");
            if (zhSide) {
                req.mode = "whole"; // zh 铁律：不下发 head/tail
            } else {
                req.mode = copyLatexMode();
                if (req.mode === "sent") {
                    if (head) req.head = head;
                    if (tail) req.tail = tail;
                }
            }
        }
        if (!req.seqs.length)
            return err(
                clText("reader.copyLatex.noChunks", "选区未覆盖任何段落"),
            );
        try {
            const res = await post(id, req);
            await finishRes(res, req.seqs);
        } catch (e) {
            failToast(e);
        }
    };

    // ------------------------------------------------------------ 命令注册

    const cmds: Command<CmdCtx>[] = [
        {
            id: "math.copyTex",
            title: "menu.math.copyTex",
            sec: "math",
            // mathml 兜底臂要算——只看 math.tex 会把恰好需要 fallback 的
            // 外源 MathML 目标藏掉（alttext/annotation 双缺）
            when: "math.tex || math.mathml",
            run: (c) => {
                const el = c.hit.math.el;
                if (!el) return;
                return copyMath(el).catch(failToast);
            },
        },
        {
            id: "chunk.copyTex",
            title: "menu.chunk.copyTex",
            sec: "chunk",
            when: "chunk.intSeq && view != 'dom'",
            run: async (c) => {
                const id = opts.taskId();
                const seq = c.hit.chunk.intSeq;
                if (!id || seq == null)
                    return err(
                        clText(
                            "reader.copyLatex.failed",
                            "复制失败——剪贴板不可用",
                        ),
                    );
                try {
                    const res = await post(id, {
                        seqs: [seq],
                        mode: "whole",
                    });
                    await finishRes(res, [seq]);
                } catch (e) {
                    failToast(e);
                }
            },
        },
        {
            id: "sel.copyTex",
            title: "menu.sel.copyTex",
            sec: "sel",
            bar: true,
            // pdf 无 data-chunk 锚——sel.inChunk 恒假，须单列放行；
            // dom 链无 .tex 源（端点 422）恒排
            when: "sel.text && view != 'dom' && (sel.inChunk || view == 'pdf')",
            run: (c) => runSel(c),
        },
    ];
    for (const cmd of cmds) {
        if (reg.get(cmd.id)) reg.unregister(cmd.id); // 幂等重挂
        reg.register(cmd);
    }

    return {
        dispose() {
            document.removeEventListener("click", onDocClick);
            closeCard();
            for (const cmd of cmds) reg.unregister(cmd.id);
        },
        cardOpen: () => card() != null,
        closeCard,
    };
}
