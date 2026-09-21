import { assert } from "chai";
import { errText, fieldText, sleep } from "../src/utils/misc";

/** getField-only item stub — fieldText must never touch anything else. */
function item(fields: Record<string, unknown>): Zotero.Item {
  return {
    getField: (name: string) => fields[name],
  } as unknown as Zotero.Item;
}

describe("utils/misc", function () {
  it("errText extracts .message from Errors", function () {
    assert.equal(errText(new Error("boom")), "boom");
    assert.equal(errText(new TypeError("bad type")), "bad type");
  });

  it("errText String()-coerces non-Error throws", function () {
    assert.equal(errText("plain"), "plain");
    assert.equal(errText(42), "42");
    assert.equal(errText(null), "null");
    assert.equal(errText(undefined), "undefined");
    assert.equal(errText({ toString: () => "weird" }), "weird");
  });

  it("fieldText returns string fields verbatim", function () {
    const it_ = item({ title: "Hello", extra: "line1\nline2" });
    assert.equal(fieldText(it_, "title"), "Hello");
    assert.equal(fieldText(it_, "extra"), "line1\nline2");
    assert.equal(fieldText(it_, "absent"), "");
  });

  it("fieldText tolerates non-item objects", function () {
    assert.equal(fieldText({} as unknown as Zotero.Item, "title"), "");
    assert.equal(
      fieldText(
        { getField: "not-a-function" } as unknown as Zotero.Item,
        "title",
      ),
      "",
    );
  });

  it("fieldText swallows a throwing getField", function () {
    const it_ = {
      getField: () => {
        throw new Error("denied");
      },
    } as unknown as Zotero.Item;
    assert.equal(fieldText(it_, "title"), "");
  });

  it("fieldText coerces non-strings, maps null/undefined to empty", function () {
    const it_ = item({
      num: 1234,
      nil: null,
      missing: undefined,
      flag: true,
    });
    assert.equal(fieldText(it_, "num"), "1234");
    assert.equal(fieldText(it_, "flag"), "true");
    assert.equal(fieldText(it_, "nil"), "");
    assert.equal(fieldText(it_, "missing"), "");
  });

  it("sleep resolves via bare setTimeout (Zotero.setTimeout is absent)", async function () {
    await sleep(1);
  });
});
