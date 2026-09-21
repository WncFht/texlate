import { assert } from "chai";
import { extractArxivId, hasArxivId } from "../src/modules/arxivId";

/** getField-only item stub — extraction reads DOI/url/archiveID/extra. */
function item(fields: Record<string, string>): Zotero.Item {
  return {
    getField: (name: string) => fields[name] ?? "",
  } as unknown as Zotero.Item;
}

// Table mirrors the docstring contract: raw ids keep vN suffixes and
// old-format slashes; the server's normalize_arxiv_id owns parsing.
const CASES: Array<[string, Record<string, string>, string | null]> = [
  // Level 1 — DOI 10.48550/arXiv.{id}
  ["DOI new-style", { DOI: "10.48550/arXiv.1706.03762" }, "1706.03762"],
  ["DOI old-style", { DOI: "10.48550/arXiv.hep-th/9901001" }, "hep-th/9901001"],
  ["DOI versioned", { DOI: "10.48550/arXiv.1706.03762v3" }, "1706.03762v3"],
  // Level 2 — url arxiv.org/(abs|pdf)/{id}
  ["url abs", { url: "https://arxiv.org/abs/2305.10601" }, "2305.10601"],
  [
    "url pdf strips .pdf",
    { url: "https://arxiv.org/pdf/2305.10601v2.pdf" },
    "2305.10601v2",
  ],
  [
    "url old-style keeps inner slash",
    { url: "https://arxiv.org/abs/hep-th/9901001" },
    "hep-th/9901001",
  ],
  [
    "url query cut",
    { url: "https://arxiv.org/abs/2305.10601?x=1" },
    "2305.10601",
  ],
  // Level 3 — archiveID (Zotero 7 preprint field)
  ["archiveID bare", { archiveID: "2201.00001" }, "2201.00001"],
  ["archiveID prefixed", { archiveID: "arXiv:2201.00001" }, "2201.00001"],
  // Level 4 — extra field, colon forms only
  ["extra colon", { extra: "arXiv: 2101.12345" }, "2101.12345"],
  ["extra full-width colon", { extra: "arXiv：2101.12345" }, "2101.12345"],
  [
    "extra trailing punctuation stripped",
    { extra: "arXiv: 2101.12345," },
    "2101.12345",
  ],
  ["extra old-style", { extra: "arXiv:hep-th/9901001" }, "hep-th/9901001"],
  [
    "extra mid-field line",
    { extra: "PMID: 123\narXiv: 2101.12345\nnote" },
    "2101.12345",
  ],
  // Negative
  ["no trace", { title: "An ordinary book" }, null],
  ["non-arxiv DOI", { DOI: "10.1234/elsewhere" }, null],
  ["non-arxiv url", { url: "https://example.com/x" }, null],
  ["malformed candidate rejected", { extra: "arXiv: not-an-id" }, null],
];

describe("extractArxivId", function () {
  for (const [name, fields, want] of CASES) {
    it(name, function () {
      assert.strictEqual(extractArxivId(item(fields)), want);
    });
  }

  it("returns null for non-item inputs", function () {
    assert.isNull(extractArxivId(null as unknown as Zotero.Item));
    assert.isNull(extractArxivId({} as unknown as Zotero.Item));
    assert.isNull(extractArxivId(42 as unknown as Zotero.Item));
  });

  it("prefers DOI over url/archiveID/extra", function () {
    const it_ = item({
      DOI: "10.48550/arXiv.1111.11111",
      url: "https://arxiv.org/abs/2222.22222",
      archiveID: "3333.33333",
      extra: "arXiv: 4444.44444",
    });
    assert.strictEqual(extractArxivId(it_), "1111.11111");
  });

  it("a level whose candidate fails the id shape falls through", function () {
    const it_ = item({
      DOI: "10.48550/arXiv.junk",
      url: "https://arxiv.org/abs/2305.10601",
    });
    assert.strictEqual(extractArxivId(it_), "2305.10601");
  });

  it("hasArxivId mirrors extraction", function () {
    assert.isTrue(hasArxivId(item({ DOI: "10.48550/arXiv.1706.03762" })));
    assert.isFalse(hasArxivId(item({ title: "nope" })));
  });
});
