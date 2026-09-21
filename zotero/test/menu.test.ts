import { assert } from "chai";
import { computeMenuState } from "../src/modules/menu";

/**
 * Minimal Zotero.Item stub — computeMenuState only calls isRegularItem(),
 * and (via extractArxivId/getTexlateMark) getField().
 */
function fakeItem(fields: Record<string, string>, regular = true): Zotero.Item {
  return {
    isRegularItem: () => regular,
    getField: (name: string) => fields[name] ?? "",
  } as unknown as Zotero.Item;
}

const ARXIV = { DOI: "10.48550/arXiv.1706.03762" };
const MARKED = { extra: "texlate: t_abc123def" };
const ARXIV_MARKED = { DOI: "10.48550/arXiv.1706.03762", ...MARKED };

describe("computeMenuState", function () {
  it("translate only: arXiv id present, no texlate mark", function () {
    assert.deepEqual(computeMenuState([fakeItem(ARXIV)]), {
      translate: true,
      reader: false,
    });
  });

  it("reader only: texlate mark present", function () {
    assert.deepEqual(computeMenuState([fakeItem(MARKED)]), {
      translate: false,
      reader: true,
    });
  });

  it("marked item is not translatable even with an arXiv id", function () {
    assert.deepEqual(computeMenuState([fakeItem(ARXIV_MARKED)]), {
      translate: false,
      reader: true,
    });
  });

  it("mixed selection sets both flags", function () {
    assert.deepEqual(computeMenuState([fakeItem(ARXIV), fakeItem(MARKED)]), {
      translate: true,
      reader: true,
    });
  });

  it("non-regular items are filtered out entirely", function () {
    assert.deepEqual(computeMenuState([fakeItem(ARXIV_MARKED, false)]), {
      translate: false,
      reader: false,
    });
  });

  it("empty selection and id-less items hide both entries", function () {
    assert.deepEqual(computeMenuState([]), {
      translate: false,
      reader: false,
    });
    assert.deepEqual(computeMenuState([fakeItem({ title: "a book" })]), {
      translate: false,
      reader: false,
    });
  });
});
