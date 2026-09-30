// escstack —— Esc 层栈（sel-system lane）。
// 层序固定优先级 editor > cite > find > menu > info > help > sel——
// 「最内层先塌」而非「最后开先塌」（预研 12 层栈剧本实证序）。
// Esc 一次恰好塌一层：
//   - 普通层：关标记 + 调 close → consumed=true（调用方
//     stopImmediatePropagation——document bubble 截停后 window 级
//     pdf.js 监听收不到，一次 Esc 不双塌）。
//   - passive 层（editor=pdf.js 选中高亮）：只记账不消费——不 close、
//     不动事件，穿透给 window 级 UIManager 自己做 unselectAll
//     （真单塌一层；层开否由宿主 isOpen 查询反映）。
//
// 两种登记模型：
//   push(layer, {close, passive?}) —— 旗标模型：push 即开、塌即关；
//     返回 disposer（=pop）。浮层组件开时 push、卸时 disposer。
//   bind(layer, {isOpen, close, passive?}) —— 查询模型：开否全听
//     isOpen()（sel 层查 getSelection、editor 层查 pdfjs().selected）。
// pop(layer) 摘层；top() 当前应塌层；isOpen(layer) 单查。

export const ESC_ORDER = [
    "editor",
    "cite",
    "find",
    "menu",
    "info",
    "help",
    "sel",
] as const;
export type EscLayer = (typeof ESC_ORDER)[number];

export interface EscHandler {
    /** 层开判定（bind 模型必填；push 模型内部旗标供给） */
    isOpen?(): boolean;
    /** 塌层动作——passive 层不调用 */
    close?(): void;
    /** true=只记账不消费（事件穿透给 window 级 pdf.js unselectAll） */
    passive?: boolean;
}

interface Entry extends EscHandler {
    flag?: { open: boolean };
}

export interface EscCollapse {
    layer: EscLayer;
    /** true=事件已消费（调用方须 preventDefault+stopImmediatePropagation） */
    consumed: boolean;
}

export class EscStack {
    private entries = new Map<EscLayer, Entry>();

    /** 旗标模型登记：push 即开。返回摘层 disposer。 */
    push(layer: EscLayer, h: Omit<EscHandler, "isOpen"> = {}): () => void {
        const flag = { open: true };
        this.entries.set(layer, {
            ...h,
            flag,
            isOpen: () => flag.open,
        });
        return () => this.pop(layer);
    }

    /** 查询模型登记：开否全听 isOpen()。返回摘层 disposer。 */
    bind(layer: EscLayer, h: EscHandler): () => void {
        this.entries.set(layer, h);
        return () => this.pop(layer);
    }

    /** 摘层（旗标/查询两模型通用） */
    pop(layer: EscLayer): boolean {
        return this.entries.delete(layer);
    }

    /** 层开判定 */
    isOpen(layer: EscLayer): boolean {
        const en = this.entries.get(layer);
        return !!en && (en.isOpen?.() ?? false);
    }

    /** 当前应塌层（ESC_ORDER 序首个开层）；无开层 null */
    top(): EscLayer | null {
        for (const layer of ESC_ORDER) if (this.isOpen(layer)) return layer;
        return null;
    }

    /** 当前开层清单（ESC_ORDER 序）——调试/测试面 */
    openLayers(): EscLayer[] {
        return ESC_ORDER.filter((l) => this.isOpen(l));
    }

    /**
     * 塌恰好一层：
     *   - 命中 passive 层 → {consumed:false}：只记账，不 close、不动标记
     *     （事件穿透给 pdf.js 自己做 unselectAll；层态由宿主编码回写）。
     *   - 命中普通层 → flag 关（旗标模型）+ close() → {consumed:true}。
     *   - 无开层 → null。
     */
    collapseTop(): EscCollapse | null {
        for (const layer of ESC_ORDER) {
            const en = this.entries.get(layer);
            if (!en) continue;
            if (!(en.isOpen?.() ?? false)) continue;
            if (en.passive) return { layer, consumed: false };
            if (en.flag) en.flag.open = false;
            en.close?.();
            return { layer, consumed: true };
        }
        return null;
    }
}
