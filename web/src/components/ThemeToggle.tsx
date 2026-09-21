// 主题快切钮——单钮循环 auto→light→dark，图标显示当前选择而非目标态
// （Docusaurus 惯例：图标报状态，title/aria 同时报语义）。Settings 页的
// Segmented 三选一保留为完整入口；阅读器 ⋯ 菜单借 themeIcon/themeLabel
// 组文案，不另起组件。

import { settingsStore, type ThemeChoice } from "../stores/settings";
import { t } from "../i18n";

const ORDER: ThemeChoice[] = ["auto", "light", "dark"];

export const themeIcon: Record<ThemeChoice, string> = {
    auto: "◐",
    light: "☀",
    dark: "☾",
};

export const themeLabel = (c: ThemeChoice): string =>
    c === "auto"
        ? t.settings.themeAuto
        : c === "light"
          ? t.settings.themeLight
          : t.settings.themeDark;

export const cycleTheme = () =>
    settingsStore.setTheme(
        ORDER[(ORDER.indexOf(settingsStore.theme()) + 1) % ORDER.length],
    );

export default function ThemeToggle(props: { class?: string }) {
    const tip = () =>
        `${t.settings.theme}：${themeLabel(settingsStore.theme())}`;
    return (
        <button
            type="button"
            class={props.class ?? "theme-toggle"}
            onClick={cycleTheme}
            title={tip()}
            aria-label={tip()}
        >
            <span aria-hidden="true">{themeIcon[settingsStore.theme()]}</span>
        </button>
    );
}
