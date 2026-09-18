import { assert } from "chai";
import { config } from "../package.json";

describe("startup", function () {
  it("should have plugin instance defined", function () {
    assert.isNotEmpty(Zotero[config.addonInstance]);
  });

  it("should be initialized", function () {
    assert.isTrue(Zotero[config.addonInstance].data.initialized);
  });
});
