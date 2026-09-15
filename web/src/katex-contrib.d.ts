declare module "katex/contrib/auto-render" {
    interface RenderMathInElementOptions {
        delimiters?: { left: string; right: string; display: boolean }[];
        ignoredTags?: string[];
        ignoredClasses?: string[];
        errorCallback?: (msg: string, err: unknown) => void;
        throwOnError?: boolean;
        macros?: Record<string, string>;
    }
    export default function renderMathInElement(
        elem: HTMLElement,
        options?: RenderMathInElementOptions,
    ): void;
}
