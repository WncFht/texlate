// HealthLine —— Home 后端健康行：dot + 状态文案 + 版本/编译器统计；
// 未连接出「重试」钮（走同一条检查路径——health.ts recheck）。

import { Show } from "solid-js";
import { t } from "../i18n";
import type { HomeHealth } from "./health";

export default function HealthLine(props: { hh: HomeHealth }) {
    return (
        <p
            class="health"
            role="status"
            classList={{
                checking: props.hh.healthPending(),
                bad: !props.hh.healthPending() && !props.hh.health()?.ok,
            }}
        >
            <i class="dot" />
            {props.hh.healthPending()
                ? t.home.healthChecking
                : props.hh.health()?.ok
                  ? t.home.healthOk
                  : t.home.healthBad}
            <Show when={!props.hh.healthPending() && props.hh.health()?.ok}>
                <span class="muted">
                    v{props.hh.health()!.version ?? "?"} · {t.home.compilers}{" "}
                    {props.hh.compilersStat()}
                </span>
            </Show>
            <Show when={!props.hh.healthPending() && !props.hh.health()?.ok}>
                <button
                    type="button"
                    class="btn-ghost health-retry"
                    onClick={() => props.hh.recheck()}
                >
                    {t.home.retry}
                </button>
            </Show>
        </p>
    );
}
