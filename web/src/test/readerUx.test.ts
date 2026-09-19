// @vitest-environment jsdom
// U 系交互件回归：
//  - externalLinksBlank：正文内 http(s) 外链一律新窗 + noopener（U2）

import { describe, expect, it } from "vitest";
import { externalLinksBlank } from "../reader/paneUtils";

describe("externalLinksBlank", () => {
    it("http(s) 外链 → target=_blank + noopener；锚点/相对链不动", () => {
        const root = document.createElement("div");
        root.innerHTML =
            '<a href="https://arxiv.org/abs/1">a</a>' +
            '<a href="http://x.test">b</a>' +
            '<a href="#sec">c</a>' +
            '<a href="/rel">d</a>';
        externalLinksBlank(root);
        const [a, b, c, d] = [...root.querySelectorAll("a")].map((el) => ({
            target: el.target,
            rel: el.rel,
        }));
        expect(a).toEqual({ target: "_blank", rel: "noopener noreferrer" });
        expect(b.target).toBe("_blank");
        expect(c.target).toBe("");
        expect(d.target).toBe("");
    });
});
