import { assert } from "chai";
import type { EndpointProbeReport, EndpointsView } from "../src/contracts";
import { pickProbeTarget, summarizeProbe } from "../src/modules/prefs";

/**
 * prefs.ts 端点探针纯函数面：pickProbeTarget（目标 id 三级回退）与
 * summarizeProbe（报告 → { ok, label } verdict 令牌摘要）。
 * 纯函数不进 Zotero HTTP 面——checkEndpoint 的请求/状态行是它的薄壳。
 */

function profile(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    label: "",
    base_url: `https://${id}.test/api`,
    dialect: "auto",
    models: ["m1"],
    enabled: true,
    has_api_key: true,
    key_env: "",
    has_env_key: false,
    ...over,
  };
}

function view(
  profiles: ReturnType<typeof profile>[],
  active_id = "",
): EndpointsView {
  return { profiles, active_id };
}

function report(
  stage1: string,
  models: EndpointProbeReport["models"] = {},
): EndpointProbeReport {
  return {
    stage1: { verdict: stage1, models: [], detail: "" },
    models,
  };
}

describe("prefs 端点探针纯函数", function () {
  describe("pickProbeTarget", function () {
    it("active_id 优先", function () {
      const v = view([profile("a"), profile("b")], "b");
      assert.equal(pickProbeTarget(v), "b");
    });

    it("无活动命中 → 首个启用条目", function () {
      const v = view([profile("a", { enabled: false }), profile("b")]);
      assert.equal(pickProbeTarget(v), "b");
    });

    it("全停用且无活动 → 表头兜底（disabled 的活动行仍是活动）", function () {
      const v = view([profile("a", { enabled: false })]);
      assert.equal(pickProbeTarget(v), "a");
    });

    it("空表 → 空串", function () {
      assert.equal(pickProbeTarget(view([])), "");
    });
  });

  describe("summarizeProbe", function () {
    it("stage1 ok + 全 usable → ok + 模型·延迟行", function () {
      const s = summarizeProbe(
        report("ok", {
          "m-a": { verdict: "usable", latency_s: 0.4 },
          "m-b": { verdict: "usable", latency_s: 1.2 },
        }),
      );
      assert.isTrue(s.ok);
      assert.equal(s.label, "m-a 0.4s、m-b 1.2s");
    });

    it("stage1 auth_failed → not ok + stage1 令牌", function () {
      const s = summarizeProbe(report("auth_failed"));
      assert.isFalse(s.ok);
      assert.include(s.label, "stage1=auth_failed");
    });

    it("stage1 带 detail → 摘要附 detail", function () {
      const s = summarizeProbe({
        stage1: { verdict: "http_error", models: [], detail: "HTTP 502" },
        models: {},
      });
      assert.isFalse(s.ok);
      assert.equal(s.label, "stage1=http_error：HTTP 502");
    });

    it("无模型行 + stage1 ok → ok（空档案只到段1）", function () {
      const s = summarizeProbe(report("ok"));
      assert.isTrue(s.ok);
      assert.equal(s.label, "stage1=ok");
    });

    it("no_models_dir 也当活端点（异形端点无模型目录）", function () {
      const s = summarizeProbe(
        report("no_models_dir", { m1: { verdict: "usable" } }),
      );
      assert.isTrue(s.ok);
      assert.equal(s.label, "m1");
    });

    it("stage1 ok 但模型全灭 → not ok + 逐 uid=verdict", function () {
      const s = summarizeProbe(
        report("ok", {
          "m-a": { verdict: "no_cjk" },
          "m-b": { verdict: "empty" },
        }),
      );
      assert.isFalse(s.ok);
      assert.equal(s.label, "m-a=no_cjk m-b=empty");
    });

    it("usable 超 3 条折叠 +N", function () {
      const s = summarizeProbe(
        report("ok", {
          m1: { verdict: "usable" },
          m2: { verdict: "usable" },
          m3: { verdict: "usable" },
          m4: { verdict: "usable" },
          m5: { verdict: "usable" },
        }),
      );
      assert.isTrue(s.ok);
      assert.equal(s.label, "m1、m2、m3、+2");
    });

    it("缺 stage1 键 → unreachable 兜底不炸", function () {
      const s = summarizeProbe({});
      assert.isFalse(s.ok);
      assert.include(s.label, "unreachable");
    });
  });
});
