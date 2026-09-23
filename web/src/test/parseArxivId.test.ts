// @vitest-environment jsdom
// parseArxivId —— canon spec §2 剥离序管线全量回归：
//   A. 30 形表（tmp/ux-research-20260922/exp/ms-urlnorm/results.tsv，
//      LANL 行按 spec §2 不收清单裁为 REJECT）；
//   B. spec §2 追加形（class 剥壳/oai/safe_id 回流/尾注/扩展名循环）；
//   C. 对抗探针（adversarial_out.txt 的 ext-only 收/拒按 spec 裁决——
//      怪 scheme/LANL/端口/双斜杠/overview 动词全拒；裸 .pdf 尾/首尾
//      斜杠/arXiv 空格冒号/大写 V 等容错收）；
//   D. era 闸（新形 YYMM∈[0704,当月]；旧形 9107..9912∪0000..0703）。

import { describe, expect, it } from "vitest";
import { parseArxivId } from "../pages/Home";

const ACCEPT: [string, string][] = [
    // ---- A. 30 形表 ----
    ["https://arxiv.org/abs/2301.12345", "2301.12345"],
    ["https://arxiv.org/abs/2301.12345v2", "2301.12345v2"],
    ["http://arxiv.org/abs/2301.12345", "2301.12345"],
    ["https://www.arxiv.org/abs/2301.12345", "2301.12345"],
    ["arxiv.org/abs/2301.12345", "2301.12345"],
    ["HTTPS://ARXIV.ORG/ABS/2301.12345", "2301.12345"],
    ["https://arxiv.org/pdf/2301.12345.pdf", "2301.12345"],
    ["https://arxiv.org/pdf/2301.12345v2.pdf#page=3", "2301.12345v2"],
    ["https://arxiv.org/abs/2301.12345?context=cs.LG", "2301.12345"],
    ["https://arxiv.org/html/2301.12345v2", "2301.12345v2"],
    ["https://export.arxiv.org/abs/2301.12345", "2301.12345"],
    ["2301.12345", "2301.12345"],
    ["2301.12345v2", "2301.12345v2"],
    ["arXiv:2301.12345", "2301.12345"],
    ["cond-mat.mes-hall/0501234", "cond-mat/0501234"],
    ["https://ar5iv.labs.arxiv.org/html/2301.12345", "2301.12345"],
    ["https://ar5iv.org/abs/2301.12345", "2301.12345"],
    ["https://www.alphaxiv.org/abs/2301.12345", "2301.12345"],
    ["https://alphaxiv.org/pdf/2301.12345v2", "2301.12345v2"],
    ["https://doi.org/10.48550/arXiv.2301.12345", "2301.12345"],
    ["doi:10.48550/arXiv.2301.12345", "2301.12345"],
    ["10.48550/arXiv.2301.12345", "2301.12345"],
    ["https://dx.doi.org/10.48550/arXiv.2301.12345", "2301.12345"],
    ["hep-th/9901001", "hep-th/9901001"],
    ["https://arxiv.org/pdf/hep-th/9901001v3", "hep-th/9901001v3"],
    ["arXiv:math.GT/0309136", "math/0309136"],
    ["https://doi.org/10.48550/arXiv.hep-th/9901001", "hep-th/9901001"],
    // ---- B. spec §2 追加形 ----
    ["physics.atom-ph/9801001", "physics/9801001"],
    ["math.GT/0309136", "math/0309136"],
    ["Hep-Th/9901001", "hep-th/9901001"],
    ["10.48550/arXiv.2301.00001", "2301.00001"],
    ["arXiv.2301.00001", "2301.00001"],
    ["arXiv:2301.00001 [cs.CL]", "2301.00001"],
    ["oai:arXiv.org:math.GT/0309136", "math/0309136"],
    ["hep-th--9901001", "hep-th/9901001"],
    ["2301.00001.tar.gz", "2301.00001"],
    ["astro-ph/0001001", "astro-ph/0001001"],
    ["cs/0501001", "cs/0501001"],
    // ---- C. 对抗探针·收 ----
    ["2301.12345.pdf", "2301.12345"],
    ["2301.12345v2.pdf", "2301.12345v2"],
    ["arXiv:2301.12345.pdf", "2301.12345"],
    ["hep-th/9901001.pdf", "hep-th/9901001"],
    ["2301.12345/", "2301.12345"],
    ["/2301.12345", "2301.12345"],
    ["  2301.12345  ", "2301.12345"],
    ["arXiv : 2301.12345", "2301.12345"],
    ["ARXIV:2301.12345", "2301.12345"],
    ["https://arxiv.org/abs/2301.12345?x=?y#z", "2301.12345"],
    ["https://arxiv.org/pdf/2301.12345.PDF", "2301.12345"],
    ["doi:10.48550/arXiv.2301.12345v2", "2301.12345v2"],
    // DOI 尾斜杠：?# 截断后首尾 / 剥落在扩展名循环前——收
    ["https://doi.org/10.48550/arXiv.2301.12345/", "2301.12345"],
    ["https://www.doi.org/10.48550/arXiv.2301.12345", "2301.12345"],
    ["10.48550/arXiv.cs.AI/0001001", "cs/0001001"],
    ["https://arxiv.org/abs/astro-ph/0001001", "astro-ph/0001001"],
    ["https://arxiv.org/abs/cond-mat.mes-hall/0501234", "cond-mat/0501234"],
    ["https://arxiv.org/abs/math.GT/0309136", "math/0309136"],
    ["math.GT/0309136v2", "math/0309136v2"],
    ["2301.12345v03", "2301.12345v3"],
    ["2301.12345V2", "2301.12345v2"],
    ["https://arxiv.org/e-print/hep-th/9901001", "hep-th/9901001"],
    ["https://arxiv.org/src/2301.12345", "2301.12345"],
    ["https://arxiv.org/abs/hep-th--9901001", "hep-th/9901001"],
    // 旧版测试既有口径（class 剥壳后仍是同论文）
    ["2501.14787", "2501.14787"],
    ["2501.14787v2", "2501.14787v2"],
    ["arXiv:2501.14787", "2501.14787"],
    ["arxiv: hep-th/9901001", "hep-th/9901001"],
    ["hep-th/9901001v3", "hep-th/9901001v3"],
    ["math.AG/0601001", "math/0601001"],
    ["https://arxiv.org/abs/2501.14787", "2501.14787"],
    ["https://arxiv.org/pdf/2501.14787.pdf", "2501.14787"],
    ["https://arxiv.org/html/2501.14787v1", "2501.14787v1"],
    ["https://arxiv.org/format/2501.14787", "2501.14787"],
    ["arxiv.org/abs/2501.14787?utm_source=x#y", "2501.14787"],
    ["https://arxiv.org/abs/2501.14787/", "2501.14787"],
];

const REJECT: string[] = [
    // ---- A. 30 形表·拒 ----
    "https://doi.org/10.1145/3442188.3445922", // 非 arXiv DOI
    "https://arxiv.org/abs/2301.12345v0", // v0 非法
    "http://xxx.lanl.gov/abs/hep-th/9901001", // LANL 镜像（spec 不收）
    // ---- C. 对抗探针·拒 ----
    "ftp://arxiv.org/abs/2301.12345",
    "javascript://arxiv.org/abs/2301.12345",
    "https://lanl.gov/abs/2301.12345",
    "https://www.lanl.gov/abs/2301.12345",
    "https://alphaxiv.org/overview/2301.12345", // 未实证动词
    "https://arxiv.org:8080/abs/2301.12345", // 端口
    "https://arxiv.org/abs/2301.12345/extra", // 多路径段
    "https://arxiv.org/list/2301.12345", // list 动词
    "https://arxiv.org/abs/", // 空 id
    "https://arxiv.org/",
    "2301.12345v9999", // 4 位版本
    "2301.12345v2junk",
    "https://arxiv.org/abs/2301.12345v", // 裸 v
    "doi : 10.48550/arXiv.2301.12345", // 冒号前空格
    "",
    "   ",
    "arxiv.org", // 裸 host
    "https://arxiv.org//abs//2301.12345", // 双斜杠
    "https://arxiv.org./abs/2301.12345", // FQDN 尾点
    "https://arxiv.org.evil.com/abs/2301.12345", // 域名后缀寄生
    "https://notarxiv.org/abs/2301.12345",
    "https://arxiv.org@evil.com/abs/2301.12345", // userinfo 寄生
    "2301.00001/../2301.00002", // .. 逃逸
    "1999hep.th....1001X", // ADS bibcode 形
    "arXiv preprint 2301.12345", // 散文
    "２３０１.１２３４５", // 全角数字
    "2301.00001.bak-mock", // 未知尾巴
    "math.GT.BT/0309136", // 双 class
    "https://example.com/2501.14787",
    "https://arxiv.org/abs/2501.147", // 3 位序号
    "12345678",
    "not-an-id",
];

describe("parseArxivId —— canon 30 形 + spec §2 + 对抗收", () => {
    for (const [input, want] of ACCEPT) {
        it(`${input} → ${want}`, () => {
            expect(parseArxivId(input)).toBe(want);
        });
    }
});

describe("parseArxivId —— 对抗拒 + era 闸", () => {
    for (const input of REJECT) {
        it(`${JSON.stringify(input)} → null`, () => {
            expect(parseArxivId(input)).toBeNull();
        });
    }

    it("era 闸：MM 越界 / 未来态 / 旧形空窗", () => {
        expect(parseArxivId("1234.5678")).toBeNull(); // MM=34
        expect(parseArxivId("0000.0000")).toBeNull(); // MM=0
        expect(parseArxivId("9912.3456")).toBeNull(); // 2099-12 未来态
        expect(parseArxivId("0703.9999")).toBeNull(); // 新形早于 0704
        expect(parseArxivId("0704.0001")).toBe("0704.0001"); // 新形下限
        expect(parseArxivId("hep-th/0704001")).toBeNull(); // 旧形空窗 0704..9106
        expect(parseArxivId("hep-th/9107001")).toBe("hep-th/9107001"); // 旧形上限
        expect(parseArxivId("hep-th/9912001")).toBe("hep-th/9912001");
        expect(parseArxivId("hep-th/9913001")).toBeNull(); // MM=13
    });
});
