import { assert } from "chai";
import { getTexlateMark, setTexlateMark } from "../src/modules/attach";

/**
 * Item stub covering the mark seam: getField/setField over a field map +
 * a no-op saveTx (mark reads/writes touch nothing else on the item).
 */
function item(fields: Record<string, string>): Zotero.Item {
  return {
    getField: (name: string) => fields[name] ?? "",
    setField: (name: string, v: string) => {
      fields[name] = v;
    },
    saveTx: async () => {},
  } as unknown as Zotero.Item;
}

describe("attach marks", function () {
  describe("getTexlateMark", function () {
    it("parses the `texlate: t_*` line", function () {
      assert.strictEqual(
        getTexlateMark(item({ extra: "texlate: t_abc123" })),
        "t_abc123",
      );
    });

    it("tolerates full-width colon and mark mid-field", function () {
      assert.strictEqual(
        getTexlateMark(item({ extra: "PMID: 1\ntexlate：t_x9\nother" })),
        "t_x9",
      );
    });

    it("returns null for absent or non-task-id marks", function () {
      assert.isNull(getTexlateMark(item({})));
      assert.isNull(getTexlateMark(item({ extra: "no mark here" })));
      // mark value must be a task id (t_[a-z0-9]+)
      assert.isNull(getTexlateMark(item({ extra: "texlate: not-a-task" })));
    });
  });

  describe("setTexlateMark", function () {
    it("writes the mark into an empty extra", async function () {
      const it_ = item({});
      await setTexlateMark(it_, "t_new1");
      assert.strictEqual(getTexlateMark(it_), "t_new1");
    });

    it("appends after existing lines, keeping them byte-for-byte", async function () {
      const it_ = item({ extra: "PMID: 42\nsome note" });
      await setTexlateMark(it_, "t_new2");
      assert.strictEqual(
        it_.getField("extra" as _ZoteroTypes.Item.ItemField),
        "PMID: 42\nsome note\ntexlate: t_new2",
      );
    });

    it("replaces an existing mark line in place", async function () {
      const it_ = item({ extra: "before\ntexlate: t_old\nafter" });
      await setTexlateMark(it_, "t_new3");
      assert.strictEqual(
        it_.getField("extra" as _ZoteroTypes.Item.ItemField),
        "before\ntexlate: t_new3\nafter",
      );
    });

    it("inserts before a trailing empty line", async function () {
      const it_ = item({ extra: "tail\n" });
      await setTexlateMark(it_, "t_new4");
      assert.strictEqual(
        it_.getField("extra" as _ZoteroTypes.Item.ItemField),
        "tail\ntexlate: t_new4\n",
      );
    });
  });
});
