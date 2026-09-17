// 阅读器/进度视图的时间格式化（纯函数）：HH:MM:SS 时刻与 h:mm:ss 时长。

const pad2 = (n: number) => String(n).padStart(2, "0");

/** epoch 秒 → 本地时钟 HH:MM:SS（阶段时间线用） */
export const fmtClock = (at: number) => {
    const d = new Date(at * 1000);
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
};

/** 秒 → h:mm:ss / m:ss（已用时与统计条 latency/seconds 共用） */
export const fmtElapsed = (sec: number) => {
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    return h > 0 ? `${h}:${pad2(m % 60)}:${pad2(s % 60)}` : `${m}:${pad2(s % 60)}`;
};
