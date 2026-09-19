// dropzone —— Home 整页拖放上传：dragDepth 计数配平 enter/leave（子元素
// 间穿行不闪断），仅拦截文件拖拽（文本拖入输入框不受影响）。
// 自 pages/Home.tsx 拆出；drop 的 busy 闸与文案归调用方。

import { createSignal } from "solid-js";

export function createHomeDropzone(deps: {
    busy(): boolean;
    /** busy 态拖入的提示——错误文案归调用方 */
    onBusyDrop(): void;
    /** 文件落袋（drag 证据已验） */
    onFiles(files: File[]): void;
}) {
    const [dragOn, setDragOn] = createSignal(false);
    let dragDepth = 0;

    /** 仅文件拖拽算数——文本拖入输入框不触发整页上传态 */
    const hasFile = (e: DragEvent) =>
        [...(e.dataTransfer?.types ?? [])].includes("Files");

    const onDragEnter = (e: DragEvent) => {
        if (!hasFile(e)) return;
        e.preventDefault();
        dragDepth++;
        setDragOn(true);
    };

    const onDragOver = (e: DragEvent) => {
        if (hasFile(e)) e.preventDefault();
    };

    const onDragLeave = () => {
        if (--dragDepth <= 0) {
            dragDepth = 0;
            setDragOn(false);
        }
    };

    const onDrop = (e: DragEvent) => {
        if (!hasFile(e)) return;
        e.preventDefault();
        dragDepth = 0;
        setDragOn(false);
        const files = [...(e.dataTransfer?.files ?? [])];
        if (!files.length) return;
        if (deps.busy()) {
            deps.onBusyDrop();
            return;
        }
        deps.onFiles(files);
    };

    return { dragOn, onDragEnter, onDragOver, onDragLeave, onDrop };
}

export type HomeDropzone = ReturnType<typeof createHomeDropzone>;
