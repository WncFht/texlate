// tasknav —— 跨任务阅读链的回程票（#/reader/{A} → #/reader/{B}?from={A}）。

export function curReaderTask(): string | undefined {
    return /^#\/reader\/([A-Za-z0-9_-]+)/.exec(window.location.hash)?.[1];
}

export function fromParamOf(hash: string): string | undefined {
    return /[?&]from=([A-Za-z0-9_-]+)/.exec(hash)?.[1];
}

export function readerHashWithFrom(taskId: string): string {
    const cur = curReaderTask();
    return `#/reader/${taskId}${cur && cur !== taskId ? `?from=${cur}` : ""}`;
}
