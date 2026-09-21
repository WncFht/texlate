import { assert } from "chai";
import {
  ApiError,
  isActiveStatus,
  isRetryableStatus,
  isTerminalStatus,
  NetworkError,
  TimeoutError,
} from "../src/contracts";

describe("contracts", function () {
  describe("status guards", function () {
    it("isActiveStatus accepts exactly the five active states", function () {
      for (const s of [
        "queued",
        "fetching",
        "parsing",
        "translating",
        "compiling",
      ]) {
        assert.isTrue(isActiveStatus(s), s);
      }
      for (const s of ["done", "fault", "", "COMPILING", "active"]) {
        assert.isFalse(isActiveStatus(s), s);
      }
    });

    it("isTerminalStatus accepts exactly the six terminal states", function () {
      for (const s of [
        "done",
        "partial",
        "fault",
        "cancelled",
        "interrupted",
        "needs_auth",
      ]) {
        assert.isTrue(isTerminalStatus(s), s);
      }
      for (const s of ["queued", "translating", "", "Done"]) {
        assert.isFalse(isTerminalStatus(s), s);
      }
    });

    it("isRetryableStatus = terminal minus done (server RETRYABLE_FROM)", function () {
      for (const s of [
        "fault",
        "partial",
        "cancelled",
        "interrupted",
        "needs_auth",
      ]) {
        assert.isTrue(isRetryableStatus(s), s);
      }
      for (const s of ["done", "queued", "translating", ""]) {
        assert.isFalse(isRetryableStatus(s), s);
      }
    });

    it("active and terminal sets are disjoint", function () {
      for (const s of [
        "queued",
        "fetching",
        "parsing",
        "translating",
        "compiling",
      ]) {
        assert.isFalse(isTerminalStatus(s), s);
      }
    });
  });

  describe("ApiError", function () {
    it("parses JSON {detail, code} bodies", function () {
      const e = new ApiError(
        400,
        '{"detail":"bad arxiv id","code":"invalid_arxiv_id"}',
      );
      assert.strictEqual(e.status, 400);
      assert.strictEqual(e.code, "invalid_arxiv_id");
      assert.strictEqual(e.detail, "bad arxiv id");
      assert.strictEqual(e.message, "HTTP 400: bad arxiv id");
      assert.strictEqual(e.name, "ApiError");
      assert.strictEqual(e.payload?.code, "invalid_arxiv_id");
    });

    it("parses the 409 {detail, code, task_id} shape", function () {
      const body = JSON.stringify({
        detail: "task already running",
        code: "conflict",
        task_id: "t_abc123",
      });
      const e = new ApiError(409, body);
      assert.strictEqual(e.status, 409);
      assert.strictEqual(e.code, "conflict");
      assert.strictEqual(e.detail, "task already running");
      assert.strictEqual(e.payload?.task_id, "t_abc123");
    });

    it("falls back to error/message keys and the http_error default", function () {
      const e = new ApiError(500, '{"error":"boom","message":"kaput"}');
      assert.strictEqual(e.code, "boom");
      assert.strictEqual(e.detail, "kaput");

      const bare = new ApiError(502, "{}");
      assert.strictEqual(bare.code, "http_error");
      assert.strictEqual(bare.detail, "{}");
    });

    it("keeps the raw body when it is not JSON", function () {
      const e = new ApiError(503, "service unavailable");
      assert.strictEqual(e.code, "http_error");
      assert.strictEqual(e.detail, "service unavailable");
      assert.strictEqual(e.message, "HTTP 503: service unavailable");
      assert.isUndefined(e.payload);
    });

    it("is an Error; NetworkError/TimeoutError carry their names", function () {
      assert.instanceOf(new ApiError(400, ""), Error);
      assert.strictEqual(new NetworkError("x").name, "NetworkError");
      assert.strictEqual(new TimeoutError("x").name, "TimeoutError");
    });
  });
});
