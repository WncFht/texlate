// health —— Home 后端健康面：TTL 门下的挂载首查（reader 往返重挂载不再
// 每趟重打）+ 不健康 30s 一拍自动复测（服务重启后页面自愈，不用手刷；
// ok 即停摆不空打端点）。手动「重试」钮走同一检查路径。

import { createSignal } from "solid-js";
import { api, type Health } from "../api/client";

/** 健康复查 TTL——reader 往返重挂载不再每趟重打（任务面走 store ensureFresh） */
const HOME_TTL_MS = 30_000;
let lastHealthAt = 0;

export function createHomeHealth() {
    const [health, setHealth] = createSignal<Health | null>(null);
    const [healthPending, setHealthPending] = createSignal(true);
    let healthTimer = 0;

    const check = async () => {
        try {
            setHealth(await api.health());
        } catch {
            setHealth(null);
        }
        setHealthPending(false);
        window.clearInterval(healthTimer);
        healthTimer = health()?.ok
            ? 0
            : window.setInterval(() => void check(), 30_000);
    };

    /** 挂载入口——TTL 窗内不重打 */
    const ensure = () => {
        const now = Date.now();
        if (now - lastHealthAt <= HOME_TTL_MS) return;
        lastHealthAt = now;
        void check();
    };

    /** 手动重试：回 pending 态走同一检查路径 */
    const recheck = () => {
        setHealthPending(true);
        void check();
    };

    /** health.compilers 可用数/总数（值 truthy 视为可用） */
    const compilersStat = () => {
        const c = health()?.compilers;
        if (!c) return "";
        const keys = Object.keys(c);
        return `${keys.filter((k) => c[k]).length}/${keys.length}`;
    };

    /** 卸载清自动复测 timer */
    const dispose = () => window.clearInterval(healthTimer);

    return { health, healthPending, ensure, recheck, compilersStat, dispose };
}

export type HomeHealth = ReturnType<typeof createHomeHealth>;
